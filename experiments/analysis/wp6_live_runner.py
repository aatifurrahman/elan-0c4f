#!/usr/bin/env python3
"""
WP6 / Rev3 Work Package E: Structured Live Verification & Telemetry Runner

Executes live verification against the private build of libfprint with SIGFM matcher,
capturing full telemetry: score, threshold, reason, fail_mask, kpts, scale, inliers, spread, duration.

Usage:
  # Genuine Block (e.g. Block 1, 20 touches):
  python3 experiments/analysis/wp6_live_runner.py --mode genuine --block 1 --count 20

  # Impostor trials (30 touches with un-enrolled finger):
  python3 experiments/analysis/wp6_live_runner.py --mode impostor --count 30

  # Real unlock-event simulation (up to 3 tries per event, 50 events):
  python3 experiments/analysis/wp6_live_runner.py --mode unlock-events --events 50

  # Statistical analysis of recorded results:
  python3 experiments/analysis/wp6_live_runner.py --mode analyze
"""

import argparse
import datetime
import math
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
EXP_DIR = os.path.dirname(HERE)
BUILD_DIR = os.path.join(EXP_DIR, "libfprint-upstream", "build_test")
VERIFY_BIN = os.path.join(BUILD_DIR, "examples", "verify")
STORAGE_FILE = os.path.join(EXP_DIR, "test-storage.variant")
DEFAULT_CSV = os.path.join(HERE, "wp6_live_results.csv")

# Failure bitmasks matching sigfm.h
FAIL_NONE                  = 0
FAIL_FEW_KEYPOINTS         = (1 << 0)
FAIL_FEW_CANDIDATE_PAIRS   = (1 << 1)
FAIL_RANSAC_FAILURE        = (1 << 2)
FAIL_INLIERS_BELOW_MIN     = (1 << 3)
FAIL_SPREAD_TOO_SMALL      = (1 << 4)
FAIL_SCALE_OUT_OF_BOUNDS   = (1 << 5)
FAIL_INLIERS_BELOW_THRESH  = (1 << 6)

BITMASK_NAMES = {
    FAIL_FEW_KEYPOINTS: "FEW_KEYPOINTS",
    FAIL_FEW_CANDIDATE_PAIRS: "FEW_CANDIDATE_PAIRS",
    FAIL_RANSAC_FAILURE: "RANSAC_FAILURE",
    FAIL_INLIERS_BELOW_MIN: "INLIERS_BELOW_MIN",
    FAIL_SPREAD_TOO_SMALL: "SPREAD_TOO_SMALL",
    FAIL_SCALE_OUT_OF_BOUNDS: "SCALE_OUT_OF_BOUNDS",
    FAIL_INLIERS_BELOW_THRESH: "INLIERS_BELOW_THRESH",
}

STAGE_RE = re.compile(
    r"sigfm stage (\d+)/(\d+):\s+score\s+(\d+)/(\d+)\s+\[status:\s+([^,\]]+)(?:,\s*mask:\s*(0x[0-9a-fA-F]+))?\]\s+"
    r"\(kpts:\s+probe=(\d+)/enrolled=(\d+),\s+cand=(\d+),\s+scale=([0-9.]+),\s+inliers=(\d+),\s+spread=\(([0-9.]+),\s*([0-9.]+)\),\s+time=([0-9.]+)ms\)"
)

CSV_HEADER = [
    "timestamp",
    "finger",
    "trial_type",
    "block_id",
    "event_idx",
    "try_in_event",
    "trial_idx",
    "matched",
    "score",
    "threshold",
    "reason",
    "fail_mask",
    "kpts_probe",
    "kpts_enrolled",
    "candidates",
    "scale",
    "inliers",
    "spread_x",
    "spread_y",
    "duration_ms"
]


def wilson_ci(k, n, conf=0.95):
    if n == 0:
        return (0.0, 0.0)
    z = 1.959963984540054 if conf == 0.95 else 1.6448536269514722
    p = k / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def find_usb_device():
    try:
        out = subprocess.check_output(["lsusb", "-d", "04f3:0c4f"], text=True).strip()
        if not out:
            return None
        parts = out.split()
        bus = parts[1]
        dev = parts[3].rstrip(":")
        return f"/dev/bus/usb/{bus}/{dev}"
    except Exception:
        return None


def ensure_device_access():
    dev = find_usb_device()
    if not dev:
        print("[ERROR] ELAN 04f3:0c4f fingerprint sensor not found on USB bus!", file=sys.stderr)
        sys.exit(1)
    if not (os.access(dev, os.R_OK) and os.access(dev, os.W_OK)):
        print(f"[!] Setting permissions for {dev} via setfacl...")
        subprocess.run(["sudo", "setfacl", "-m", f"u:{os.getlogin()}:rw", dev], check=False)


def run_single_touch(finger=7, timeout_sec=25):
    """
    Runs verify binary with finger input and parses stdout/stderr.
    Returns dict of telemetry.
    """
    ensure_device_access()
    env = os.environ.copy()
    env["G_MESSAGES_DEBUG"] = "all"

    # Input: finger chooser number (e.g. 7 for right middle), followed by newline
    p = subprocess.Popen(
        [VERIFY_BIN],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=EXP_DIR,
        env=env,
        text=True
    )

    try:
        stdout, _ = p.communicate(input=f"{finger}\n", timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        p.kill()
        stdout, _ = p.communicate()
        return {
            "matched": "no",
            "score": 0,
            "threshold": 12,
            "reason": "TIMEOUT",
            "fail_mask": "0x00",
            "kpts_probe": 0,
            "kpts_enrolled": 0,
            "candidates": 0,
            "scale": 0.0,
            "inliers": 0,
            "spread_x": 0.0,
            "spread_y": 0.0,
            "duration_ms": 0.0,
            "raw": stdout,
        }

    # Parse stages
    stages = []
    for line in stdout.splitlines():
        m = STAGE_RE.search(line)
        if m:
            st_idx = int(m.group(1))
            st_tot = int(m.group(2))
            score = int(m.group(3))
            thresh = int(m.group(4))
            status = m.group(5).strip()
            mask = m.group(6) if m.group(6) else "0x00"
            kp_p = int(m.group(7))
            kp_e = int(m.group(8))
            cand = int(m.group(9))
            scale = float(m.group(10))
            inliers = int(m.group(11))
            sp_x = float(m.group(12))
            sp_y = float(m.group(13))
            dur = float(m.group(14))
            stages.append({
                "stage": st_idx,
                "score": score,
                "threshold": thresh,
                "status": status,
                "mask": mask,
                "kpts_probe": kp_p,
                "kpts_enrolled": kp_e,
                "cand": cand,
                "scale": scale,
                "inliers": inliers,
                "spread_x": sp_x,
                "spread_y": sp_y,
                "dur": dur,
            })

    matched = "no"
    if "MATCH!" in stdout:
        matched = "yes"

    if stages:
        # If matched, pick the matching stage
        matching_stages = [s for s in stages if s["score"] >= s["threshold"] or s["status"] == "MATCH"]
        if matching_stages:
            best = matching_stages[0]
            matched = "yes"
        else:
            # Pick highest inliers stage as the representative closest attempt
            best = max(stages, key=lambda s: s["inliers"])
        
        return {
            "matched": matched,
            "score": best["score"],
            "threshold": best["threshold"],
            "reason": best["status"],
            "fail_mask": best["mask"],
            "kpts_probe": best["kpts_probe"],
            "kpts_enrolled": best["kpts_enrolled"],
            "candidates": best["cand"],
            "scale": best["scale"],
            "inliers": best["inliers"],
            "spread_x": best["spread_x"],
            "spread_y": best["spread_y"],
            "duration_ms": best["dur"],
            "raw": stdout,
        }
    else:
        # No stage line detected (could be sensor read failure / retry error)
        reason = "UNKNOWN"
        if "Retry error" in stdout or "FP_DEVICE_RETRY" in stdout:
            reason = "RETRY_ERROR"
        elif "Failed to load fingerprint" in stdout:
            reason = "STORAGE_LOAD_ERROR"
        return {
            "matched": matched,
            "score": 0,
            "threshold": 12,
            "reason": reason,
            "fail_mask": "0x00",
            "kpts_probe": 0,
            "kpts_enrolled": 0,
            "candidates": 0,
            "scale": 0.0,
            "inliers": 0,
            "spread_x": 0.0,
            "spread_y": 0.0,
            "duration_ms": 0.0,
            "raw": stdout,
        }


def init_csv(path):
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(",".join(CSV_HEADER) + "\n")


def append_csv_row(path, row_dict):
    init_csv(path)
    vals = [str(row_dict.get(h, "")) for h in CSV_HEADER]
    with open(path, "a") as f:
        f.write(",".join(vals) + "\n")


def run_genuine_block(block_id, count=20, finger=7, csv_path=DEFAULT_CSV):
    print("=" * 70)
    print(f" WP6 / Rev3 E1: Genuine Verification Block #{block_id} ({count} Touches)")
    print(f" Target Finger Choice: {finger} (enrolled in {STORAGE_FILE})")
    print(f" Logging to: {csv_path}")
    print("=" * 70)

    matches = 0
    total = 0

    for i in range(1, count + 1):
        print(f"\n[Block {block_id}] Trial {i}/{count} >>> TOUCH ENROLLED FINGER ON SENSOR NOW <<<")
        sys.stdout.flush()
        res = run_single_touch(finger=finger)
        now_ts = datetime.datetime.now().strftime("%Y-%m-%d_%H:%M:%S")

        matched = res["matched"]
        if matched == "yes":
            matches += 1
        total += 1

        row = {
            "timestamp": now_ts,
            "finger": finger,
            "trial_type": "genuine",
            "block_id": block_id,
            "event_idx": "",
            "try_in_event": "",
            "trial_idx": i,
            "matched": matched,
            "score": res["score"],
            "threshold": res["threshold"],
            "reason": res["reason"],
            "fail_mask": res["fail_mask"],
            "kpts_probe": res["kpts_probe"],
            "kpts_enrolled": res["kpts_enrolled"],
            "candidates": res["candidates"],
            "scale": f"{res['scale']:.3f}",
            "inliers": res["inliers"],
            "spread_x": f"{res['spread_x']:.1f}",
            "spread_y": f"{res['spread_y']:.1f}",
            "duration_ms": f"{res['duration_ms']:.2f}"
        }
        append_csv_row(csv_path, row)

        status_str = f"MATCH (score {res['score']}/{res['threshold']})" if matched == "yes" else f"NO MATCH ({res['reason']}, mask {res['fail_mask']})"
        print(f"  -> Result: {status_str} | inliers={res['inliers']}, scale={res['scale']:.3f}, time={res['duration_ms']:.1f}ms")
        print(f"  -> Cumulative Block {block_id}: {matches}/{total} matched ({(matches/total)*100:.1f}%)")

        if i < count:
            time.sleep(1.2)

    frr = (total - matches) / total
    ci_low, ci_high = wilson_ci(total - matches, total)
    print("\n" + "=" * 70)
    print(f" Block #{block_id} Complete: {matches}/{total} matches (FRR: {frr*100:.1f}%, 95% CI: [{ci_low*100:.1f}%, {ci_high*100:.1f}%])")
    print("=" * 70)


def run_impostor_series(count=30, finger=7, csv_path=DEFAULT_CSV):
    print("=" * 70)
    print(f" WP6 / Rev3 E1: Impostor Verification Series ({count} Touches)")
    print(" INSTRUCTION: Use non-enrolled fingers (e.g. left index, right ring/thumb)")
    print(f" Logging to: {csv_path}")
    print("=" * 70)

    falsely_accepted = 0
    total = 0

    for i in range(1, count + 1):
        print(f"\n[Impostor] Trial {i}/{count} >>> TOUCH UN-ENROLLED FINGER ON SENSOR NOW <<<")
        sys.stdout.flush()
        res = run_single_touch(finger=finger)
        now_ts = datetime.datetime.now().strftime("%Y-%m-%d_%H:%M:%S")

        matched = res["matched"]
        if matched == "yes":
            falsely_accepted += 1
        total += 1

        row = {
            "timestamp": now_ts,
            "finger": finger,
            "trial_type": "impostor",
            "block_id": "",
            "event_idx": "",
            "try_in_event": "",
            "trial_idx": i,
            "matched": matched,
            "score": res["score"],
            "threshold": res["threshold"],
            "reason": res["reason"],
            "fail_mask": res["fail_mask"],
            "kpts_probe": res["kpts_probe"],
            "kpts_enrolled": res["kpts_enrolled"],
            "candidates": res["candidates"],
            "scale": f"{res['scale']:.3f}",
            "inliers": res["inliers"],
            "spread_x": f"{res['spread_x']:.1f}",
            "spread_y": f"{res['spread_y']:.1f}",
            "duration_ms": f"{res['duration_ms']:.2f}"
        }
        append_csv_row(csv_path, row)

        status_str = f"FALSE ACCEPT! (score {res['score']}/{res['threshold']})" if matched == "yes" else f"REJECTED ({res['reason']}, mask {res['fail_mask']})"
        print(f"  -> Result: {status_str} | inliers={res['inliers']}, scale={res['scale']:.3f}, time={res['duration_ms']:.1f}ms")
        print(f"  -> Cumulative Impostor: {total - falsely_accepted}/{total} rejected")

        if i < count:
            time.sleep(1.2)

    far = falsely_accepted / total
    ci_low, ci_high = wilson_ci(falsely_accepted, total)
    print("\n" + "=" * 70)
    print(f" Impostor Series Complete: {falsely_accepted}/{total} false accepts (FAR: {far*100:.1f}%, 95% CI: [{ci_low*100:.1f}%, {ci_high*100:.1f}%])")
    print("=" * 70)


def run_unlock_events(num_events=50, finger=7, csv_path=DEFAULT_CSV):
    print("=" * 70)
    print(f" WP6 / Rev3 E1: Simulated Real Unlock Events ({num_events} Events, Up to 3 Tries/Event)")
    print(f" Target Finger Choice: {finger}")
    print(f" Logging to: {csv_path}")
    print("=" * 70)

    try_counts = {1: 0, 2: 0, 3: 0, "fail": 0}
    total_touches = 0

    for e in range(1, num_events + 1):
        print(f"\n========================================================================")
        print(f" UNLOCK EVENT {e} / {num_events}")
        print(f"========================================================================")

        event_resolved = False
        for t in range(1, 4):
            total_touches += 1
            print(f"  [Event {e} - Try {t}/3] >>> PLACE FINGER ON SENSOR <<<")
            sys.stdout.flush()
            res = run_single_touch(finger=finger)
            now_ts = datetime.datetime.now().strftime("%Y-%m-%d_%H:%M:%S")

            matched = res["matched"]
            row = {
                "timestamp": now_ts,
                "finger": finger,
                "trial_type": "unlock_event",
                "block_id": "",
                "event_idx": e,
                "try_in_event": t,
                "trial_idx": total_touches,
                "matched": matched,
                "score": res["score"],
                "threshold": res["threshold"],
                "reason": res["reason"],
                "fail_mask": res["fail_mask"],
                "kpts_probe": res["kpts_probe"],
                "kpts_enrolled": res["kpts_enrolled"],
                "candidates": res["candidates"],
                "scale": f"{res['scale']:.3f}",
                "inliers": res["inliers"],
                "spread_x": f"{res['spread_x']:.1f}",
                "spread_y": f"{res['spread_y']:.1f}",
                "duration_ms": f"{res['duration_ms']:.2f}"
            }
            append_csv_row(csv_path, row)

            if matched == "yes":
                print(f"  [PASS] UNLOCKED on Try {t}! (score {res['score']}/{res['threshold']}, inliers={res['inliers']})")
                try_counts[t] += 1
                event_resolved = True
                break
            else:
                print(f"  [MISS] Try {t} rejected: {res['reason']} (mask {res['fail_mask']}, inliers {res['inliers']})")
                if t < 3:
                    print("  -> Retrying in 1.5 seconds...")
                    time.sleep(1.5)

        if not event_resolved:
            print(f"  [FAIL] Unlock Event {e} FAILED after 3 attempts!")
            try_counts["fail"] += 1

        curr_failed = try_counts["fail"]
        print(f">> Running Total: {e - curr_failed}/{e} unlocked | Try1: {try_counts[1]}, Try2: {try_counts[2]}, Try3: {try_counts[3]}, Failed: {try_counts['fail']}")
        if e < num_events:
            print("Next unlock event starting in 2 seconds...")
            time.sleep(2.0)

    # Statistical Summary
    n_events = num_events
    n_fail = try_counts["fail"]
    fail_rate = n_fail / n_events
    ci_low, ci_high = wilson_ci(n_fail, n_events)

    # First-try FRR across the 50 events
    first_try_fails = n_events - try_counts[1]
    single_frr = first_try_fails / n_events
    indep_est = single_frr ** 3

    print("\n" + "=" * 70)
    print(" REAL UNLOCK EVENTS EVALUATION SUMMARY")
    print("=" * 70)
    print(f"Total Unlock Events Evaluated:  {n_events}")
    print(f"  - Resolved on Try 1:          {try_counts[1]} ({(try_counts[1]/n_events)*100:.1f}%)")
    print(f"  - Resolved on Try 2:          {try_counts[2]} ({(try_counts[2]/n_events)*100:.1f}%)")
    print(f"  - Resolved on Try 3:          {try_counts[3]} ({(try_counts[3]/n_events)*100:.1f}%)")
    print(f"  - Failed (Exhausted 3 Tries): {n_fail} ({(n_fail/n_events)*100:.1f}%)")
    print("-" * 70)
    print(f"Single-Touch First-Attempt FRR: {single_frr*100:.2f}% ({first_try_fails}/{n_events})")
    print(f"Independence Model Estimate (p³): {indep_est*100:.2f}%")
    print(f"MEASURED Three-Try Failure Rate: {fail_rate*100:.2f}% ({n_fail}/{n_events})")
    print(f"  95% Wilson Confidence Interval: [{ci_low*100:.2f}%, {ci_high*100:.2f}%]")
    print("=" * 70)


def analyze_results(csv_path=DEFAULT_CSV):
    if not os.path.exists(csv_path):
        print(f"[!] No CSV found at {csv_path}", file=sys.stderr)
        return

    import csv
    from collections import Counter, defaultdict

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print("=" * 78)
    print(f" WP6 / Rev3 E1: Live Benchmark Telemetry Analysis ({len(rows)} total rows)")
    print(f" Source: {csv_path}")
    print("=" * 78)

    # 1. Genuine Touches Analysis (by block)
    gen_rows = [r for r in rows if r.get("trial_type") == "genuine"]
    if gen_rows:
        print("\n--- 1. GENUINE TOUCH BLOCKS (Placement Learning Analysis) ---")
        blocks = sorted(list(set(r.get("block_id", "") for r in gen_rows if r.get("block_id", ""))))
        for b in blocks:
            b_rows = [r for r in gen_rows if r.get("block_id") == b]
            n_tot = len(b_rows)
            n_match = sum(1 for r in b_rows if r.get("matched") == "yes")
            n_fail = n_tot - n_match
            frr = n_fail / n_tot if n_tot > 0 else 0
            low, high = wilson_ci(n_fail, n_tot)
            match_inliers = [float(r["inliers"]) for r in b_rows if r.get("matched") == "yes"]
            mean_inl = sum(match_inliers) / len(match_inliers) if match_inliers else 0.0
            durs = [float(r["duration_ms"]) for r in b_rows if r.get("duration_ms")]
            mean_dur = sum(durs) / len(durs) if durs else 0.0
            print(f"Block {b:>2}: N={n_tot:2d} | Matched={n_match:2d} | Failed={n_fail:2d} | FRR={frr*100:5.1f}% (95% CI: [{low*100:4.1f}%, {high*100:4.1f}%]) | Match Inliers={mean_inl:.1f} | Mean Dur={mean_dur:.1f}ms")

        # Overall Genuine
        tot_g = len(gen_rows)
        match_g = sum(1 for r in gen_rows if r.get("matched") == "yes")
        fail_g = tot_g - match_g
        frr_g = fail_g / tot_g if tot_g > 0 else 0
        low_g, high_g = wilson_ci(fail_g, tot_g)
        print(f"OVERALL GENUINE: N={tot_g} | FRR={frr_g*100:.1f}% (95% CI: [{low_g*100:.1f}%, {high_g*100:.1f}%])")

        # Failure Breakdown
        print("\nGenuine Failure Reasons (Primary Attribution):")
        fail_rows = [r for r in gen_rows if r.get("matched") == "no"]
        if fail_rows:
            reason_counts = Counter(r.get("reason", "UNKNOWN") for r in fail_rows)
            for r_name, count in reason_counts.most_common():
                pct = (count / len(fail_rows)) * 100
                print(f"  - {r_name:<26}: {count:2d} ({pct:5.1f}% of failures)")

            print("\nGenuine Failure Bitmask Analysis (Multi-Condition Flags):")
            bit_counts = {name: 0 for name in BITMASK_NAMES.values()}
            for r in fail_rows:
                try:
                    mask_val = int(str(r.get("fail_mask", "0x00")), 16)
                    for bit_val, name in BITMASK_NAMES.items():
                        if mask_val & bit_val:
                            bit_counts[name] += 1
                except Exception:
                    pass
            for name, cnt in sorted(bit_counts.items(), key=lambda x: x[1], reverse=True):
                if cnt > 0:
                    pct = (cnt / len(fail_rows)) * 100
                    print(f"  * {name:<26}: {cnt:2d} touches ({pct:5.1f}%)")

    # 2. Impostor Touches Analysis
    imp_rows = [r for r in rows if r.get("trial_type") == "impostor"]
    if imp_rows:
        print("\n--- 2. IMPOSTOR TRIALS (False Accept Verification) ---")
        n_imp = len(imp_rows)
        fa_count = sum(1 for r in imp_rows if r.get("matched") == "yes")
        far = fa_count / n_imp if n_imp > 0 else 0
        low_imp, high_imp = wilson_ci(fa_count, n_imp)
        max_imp_inliers = max(int(r.get("inliers", 0)) for r in imp_rows) if imp_rows else 0
        margin = 12 - max_imp_inliers
        print(f"Trials: {n_imp} | False Accepts: {fa_count} | FAR: {far*100:.2f}% (95% CI: [{low_imp*100:.2f}%, {high_imp*100:.2f}%])")
        print(f"Max Impostor Inliers: {max_imp_inliers} / 12 (Security Margin: {margin} inliers)")
        print("\nImpostor Failure Attribution:")
        imp_reasons = Counter(r.get("reason", "UNKNOWN") for r in imp_rows)
        for r_name, count in imp_reasons.most_common():
            pct = (count / n_imp) * 100
            print(f"  - {r_name:<26}: {count:2d} ({pct:5.1f}%)")

    # 3. Unlock Events Simulation Analysis
    ue_rows = [r for r in rows if r.get("event_idx")]
    if ue_rows:
        print("\n--- 3. MEASURED UNLOCK-EVENT THREE-TRY RATE ---")
        events = defaultdict(list)
        for r in ue_rows:
            events[r["event_idx"]].append(r)

        n_ev = len(events)
        ev_summary = {}
        for ev_id, t_list in events.items():
            t_list_sorted = sorted(t_list, key=lambda x: int(x.get("try_in_event", 1) or 1))
            matched_try = None
            for item in t_list_sorted:
                if item.get("matched") == "yes":
                    matched_try = int(item.get("try_in_event", 1) or 1)
                    break
            ev_summary[ev_id] = matched_try if matched_try else "fail"

        c1 = sum(1 for v in ev_summary.values() if v == 1)
        c2 = sum(1 for v in ev_summary.values() if v == 2)
        c3 = sum(1 for v in ev_summary.values() if v == 3)
        cfail = sum(1 for v in ev_summary.values() if v == "fail")

        frr_1 = (n_ev - c1) / n_ev if n_ev > 0 else 0
        meas_fail_rate = cfail / n_ev if n_ev > 0 else 0
        ci_l, ci_h = wilson_ci(cfail, n_ev)
        indep_p3 = frr_1 ** 3

        print(f"Total Unlock Events:         {n_ev}")
        print(f"  - Solved on Try 1:         {c1:2d} ({(c1/n_ev)*100:5.1f}%)")
        print(f"  - Solved on Try 2:         {c2:2d} ({(c2/n_ev)*100:5.1f}%)")
        print(f"  - Solved on Try 3:         {c3:2d} ({(c3/n_ev)*100:5.1f}%)")
        print(f"  - Failed (3 Tries Out):    {cfail:2d} ({(cfail/n_ev)*100:5.1f}%)")
        print("-" * 50)
        print(f"Try-1 Single-Touch FRR:      {frr_1*100:.2f}% ({n_ev - c1}/{n_ev})")
        print(f"Independence Estimate (p³):  {indep_p3*100:.2f}%")
        print(f"MEASURED 3-Try Failure Rate: {meas_fail_rate*100:.2f}% ({cfail}/{n_ev})")
        print(f"  95% Wilson CI:             [{ci_l*100:.2f}%, {ci_h*100:.2f}%]")
    print("=" * 78)
    print("=" * 78)


def main():
    parser = argparse.ArgumentParser(description="WP6 / Rev3 E1 Live Verification & Telemetry Runner")
    parser.add_argument("--mode", choices=["genuine", "impostor", "unlock-events", "analyze"], required=True,
                        help="Operating mode: genuine block, impostor series, unlock-events sequence, or analyze")
    parser.add_argument("--block", type=int, default=1, help="Block ID for genuine trials (e.g. 1, 2, 3)")
    parser.add_argument("--count", type=int, default=20, help="Number of trials for genuine (default 20) or impostor (default 30)")
    parser.add_argument("--events", type=int, default=50, help="Number of unlock events to simulate (default 50)")
    parser.add_argument("--finger", type=int, default=7, help="Finger chooser index (default 7: right middle)")
    parser.add_argument("--csv", default=DEFAULT_CSV, help="Target results CSV path")

    args = parser.parse_args()

    if args.mode == "genuine":
        run_genuine_block(block_id=args.block, count=args.count, finger=args.finger, csv_path=args.csv)
    elif args.mode == "impostor":
        run_impostor_series(count=args.count, finger=args.finger, csv_path=args.csv)
    elif args.mode == "unlock-events":
        run_unlock_events(num_events=args.events, finger=args.finger, csv_path=args.csv)
    elif args.mode == "analyze":
        analyze_results(csv_path=args.csv)


if __name__ == "__main__":
    main()
