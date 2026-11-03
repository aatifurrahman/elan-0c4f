#!/usr/bin/env python3
"""
E2: Opt-in Dogfood Logger for ELAN 04f3:0c4f SIGFM Matcher.
Monitors system fprintd service journal for real-world authentication events.
Appends one lightweight summary line per attempt:
  timestamp,outcome,score,threshold,reason,fail_mask,inliers,scale,duration_ms
Strictly NO images and NO keypoints recorded.
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
DEFAULT_LOG = os.path.join(EXP_DIR, "dogfood_log.csv")

CSV_HEADER = [
    "timestamp",
    "outcome",
    "score",
    "threshold",
    "reason",
    "fail_mask",
    "inliers",
    "scale",
    "duration_ms"
]

STAGE_RE = re.compile(
    r"sigfm stage (\d+)/(\d+):\s+score\s+(\d+)/(\d+)\s+\[status:\s+([^,\]]+)(?:,\s*mask:\s*(0x[0-9a-fA-F]+))?\]\s+"
    r"\(kpts:\s+probe=\d+/enrolled=\d+,\s+cand=\d+,\s+scale=([0-9.]+),\s+inliers=(\d+),\s+spread=\([0-9.]+,\s*[0-9.]+\),\s+time=([0-9.]+)ms\)"
)


def init_csv(path):
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(",".join(CSV_HEADER) + "\n")


def append_entry(path, row_dict):
    init_csv(path)
    vals = [str(row_dict.get(h, "")) for h in CSV_HEADER]
    with open(path, "a") as f:
        f.write(",".join(vals) + "\n")
        f.flush()


def run_monitor(csv_path=DEFAULT_LOG):
    init_csv(csv_path)
    print(f"[*] Starting dogfood journal monitor...")
    print(f"[*] Logging attempts to: {csv_path}")
    print("[*] Listening for fprintd authentication attempts...")
    sys.stdout.flush()

    # Start journalctl following fprintd
    cmd = ["journalctl", "-u", "fprintd", "-f", "-n", "0"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

    current_stages = []
    last_event_time = time.time()

    try:
        for line in iter(proc.stdout.readline, ""):
            line_str = line.strip()
            if not line_str:
                continue

            m = STAGE_RE.search(line_str)
            if m:
                st_idx = int(m.group(1))
                st_tot = int(m.group(2))
                score = int(m.group(3))
                thresh = int(m.group(4))
                status = m.group(5).strip()
                mask = m.group(6) if m.group(6) else "0x00"
                scale = float(m.group(7))
                inliers = int(m.group(8))
                dur = float(m.group(9))

                stage_info = {
                    "stage": st_idx,
                    "score": score,
                    "threshold": thresh,
                    "status": status,
                    "mask": mask,
                    "scale": scale,
                    "inliers": inliers,
                    "dur": dur
                }
                current_stages.append(stage_info)
                last_event_time = time.time()

                # If match occurred, flush event
                if score >= thresh or status == "MATCH":
                    flush_event(csv_path, current_stages, matched=True)
                    current_stages = []
                elif st_idx == st_tot:
                    # Final stage reached without match
                    flush_event(csv_path, current_stages, matched=False)
                    current_stages = []

    except KeyboardInterrupt:
        print("\n[*] Stopping dogfood monitor...")
    finally:
        proc.terminate()


def flush_event(csv_path, stages, matched):
    if not stages:
        return
    now_ts = datetime.datetime.now().strftime("%Y-%m-%d_%H:%M:%S")

    if matched:
        # First matching stage
        matching = [s for s in stages if s["score"] >= s["threshold"] or s["status"] == "MATCH"]
        best = matching[0] if matching else stages[-1]
        outcome = "MATCH"
    else:
        # Highest inliers attempt
        best = max(stages, key=lambda s: s["inliers"])
        outcome = "NO_MATCH"

    row = {
        "timestamp": now_ts,
        "outcome": outcome,
        "score": best["score"],
        "threshold": best["threshold"],
        "reason": best["status"],
        "fail_mask": best["mask"],
        "inliers": best["inliers"],
        "scale": f"{best['scale']:.3f}",
        "duration_ms": f"{best['dur']:.2f}"
    }
    append_entry(csv_path, row)
    print(f"[{now_ts}] {outcome} | score={best['score']}/{best['threshold']} | inliers={best['inliers']} | scale={best['scale']:.3f} | reason={best['status']} | mask={best['mask']} ({best['dur']:.1f}ms)")
    sys.stdout.flush()


def generate_summary(csv_path=DEFAULT_LOG):
    if not os.path.exists(csv_path):
        print(f"[!] Dogfood log {csv_path} does not exist yet.", file=sys.stderr)
        return

    import csv
    from collections import Counter

    with open(csv_path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print("[!] Dogfood log is empty.", file=sys.stderr)
        return

    n_tot = len(rows)
    n_match = sum(1 for r in rows if r.get("outcome") == "MATCH")
    n_fail = n_tot - n_match
    frr = n_fail / n_tot if n_tot > 0 else 0

    durations = [float(r["duration_ms"]) for r in rows if r.get("duration_ms")]
    mean_dur = sum(durations) / len(durations) if durations else 0.0
    durations_sorted = sorted(durations)
    p95_dur = durations_sorted[int(0.95 * len(durations_sorted))] if durations_sorted else 0.0

    print("=" * 70)
    print(f" E2: OPT-IN DOGFOOD TELEMETRY SUMMARY ({n_tot} Total Real Attempts)")
    print(f" Log File: {csv_path}")
    print("=" * 70)
    print(f"Total Attempts Logged:      {n_tot}")
    print(f"Successful Matches:         {n_match} ({(n_match/n_tot)*100:.1f}%)")
    print(f"Failed Touches (FRR):       {n_fail} ({frr*100:.1f}%)")
    print(f"Mean Matching Duration:     {mean_dur:.2f} ms (p95: {p95_dur:.2f} ms)")

    print("\nFailure Breakdown by Reason:")
    fail_rows = [r for r in rows if r.get("outcome") == "NO_MATCH"]
    if fail_rows:
        reasons = Counter(r.get("reason", "UNKNOWN") for r in fail_rows)
        for r_name, cnt in reasons.most_common():
            print(f"  - {r_name:<26}: {cnt:3d} ({(cnt/len(fail_rows))*100:5.1f}%)")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="E2 Opt-In Dogfood Logger")
    parser.add_argument("--action", choices=["monitor", "summary"], default="monitor",
                        help="Action: run monitor daemon or generate summary")
    parser.add_argument("--csv", default=DEFAULT_LOG, help="Target log CSV path")
    args = parser.parse_args()

    if args.action == "monitor":
        run_monitor(csv_path=args.csv)
    elif args.action == "summary":
        generate_summary(csv_path=args.csv)


if __name__ == "__main__":
    main()
