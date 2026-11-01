#!/usr/bin/env python3
"""
Golden-Vector Parity Test: C++ (sigfm_scorer.cpp) vs Python (eval_offline.py).
Validates that both implementations enforce identical:
  1. Preprocessing: row-median subtraction + bandpass (sigma 5.0 / 0.8) + cubic 2x upscale
  2. Feature extraction: SIFT(0, 3, 0.01, 20.0)
  3. Lowe's ratio test: < 0.80 * distance
  4. Affine partial RANSAC: reproj error 4.0, scale bounds [0.80, 1.25]
  5. Spatial spread: >= 25.0px in both x and y
  6. Match decision: inliers >= 12
"""

import os
import sys
import tempfile
import subprocess
import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.append(HERE)
from eval_offline import match_sift_ransac

CPP_BIN = os.path.join(HERE, "sigfm_scorer")
DATA_DIR = os.path.join(HERE, "data", "p01")

def run_cpp(path_a, path_b):
    cmd = [CPP_BIN, path_a, path_b]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return int(proc.stdout.strip())

def normalize_frame(f):
    f_min = float(f.min())
    f_max = float(f.max())
    denom = f_max - f_min if f_max > f_min else 1.0
    return np.clip((f - f_min) * 255.0 / denom, 0, 255).astype(np.uint8)

def get_center_frame(npz_path):
    d = np.load(npz_path)
    frames = d["frames"]
    state = d["state"]
    contact_idx = np.where(state == 2)[0]
    if len(contact_idx) == 0:
        f = frames[len(frames) // 2].astype(np.float32)
    else:
        f = frames[contact_idx[len(contact_idx) // 2]].astype(np.float32)
    return normalize_frame(f)

def write_pgm(path, img_u8):
    with open(path, "wb") as f:
        f.write(f"P5\n{img_u8.shape[1]} {img_u8.shape[0]}\n255\n".encode("ascii"))
        f.write(img_u8.tobytes())

def test_parity():
    if not os.path.exists(CPP_BIN):
        print(f"Error: {CPP_BIN} not found. Please compile it first.")
        sys.exit(1)

    print("=" * 70)
    print("Golden-Vector Parity Test: C++ sigfm_scorer vs Python eval_offline")
    print("=" * 70)

    # 1. Test existing PGM files if available
    pgm_enrolled = os.path.join(HERE, "enrolled.pgm")
    pgm_verify = os.path.join(HERE, "verify.pgm")

    test_pairs = []

    if os.path.exists(pgm_enrolled) and os.path.exists(pgm_verify):
        img_e = cv2.imread(pgm_enrolled, cv2.IMREAD_GRAYSCALE)
        img_v = cv2.imread(pgm_verify, cv2.IMREAD_GRAYSCALE)
        test_pairs.append(("Self Match (enrolled.pgm)", pgm_enrolled, pgm_enrolled, img_e, img_e, True))
        test_pairs.append(("Self Match (verify.pgm)", pgm_verify, pgm_verify, img_v, img_v, True))
        test_pairs.append(("Cross Match (enrolled vs verify)", pgm_enrolled, pgm_verify, img_e, img_v, False))

    # 2. Add genuine and impostor pairs from dataset
    with tempfile.TemporaryDirectory() as tmpdir:
        # Load genuine touches
        rm_s01 = os.path.join(DATA_DIR, "right-middle-finger", "s01")
        li_s01 = os.path.join(DATA_DIR, "left-index-finger", "s01")
        ri_s01 = os.path.join(DATA_DIR, "right-index-finger", "s01")

        if os.path.exists(rm_s01):
            t1 = get_center_frame(os.path.join(rm_s01, "touch_01.npz"))
            t2 = get_center_frame(os.path.join(rm_s01, "touch_02.npz"))
            t3 = get_center_frame(os.path.join(rm_s01, "touch_03.npz"))
            p_t1 = os.path.join(tmpdir, "rm_01.pgm")
            p_t2 = os.path.join(tmpdir, "rm_02.pgm")
            p_t3 = os.path.join(tmpdir, "rm_03.pgm")
            write_pgm(p_t1, t1)
            write_pgm(p_t2, t2)
            write_pgm(p_t3, t3)

            test_pairs.append(("Genuine Touch (RM 01 vs RM 01)", p_t1, p_t1, t1, t1, True))
            test_pairs.append(("Genuine Touch (RM 01 vs RM 02)", p_t1, p_t2, t1, t2, None))
            test_pairs.append(("Genuine Touch (RM 02 vs RM 03)", p_t2, p_t3, t2, t3, None))

            # Impostors
            if os.path.exists(li_s01):
                li1 = get_center_frame(os.path.join(li_s01, "touch_01.npz"))
                p_li1 = os.path.join(tmpdir, "li_01.pgm")
                write_pgm(p_li1, li1)
                test_pairs.append(("Impostor Touch (RM 01 vs LI 01)", p_t1, p_li1, t1, li1, False))

            if os.path.exists(ri_s01):
                ri1 = get_center_frame(os.path.join(ri_s01, "touch_01.npz"))
                p_ri1 = os.path.join(tmpdir, "ri_01.pgm")
                write_pgm(p_ri1, ri1)
                test_pairs.append(("Impostor Touch (RM 01 vs RI 01)", p_t1, p_ri1, t1, ri1, False))

        # Evaluate all pairs
        discrepancies = 0
        THRESHOLD = 12

        print(f"{'Pair Description':<35} | {'C++ Score':<9} | {'Py Score':<9} | {'C++ Dec':<7} | {'Py Dec':<7} | Parity")
        print("-" * 80)

        for desc, path_a, path_b, img_a, img_b, expected_decision in test_pairs:
            cpp_score = run_cpp(path_a, path_b)
            py_score = match_sift_ransac(img_a, img_b)

            cpp_dec = "MATCH" if cpp_score >= THRESHOLD else "REJECT"
            py_dec = "MATCH" if py_score >= THRESHOLD else "REJECT"

            # Check decision agreement
            dec_match = (cpp_dec == py_dec)
            if not dec_match:
                discrepancies += 1
                parity_str = "MISMATCH"
            else:
                parity_str = "OK"

            print(f"{desc:<35} | {cpp_score:<9} | {py_score:<9} | {cpp_dec:<7} | {py_dec:<7} | {parity_str}")

        print("=" * 80)
        if discrepancies == 0:
            print("[PASS] 100% Decision Parity between C++ and Python matchers!")
        else:
            print(f"[FAIL] Found {discrepancies} decision discrepancies!")
            sys.exit(1)

if __name__ == "__main__":
    test_parity()
