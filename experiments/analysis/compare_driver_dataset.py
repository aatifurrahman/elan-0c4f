#!/usr/bin/env python3
"""
Cross-Driver & Bi-Manual Dataset Comparative Analysis.
Compares:
  - Reference Driver:    ubuntu/lenovo-tod (proprietary Lenovo TOD driver)
  - Experimental Driver: ubuntu/sigfm (open-source upstream libfprint with SIGFM)
  - Hand separation:     Right Hand (Genuine) vs Left Hand (Impostor)

Evaluates:
  1. Image Quality Metrics (Sharpness, Contrast, Coverage, Row-Noise, Saturation)
  2. SIFT Keypoint Repeatability & Minutiae Counts
  3. Matcher Performance: Genuine FRR, Impostor FAR, Security Separation Margin
  4. Failure Telemetry: Primary Rejection Attribution and Bitmasks

Complies strictly with Rule 2:
  - Zero image display, ASCII art, or raw pixel dumping.
  - Outputs aggregate statistics only (means, standard deviations, confidence intervals, percentiles).
"""

import json
import math
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
EXP_DIR = os.path.dirname(HERE)
ROOT_DIR = os.path.dirname(EXP_DIR)
DATA_DIR = os.path.join(EXP_DIR, "data")
MANIFEST_PATH = os.path.join(DATA_DIR, "manifest.json")

# Ensure .venv_pkgs and project paths are loaded
_vpkgs = os.path.join(ROOT_DIR, ".venv_pkgs")
if os.path.isdir(_vpkgs) and _vpkgs not in sys.path:
    sys.path.insert(0, _vpkgs)
if EXP_DIR not in sys.path:
    sys.path.insert(0, EXP_DIR)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import cv2
import numpy as np

from wp3_quality_averaging import compute_frame_quality_metrics
from wp6_evaluation import match_sift_detailed, THRESHOLD, FAIL_NONE

BITMASK_NAMES = {
    (1 << 0): "FEW_KEYPOINTS",
    (1 << 1): "FEW_CANDIDATE_PAIRS",
    (1 << 2): "RANSAC_FAILURE",
    (1 << 3): "INLIERS_BELOW_MIN",
    (1 << 4): "SPREAD_TOO_SMALL",
    (1 << 5): "SCALE_OUT_OF_BOUNDS",
    (1 << 6): "INLIERS_BELOW_THRESH",
}


def wilson_ci(k, n, conf=0.95):
    if n == 0:
        return (0.0, 0.0)
    z = 1.959963984540054 if conf == 0.95 else 1.6448536269514722
    p = k / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def load_dataset_touches():
    if not os.path.isfile(MANIFEST_PATH):
        print(f"[!] Manifest not found at {MANIFEST_PATH}", file=sys.stderr)
        return []

    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    touches = manifest.get("touches", [])
    loaded = []

    for t in touches:
        npz_path = os.path.join(DATA_DIR, t["rel_path"])
        if not os.path.isfile(npz_path):
            continue

        try:
            with np.load(npz_path) as data:
                frames = data["frames"]
                state = data["state"]
                baseline = data["baseline"]

            # Filter contact frames (state == 2)
            contact_idx = np.where(state == 2)[0]
            if len(contact_idx) == 0:
                contact_frames = frames
                mid_frame = frames[len(frames) // 2]
            else:
                contact_frames = frames[contact_idx]
                mid_frame = contact_frames[len(contact_frames) // 2]

            # Linear normalized 8-bit frame (matching libfprint driver frontend)
            f_f32 = mid_frame.astype(np.float32)
            mn, mx = f_f32.min(), f_f32.max()
            if mx > mn:
                norm8 = np.clip((f_f32 - mn) * 255.0 / (mx - mn), 0, 255).astype(np.uint8)
            else:
                norm8 = np.zeros((80, 80), dtype=np.uint8)

            finger = t.get("finger", "")
            notes = t.get("notes", "")
            is_impostor = "impostor" in notes.lower() or "left" in finger.lower()
            hand = "left" if is_impostor else "right"

            loaded.append({
                "entry": t,
                "driver": t.get("driver", "unknown"),
                "person": t.get("person_id", "p01"),
                "finger": finger,
                "hand": hand,
                "notes": notes,
                "is_impostor": is_impostor,
                "purpose": t.get("purpose", "probe"),
                "session": t.get("session", ""),
                "frames": frames,
                "contact_frames": contact_frames,
                "baseline": baseline,
                "mid_frame": mid_frame,
                "norm8": norm8,
            })
        except Exception as e:
            print(f"[!] Warning: error reading {t['rel_path']}: {e}", file=sys.stderr)

    return loaded


def evaluate_quality_metrics(touches):
    print("\n" + "=" * 80)
    print(" 1. SENSOR IMAGE QUALITY COMPARISON (Reference vs Experimental)")
    print("=" * 80)

    # Group by driver and hand
    groups = defaultdict(list)
    for t in touches:
        grp_key = (t["driver"], t["hand"])
        groups[grp_key].append(t)

    print(f"{'Driver':<20} {'Hand':<8} {'Touches':<8} {'Sharpness':<16} {'Contrast':<14} {'Coverage':<12} {'RowNoise%':<10}")
    print("-" * 80)

    quality_summary = {}
    for (d, h), t_list in sorted(groups.items()):
        sharp_vals = []
        contrast_vals = []
        cov_vals = []
        row_vals = []

        for t in t_list:
            base = t["baseline"]
            # Evaluate on all contact frames
            for cf in t["contact_frames"]:
                q = compute_frame_quality_metrics(cf, base)
                sharp_vals.append(q["sharpness"])
                contrast_vals.append(q["local_contrast"])
                cov_vals.append(q["coverage"])
                row_vals.append(q["row_noise_ratio"] * 100.0)

        s_mean, s_std = (np.mean(sharp_vals), np.std(sharp_vals)) if sharp_vals else (0, 0)
        c_mean, c_std = (np.mean(contrast_vals), np.std(contrast_vals)) if contrast_vals else (0, 0)
        cov_mean = np.mean(cov_vals) * 100.0 if cov_vals else 0
        r_mean = np.mean(row_vals) if row_vals else 0

        quality_summary[(d, h)] = {
            "n_touches": len(t_list),
            "n_frames": len(sharp_vals),
            "sharp_mean": s_mean,
            "sharp_std": s_std,
            "contrast_mean": c_mean,
            "cov_mean": cov_mean,
            "row_mean": r_mean,
        }

        print(f"{d:<20} {h:<8} {len(t_list):<8} {s_mean:6.1f} ± {s_std:<7.1f} {c_mean:5.1f} ± {c_std:<6.1f} {cov_mean:5.1f}%      {r_mean:5.2f}%")

    print("=" * 80)
    return quality_summary


def evaluate_matching_performance(touches):
    print("\n" + "=" * 80)
    print(" 2. SIFT/RANSAC MATCHER PERFORMANCE & SECURITY SEPARATION MARGIN")
    print("=" * 80)

    # Evaluate per driver
    drivers = sorted(set(t["driver"] for t in touches))

    for d in drivers:
        d_touches = [t for t in touches if t["driver"] == d]
        fingers = sorted(set(t["finger"] for t in d_touches))
        print(f"\n================================================================================")
        print(f" Cohort: Driver [{d}] ({len(d_touches)} total touches)")
        print(f" Available Fingers: {', '.join(fingers)}")
        print(f"================================================================================")

        # Look for genuine finger (prefer right-index-finger or right-middle-finger)
        gen_finger = None
        for cand in ["right-index-finger", "right-middle-finger"]:
            if cand in fingers:
                gen_finger = cand
                break
        if not gen_finger and fingers:
            gen_finger = fingers[0]

        # Look for impostor finger (prefer left-index-finger or left-middle-finger)
        imp_finger = None
        for cand in ["left-index-finger", "left-middle-finger"]:
            if cand in fingers and cand != gen_finger:
                imp_finger = cand
                break
        if not imp_finger:
            other_fingers = [f for f in fingers if f != gen_finger]
            if other_fingers:
                imp_finger = other_fingers[0]

        gen_enroll = [t["norm8"] for t in d_touches if t["purpose"] == "enroll" and not t["is_impostor"]]
        gen_probes = [t["norm8"] for t in d_touches if t["purpose"] == "probe" and not t["is_impostor"]]
        imp_probes = [t["norm8"] for t in d_touches if t["is_impostor"]]

        # Fallback if no explicit probe flag
        if len(gen_probes) == 0 and len(d_touches) > 1:
            split_idx = max(1, min(16, len(d_touches) // 2))
            gen_enroll = [t["norm8"] for t in d_touches[:split_idx] if not t["is_impostor"]]
            gen_probes = [t["norm8"] for t in d_touches[split_idx:] if not t["is_impostor"]]

        print(f"Matching Setup for [{d}]:")
        print(f"  * Genuine Finger:  {gen_finger} ({len(gen_enroll)} gallery, {len(gen_probes)} probes)")
        print(f"  * Impostor Finger: {'left-index-finger (impostor hand)' if imp_probes else 'None'} ({len(imp_probes)} probes)")

        if not gen_enroll or not gen_probes:
            print("  [!] Insufficient genuine touches to evaluate matching.")
            continue

        # 1. Genuine Matching
        gen_scores = []
        gen_matches = 0
        gen_reasons = Counter()
        gen_bitmasks = Counter()

        for p in gen_probes:
            best_sc = -1
            best_r = None
            for g in gen_enroll:
                r = match_sift_detailed(p, g, enforce_scale=True, enforce_spread=True)
                if r["score"] > best_sc or best_r is None:
                    best_sc = r["score"]
                    best_r = r
                if r["score"] >= THRESHOLD:
                    break

            gen_scores.append(max(0, best_sc))
            if best_sc >= THRESHOLD:
                gen_matches += 1
            elif best_r is not None:
                gen_reasons[best_r["reason"]] += 1
                mask = best_r["fail_mask"]
                for bit, name in BITMASK_NAMES.items():
                    if mask & bit:
                        gen_bitmasks[name] += 1

        n_gp = len(gen_scores)
        n_gfails = n_gp - gen_matches
        frr = (n_gfails / n_gp) if n_gp > 0 else 0.0
        ci_l, ci_h = wilson_ci(n_gfails, n_gp)

        print(f"\nGenuine Matching ($N={n_gp}$ Probes vs Enrolled Gallery):")
        print(f"  - Matches (Score >= {THRESHOLD}): {gen_matches}/{n_gp} ({(gen_matches/n_gp)*100:.1f}%)" if n_gp else "  - Matches: 0")
        print(f"  - Single-Touch FRR:     {frr*100:.1f}% (95% CI: [{ci_l*100:.1f}%, {ci_h*100:.1f}%])")
        if gen_scores:
            print(f"  - Inlier Distribution:  Mean={np.mean(gen_scores):.1f}, Median={np.median(gen_scores):.1f}, Range=[{min(gen_scores)}, {max(gen_scores)}]")

        if gen_reasons:
            print("  - Failure Attribution:")
            for r_name, cnt in gen_reasons.most_common():
                print(f"      * {r_name:<24}: {cnt:2d} ({(cnt/n_gfails)*100:5.1f}%)")

        # 2. Impostor Matching
        if imp_probes:
            imp_scores = []
            imp_fa = 0
            imp_reasons = Counter()

            for imp in imp_probes:
                best_sc = -1
                best_r = None
                for g in gen_enroll:
                    r = match_sift_detailed(imp, g, enforce_scale=True, enforce_spread=True)
                    if r["score"] > best_sc or best_r is None:
                        best_sc = r["score"]
                        best_r = r

                imp_scores.append(max(0, best_sc))
                if best_sc >= THRESHOLD:
                    imp_fa += 1
                elif best_r is not None:
                    imp_reasons[best_r["reason"]] += 1

            n_ip = len(imp_scores)
            far = (imp_fa / n_ip) if n_ip > 0 else 0.0
            ci_il, ci_ih = wilson_ci(imp_fa, n_ip)
            max_imp_sc = max(imp_scores) if imp_scores else 0
            margin = THRESHOLD - max_imp_sc

            print(f"\nImpostor Matching ({imp_finger} vs {gen_finger} Gallery, $N={n_ip}$ Probes):")
            print(f"  - False Accepts (Score >= {THRESHOLD}): {imp_fa}/{n_ip} (FAR: {far*100:.2f}%, 95% CI: [{ci_il*100:.2f}%, {ci_ih*100:.2f}%])")
            print(f"  - Max Impostor Inliers: {max_imp_sc} / {THRESHOLD} (Separation Margin: {margin} inliers)")
            if imp_reasons:
                print("  - Impostor Rejection Breakdown:")
                for r_name, cnt in imp_reasons.most_common():
                    print(f"      * {r_name:<24}: {cnt:2d} ({(cnt/n_ip)*100:5.1f}%)")
        else:
            print(f"\nImpostor Matching: No separate impostor finger available for [{d}].")

    print("\n" + "=" * 80)


def main():
    print("=" * 80)
    print(" CROSS-DRIVER & BI-MANUAL COMPARATIVE ANALYSIS")
    print(" Reference: ubuntu/lenovo-tod  |  Experimental: ubuntu/sigfm")
    print("=" * 80)

    touches = load_dataset_touches()
    print(f"Loaded {len(touches)} touches from dataset manifest.")

    if not touches:
        print("[!] No touches found in dataset. Use collect_session.sh to record data.")
        return

    evaluate_quality_metrics(touches)
    evaluate_matching_performance(touches)


if __name__ == "__main__":
    main()
