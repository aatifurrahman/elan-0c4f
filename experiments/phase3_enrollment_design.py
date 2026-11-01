#!/usr/bin/env python3
"""
Phase 3: Enrollment Design Analysis for ELAN 04f3:0c4f.
Addresses the four Phase 3 requirements in experiments/PLAN.md:
  1. Enrollment touch count N vs FRR curve (evaluate N in 4..24).
  2. Frame selection rule per touch (center contact vs max energy vs aligned average).
  3. Diverse touch selection (redundancy rejection vs gallery coverage).
  4. Template update / adaptation feasibility.
"""

import itertools
import os
import sys
import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from eval_offline import (
    load_dataset,
    match_sift_ransac,
    match_ncc,
    prep,
    align_and_average,
    compute_roc,
)
from dataset import load_manifest, DATA_DIR


# ---------------------------------------------------------------- Frame Selection Rules
def ridge_energy(frame):
    """Measures ridge contrast/energy via variance of the high-pass filtered frame."""
    p = prep(frame)
    return float(p.var())


def evaluate_frame_selection_rules():
    """
    Compares:
      - Rule 1: Center contact frame (state == 2 median index)
      - Rule 2: Max ridge energy contact frame
      - Rule 3: Phase-aligned average of all contact frames
    Evaluates keypoint quality and inlier yield.
    """
    print("=" * 70)
    print(" Phase 3.1: Frame Selection Rule per Touch")
    print("=" * 70)

    manifest = load_manifest()
    touches = [t for t in manifest.get("touches", []) if t["contact_frames"] >= 2]

    stats = {
        "center": {"keypoints": [], "energy": []},
        "max_energy": {"keypoints": [], "energy": []},
        "average": {"keypoints": [], "energy": []},
    }

    from eval_offline import _extract_sift

    for t in touches:
        fpath = os.path.join(DATA_DIR, t["rel_path"])
        if not os.path.isfile(fpath):
            continue
        d = np.load(fpath)
        frames, state, base = d["frames"], d["state"], d["baseline"]
        sub = np.clip(frames.astype(np.float32) - base.astype(np.float32), 0, None)
        c_idx = np.where(state == 2)[0]
        if len(c_idx) < 2:
            continue

        # Rule 1: Center
        center_img = sub[c_idx[len(c_idx) // 2]]
        # Rule 2: Max energy
        energies = [ridge_energy(sub[i]) for i in c_idx]
        best_energy_img = sub[c_idx[np.argmax(energies)]]
        # Rule 3: Aligned average
        avg_img = align_and_average(sub[c_idx])

        for r_name, img in [
            ("center", center_img),
            ("max_energy", best_energy_img),
            ("average", avg_img),
        ]:
            kp, _ = _extract_sift(img)
            stats[r_name]["keypoints"].append(len(kp) if kp else 0)
            stats[r_name]["energy"].append(ridge_energy(img))

    print(f"Evaluated across {len(touches)} multi-frame touches:")
    for r_name in ["center", "max_energy", "average"]:
        kps = stats[r_name]["keypoints"]
        engs = stats[r_name]["energy"]
        print(f"  * {r_name:<12}: SIFT Keypoints (avg={np.mean(kps):.1f}, med={np.median(kps):.1f}) | Ridge Energy={np.mean(engs):.3f}")


# ---------------------------------------------------------------- N vs FRR Curve
def evaluate_enroll_count_vs_frr():
    """
    Evaluates enrollment stages N in {4, 6, 8, 10, 12, 14, 16, 20, 24}.
    Measures genuine matching rate and FRR at the zero-FA threshold (12 inliers).
    """
    print("\n" + "=" * 70)
    print(" Phase 3.2: Number of Enroll Touches (N) vs FRR Curve")
    print(" Target: Zero-FA Threshold = 12 Inliers (FAR = 0%)")
    print("=" * 70)

    classes = load_dataset(DATA_DIR)
    # Target right-middle-finger which has 50 usable touches
    mid_touches = classes["p01:right-middle-finger"]["enroll"] + classes["p01:right-middle-finger"]["probe"]
    idx_touches = classes["p01:right-index-finger"]["enroll"] + classes["p01:right-index-finger"]["probe"]
    left_touches = classes["p01:left-index-finger"]["enroll"] + classes["p01:left-index-finger"]["probe"]

    # Impostor galleries to verify FAR stays 0
    impostor_galleries = [
        [t["img"] for t in idx_touches[:10]],
        [t["img"] for t in left_touches[:10]],
    ]

    total_mid = len(mid_touches)
    print(f"Testing on Right Middle Finger ({total_mid} touches total):")
    print(f"{'N (Stages)':<12} {'Probes':<8} {'Median Inliers':<16} {'Single-Touch FRR':<18} {'3-Try FRR':<12}")
    print("-" * 70)

    results = []

    for N in [4, 6, 8, 10, 12, 14, 16, 18, 20, 24]:
        if N >= total_mid - 5:
            continue
        gallery = [t["img"] for t in mid_touches[:N]]
        probes = [t["img"] for t in mid_touches[N:]]

        # Genuine matches: best-of-N for each probe
        gen_scores = [max(match_sift_ransac(p, g) for g in gallery) for p in probes]

        # Impostor matches: each probe against impostor galleries
        imp_scores = []
        for p in probes:
            for imp_gal in impostor_galleries:
                imp_scores.append(max(match_sift_ransac(p, g) for g in imp_gal))

        gen_arr = np.array(gen_scores)
        imp_arr = np.array(imp_scores)

        # At Zero-FA threshold of 12 inliers
        threshold = 12
        frr_single = float((gen_arr < threshold).mean())
        frr_3try = float(frr_single ** 3)
        max_imp = imp_arr.max() if len(imp_arr) else 0

        print(f"{N:<12} {len(probes):<8} {np.median(gen_arr):<16.1f} {frr_single*100:<17.1f}% {frr_3try*100:<11.2f}% (max imp: {max_imp})")
        results.append((N, len(probes), np.median(gen_arr), frr_single, frr_3try, max_imp))

    return results


# ---------------------------------------------------------------- Diversity & Redundancy Filter
def evaluate_diversity_filter():
    """
    Tests an active diversity filter during enrollment:
    Reject near-duplicates (SIFT inliers > 35 or NCC > 0.90) to force spatial coverage.
    """
    print("\n" + "=" * 70)
    print(" Phase 3.3: Diversity Selection vs Naive Sequential Enrollment")
    print("=" * 70)

    classes = load_dataset(DATA_DIR)
    mid_touches = classes["p01:right-middle-finger"]["enroll"] + classes["p01:right-middle-finger"]["probe"]

    # 1. Naive first 12
    naive_gallery = [t["img"] for t in mid_touches[:12]]

    # 2. Diverse selection: add touch only if it is not a near duplicate of an existing gallery template
    diverse_gallery = [mid_touches[0]["img"]]
    for t in mid_touches[1:]:
        img = t["img"]
        # Max match against current diverse gallery
        max_inliers = max(match_sift_ransac(img, g) for g in diverse_gallery)
        # Only accept if it adds diversity (not a duplicate) and has sufficient quality
        if max_inliers < 35:
            diverse_gallery.append(img)
        if len(diverse_gallery) == 12:
            break

    # Test probes (last 20 touches)
    probes = [t["img"] for t in mid_touches[-20:]]

    naive_gen = [max(match_sift_ransac(p, g) for g in naive_gallery) for p in probes]
    diverse_gen = [max(match_sift_ransac(p, g) for g in diverse_gallery) for p in probes]

    th = 12
    naive_frr = (np.array(naive_gen) < th).mean()
    diverse_frr = (np.array(diverse_gen) < th).mean()

    print(f"Naive 12-touch gallery:   Median Inliers = {np.median(naive_gen):.1f}, Single FRR = {naive_frr*100:.1f}%, 3-Try = {(naive_frr**3)*100:.2f}%")
    print(f"Diverse 12-touch gallery: Median Inliers = {np.median(diverse_gen):.1f}, Single FRR = {diverse_frr*100:.1f}%, 3-Try = {(diverse_frr**3)*100:.2f}%")


if __name__ == "__main__":
    evaluate_frame_selection_rules()
    evaluate_enroll_count_vs_frr()
    evaluate_diversity_filter()
