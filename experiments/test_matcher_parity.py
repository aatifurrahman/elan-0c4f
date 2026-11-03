#!/usr/bin/env python3
"""
Exhaustive Golden-Vector and Dataset Parity Test (WP1):
C++ (libfprint/sigfm/sigfm.cpp via sigfm_scorer) vs Python (eval_offline.py).

Validates decision and score parity across every gallery/probe pair used in Phase 3
(all fingers, all touches) plus golden image vectors.
"""

import os
import sys
import tempfile
import subprocess
import numpy as np

# Setup import path for .venv_pkgs and local experiments
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
_vpkgs = os.path.join(ROOT, ".venv_pkgs")
if os.path.isdir(_vpkgs) and _vpkgs not in sys.path:
    sys.path.insert(0, _vpkgs)
sys.path.insert(0, HERE)

import cv2
from eval_offline import load_dataset, match_sift_ransac, DATA_DIR

CPP_BIN = os.path.join(HERE, "sigfm_scorer")
THRESHOLD = 12


def norm_u8(f):
    f_min = float(f.min())
    f_max = float(f.max())
    denom = f_max - f_min if f_max > f_min else 1.0
    return np.clip((f - f_min) * 255.0 / denom, 0, 255).astype(np.uint8)


def write_pgm(path, img_u8):
    with open(path, "wb") as f:
        f.write(f"P5\n{img_u8.shape[1]} {img_u8.shape[0]}\n255\n".encode("ascii"))
        f.write(img_u8.tobytes())


def run_cpp_batch(pairs):
    """
    Runs sigfm_scorer in batch mode:
    pairs: list of (path_a, path_b)
    Returns: list of int scores
    """
    with tempfile.NamedTemporaryFile("w", delete=False) as f:
        for pa, pb in pairs:
            f.write(f"{pa} {pb}\n")
        batch_file = f.name

    try:
        cmd = [CPP_BIN, "--batch", batch_file]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        scores = [int(line.strip()) for line in proc.stdout.strip().splitlines() if line.strip()]
        if len(scores) != len(pairs):
            raise RuntimeError(f"Expected {len(pairs)} scores from sigfm_scorer, got {len(scores)}")
        return scores
    finally:
        if os.path.exists(batch_file):
            os.remove(batch_file)


def run_parity_test():
    if not os.path.exists(CPP_BIN):
        print(f"Error: {CPP_BIN} not found. Please compile it first.")
        sys.exit(1)

    print("=" * 80)
    print(" WP1: Exhaustive Parity Test: C++ (sigfm.cpp) vs Python (eval_offline.py)")
    print(f" C++ Binary: {CPP_BIN}")
    print(f" Decision Threshold: {THRESHOLD} inliers")
    print("=" * 80)

    classes = load_dataset(DATA_DIR)
    mid_touches = classes["p01:right-middle-finger"]["enroll"] + classes["p01:right-middle-finger"]["probe"]
    idx_touches = classes["p01:right-index-finger"]["enroll"] + classes["p01:right-index-finger"]["probe"]
    left_touches = classes["p01:left-index-finger"]["enroll"] + classes["p01:left-index-finger"]["probe"]

    print(f"Dataset summary:")
    print(f"  * Right Middle: {len(mid_touches)} touches")
    print(f"  * Right Index:  {len(idx_touches)} touches")
    print(f"  * Left Index:   {len(left_touches)} touches")

    all_pairs = []  # list of dicts

    # 1. Golden file pairs
    pgm_enrolled = os.path.join(HERE, "enrolled.pgm")
    pgm_verify = os.path.join(HERE, "verify.pgm")
    if os.path.exists(pgm_enrolled) and os.path.exists(pgm_verify):
        img_e = cv2.imread(pgm_enrolled, cv2.IMREAD_GRAYSCALE)
        img_v = cv2.imread(pgm_verify, cv2.IMREAD_GRAYSCALE)
        all_pairs.append({
            "desc": "Golden: enrolled.pgm self-match",
            "img_a": img_e, "img_b": img_e,
            "path_a": pgm_enrolled, "path_b": pgm_enrolled,
            "label": "genuine",
        })
        all_pairs.append({
            "desc": "Golden: verify.pgm self-match",
            "img_a": img_v, "img_b": img_v,
            "path_a": pgm_verify, "path_b": pgm_verify,
            "label": "genuine",
        })
        all_pairs.append({
            "desc": "Golden: enrolled vs verify cross-match",
            "img_a": img_e, "img_b": img_v,
            "path_a": pgm_enrolled, "path_b": pgm_verify,
            "label": "impostor",
        })

    # 2. Phase 3 dataset pairs (N=16 gallery vs probes + impostor galleries)
    with tempfile.TemporaryDirectory() as tmpdir:
        # Pre-save normalized PGMs for all touches
        def save_touch_pgms(touch_list, prefix):
            paths = []
            u8_imgs = []
            for idx, t in enumerate(touch_list):
                u8 = norm_u8(t["img"])
                p = os.path.join(tmpdir, f"{prefix}_{idx:03d}.pgm")
                write_pgm(p, u8)
                paths.append(p)
                u8_imgs.append(u8)
            return paths, u8_imgs

        p_mid, u_mid = save_touch_pgms(mid_touches, "mid")
        p_idx, u_idx = save_touch_pgms(idx_touches, "idx")
        p_left, u_left = save_touch_pgms(left_touches, "left")

        # Phase 3 N=16 Gallery for Right Middle
        mid_gallery_p = p_mid[:16]
        mid_gallery_u = u_mid[:16]
        mid_probes_p = p_mid[16:]
        mid_probes_u = u_mid[16:]

        # A. Genuine pairs: mid probes vs mid gallery (34 * 16 = 544 pairs)
        for pi, (pa, ua) in enumerate(zip(mid_probes_p, mid_probes_u)):
            for gi, (pb, ub) in enumerate(zip(mid_gallery_p, mid_gallery_u)):
                all_pairs.append({
                    "desc": f"RM Probe {pi+16} vs RM Gallery {gi}",
                    "img_a": ua, "img_b": ub,
                    "path_a": pa, "path_b": pb,
                    "label": "genuine",
                })

        # B. Impostor pairs: mid probes vs Right Index gallery (34 * 10 = 340 pairs)
        for pi, (pa, ua) in enumerate(zip(mid_probes_p, mid_probes_u)):
            for gi, (pb, ub) in enumerate(zip(p_idx[:10], u_idx[:10])):
                all_pairs.append({
                    "desc": f"RM Probe {pi+16} vs RI Impostor {gi}",
                    "img_a": ua, "img_b": ub,
                    "path_a": pa, "path_b": pb,
                    "label": "impostor",
                })

        # C. Impostor pairs: mid probes vs Left Index gallery (34 * 10 = 340 pairs)
        for pi, (pa, ua) in enumerate(zip(mid_probes_p, mid_probes_u)):
            for gi, (pb, ub) in enumerate(zip(p_left[:10], u_left[:10])):
                all_pairs.append({
                    "desc": f"RM Probe {pi+16} vs LI Impostor {gi}",
                    "img_a": ua, "img_b": ub,
                    "path_a": pa, "path_b": pb,
                    "label": "impostor",
                })

        # D. Genuine pairs for Right Index (5 probes * 10 gallery = 50 pairs)
        for pi, (pa, ua) in enumerate(zip(p_idx[10:], u_idx[10:])):
            for gi, (pb, ub) in enumerate(zip(p_idx[:10], u_idx[:10])):
                all_pairs.append({
                    "desc": f"RI Probe {pi+10} vs RI Gallery {gi}",
                    "img_a": ua, "img_b": ub,
                    "path_a": pa, "path_b": pb,
                    "label": "genuine",
                })

        # E. Genuine pairs for Left Index (5 probes * 10 gallery = 50 pairs)
        for pi, (pa, ua) in enumerate(zip(p_left[10:], u_left[10:])):
            for gi, (pb, ub) in enumerate(zip(p_left[:10], u_left[:10])):
                all_pairs.append({
                    "desc": f"LI Probe {pi+10} vs LI Gallery {gi}",
                    "img_a": ua, "img_b": ub,
                    "path_a": pa, "path_b": pb,
                    "label": "genuine",
                })

        # F. Impostor cross pairs: Right Index vs Left Index (10 * 10 = 100 pairs)
        for pi, (pa, ua) in enumerate(zip(p_idx[:10], u_idx[:10])):
            for gi, (pb, ub) in enumerate(zip(p_left[:10], u_left[:10])):
                all_pairs.append({
                    "desc": f"RI {pi} vs LI {gi}",
                    "img_a": ua, "img_b": ub,
                    "path_a": pa, "path_b": pb,
                    "label": "impostor",
                })

        print(f"Total pairs to evaluate: {len(all_pairs)} pairs")
        print("Running C++ batch matcher...")
        batch_args = [(item["path_a"], item["path_b"]) for item in all_pairs]
        cpp_scores = run_cpp_batch(batch_args)

        print("Running Python matcher...")
        py_scores = []
        for item in all_pairs:
            s = match_sift_ransac(item["img_a"], item["img_b"])
            py_scores.append(s)

    # Analyze Parity
    diffs = []
    flips = []
    max_diff = 0
    gen_diffs = []
    imp_diffs = []

    imp_max_cpp = 0
    imp_max_py = 0

    for idx, (item, c_score, p_score) in enumerate(zip(all_pairs, cpp_scores, py_scores)):
        diff = abs(c_score - p_score)
        diffs.append(diff)
        if diff > max_diff:
            max_diff = diff

        c_dec = "MATCH" if c_score >= THRESHOLD else "REJECT"
        p_dec = "MATCH" if p_score >= THRESHOLD else "REJECT"

        if item["label"] == "genuine":
            gen_diffs.append(diff)
        else:
            imp_diffs.append(diff)
            imp_max_cpp = max(imp_max_cpp, c_score)
            imp_max_py = max(imp_max_py, p_score)

        if c_dec != p_dec:
            flips.append({
                "pair": item["desc"],
                "label": item["label"],
                "cpp_score": c_score,
                "py_score": p_score,
                "cpp_dec": c_dec,
                "py_dec": p_dec,
            })

    mean_diff = float(np.mean(diffs)) if diffs else 0.0
    mean_gen_diff = float(np.mean(gen_diffs)) if gen_diffs else 0.0
    mean_imp_diff = float(np.mean(imp_diffs)) if imp_diffs else 0.0

    print("\n" + "=" * 80)
    print(" PARITY RESULTS SUMMARY")
    print("=" * 80)
    print(f"Total Pairs Evaluated:    {len(all_pairs)}")
    print(f"  * Genuine Pairs:        {len(gen_diffs)}")
    print(f"  * Impostor Pairs:       {len(imp_diffs)}")
    print(f"Score Differences (|C++ - Python|):")
    print(f"  * Max |Δscore|:         {max_diff}")
    print(f"  * Mean |Δscore|:        {mean_diff:.4f}")
    print(f"  * Mean |Δscore| (Gen):  {mean_gen_diff:.4f}")
    print(f"  * Mean |Δscore| (Imp):  {mean_imp_diff:.4f}")
    print(f"Impostor Maximum Score:")
    print(f"  * C++ Max Impostor:     {imp_max_cpp} (Margin: {THRESHOLD - imp_max_cpp})")
    print(f"  * Python Max Impostor:  {imp_max_py} (Margin: {THRESHOLD - imp_max_py})")
    print(f"Decision Flips (Threshold = {THRESHOLD}): {len(flips)}")

    if flips:
        print("\nDecision Flips Detected:")
        print(f"{'Pair Description':<35} | {'Label':<8} | {'C++ Score':<9} | {'Py Score':<9} | {'C++ Dec':<7} | {'Py Dec':<7}")
        print("-" * 85)
        for f in flips:
            print(f"{f['pair']:<35} | {f['label']:<8} | {f['cpp_score']:<9} | {f['py_score']:<9} | {f['cpp_dec']:<7} | {f['py_dec']:<7}")
    else:
        print("[OK] ZERO decision flips across all pairs!")

    # Check Acceptance Criteria
    print("-" * 80)
    pass_parity = (len(flips) == 0 and max_diff <= 1)
    if pass_parity:
        print("[PASS] WP1 Acceptance Criteria Satisfied: max |Δscore| <= 1 and ZERO decision flips!")
    else:
        print(f"[FAIL] WP1 Acceptance Criteria Not Met: max |Δscore| = {max_diff}, decision flips = {len(flips)}")
        sys.exit(1)


if __name__ == "__main__":
    run_parity_test()
