#!/usr/bin/env python3
"""
Evaluates NIST NBIS MINDTCT minutiae detector across image preprocessing variants:
1. Baseline (Driver-normalized 80x80 linear grayscale)
2. Destriped (Row median subtracted 80x80)
3. Destriped + Bandpassed (Row median + Gaussian bandpass sigma=(5.0, 0.8))
4. Upscaled 2x (Destriped + Bandpassed + Bicubic 2x to 160x160)
5. Baseline Upscaled 2x (Baseline + Bicubic 2x to 160x160)

Evaluates yield both with perimeter removal (FPI_IMAGE_PARTIAL) and without.
Compares counts against MIN_COMPUTABLE_BOZORTH_MINUTIAE (10 minutiae).
"""

import os
import glob
import tempfile
import subprocess
import numpy as np
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
DATA_DIR = os.path.join(REPO_ROOT, "experiments", "data", "p01")
MEASURE_BIN = os.path.join(REPO_ROOT, "experiments", "measure_mindtct")

MIN_COMPUTABLE_BOZORTH_MINUTIAE = 10

def get_center_contact_frame(touch_path):
    d = np.load(touch_path)
    frames = d["frames"]
    state = d["state"]
    contact_idx = np.where(state == 2)[0]
    if len(contact_idx) == 0:
        return frames[len(frames) // 2].astype(np.float32)
    return frames[contact_idx[len(contact_idx) // 2]].astype(np.float32)

def normalize_linear(frame):
    f_min = float(frame.min())
    f_max = float(frame.max())
    denom = f_max - f_min if f_max > f_min else 1.0
    return np.clip((frame - f_min) * 255.0 / denom, 0, 255).astype(np.uint8)

def destripe(img_u8):
    f = img_u8.astype(np.float32)
    k = f.shape[1] // 2
    f = f - np.partition(f, k, axis=1)[:, k:k+1]
    return cv2.normalize(f, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)

def bandpass(img_u8):
    f = img_u8.astype(np.float32)
    k = f.shape[1] // 2
    f = f - np.partition(f, k, axis=1)[:, k:k+1]
    f = f - cv2.GaussianBlur(f, (0, 0), 5.0)
    blur08 = cv2.GaussianBlur(f, (0, 0), 0.8)
    return cv2.normalize(blur08, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)

def write_pgm(path, img_u8):
    with open(path, "wb") as f:
        f.write(f"P5\n{img_u8.shape[1]} {img_u8.shape[0]}\n255\n".encode("ascii"))
        f.write(img_u8.tobytes())

def evaluate_variant(variant_name, touch_files, transform_fn, ppmm=20.0):
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_pgms = []
        for i, tf in enumerate(touch_files):
            raw_frame = get_center_contact_frame(tf)
            processed = transform_fn(raw_frame)
            pgm_path = os.path.join(tmpdir, f"frame_{i:03d}.pgm")
            write_pgm(pgm_path, processed)
            temp_pgms.append(pgm_path)

        env = os.environ.copy()
        env["NBIS_PPMM"] = str(ppmm)
        cmd = [MEASURE_BIN] + temp_pgms
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)

        lines = proc.stdout.strip().splitlines()
        with_perim = []
        without_perim = []
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) == 3:
                with_perim.append(int(parts[1]))
                without_perim.append(int(parts[2]))

        wp = np.array(with_perim)
        wop = np.array(without_perim)
        return wp, wop

def summarize_stats(arr, n_total):
    return {
        "min": int(arr.min()),
        "p25": float(np.percentile(arr, 25)),
        "median": float(np.median(arr)),
        "p75": float(np.percentile(arr, 75)),
        "max": int(arr.max()),
        "mean": float(arr.mean()),
        "std": float(arr.std()),
        "zeros": int((arr == 0).sum()),
        "zeros_pct": float((arr == 0).mean() * 100),
        "lt6": int((arr < 6).sum()),
        "lt6_pct": float((arr < 6).mean() * 100),
        "lt10": int((arr < MIN_COMPUTABLE_BOZORTH_MINUTIAE).sum()),
        "lt10_pct": float((arr < MIN_COMPUTABLE_BOZORTH_MINUTIAE).mean() * 100),
    }

def print_table(results):
    print("=" * 110)
    print("NBIS MINDTCT MINUTIAE YIELD ACROSS PREPROCESSING VARIANTS (N=86 touches)")
    print(f"Citing bozorth.h MIN_COMPUTABLE_BOZORTH_MINUTIAE = {MIN_COMPUTABLE_BOZORTH_MINUTIAE}")
    print("=" * 110)
    print(f"{'Variant':<28} | {'Perim':<7} | {'Median':<6} | {'Mean ± Std':<13} | {'Max':<4} | {'Zero %':<8} | {'<10 (<Min)':<10}")
    print("-" * 110)
    for name, wp, wop in results:
        swp = summarize_stats(wp, len(wp))
        swop = summarize_stats(wop, len(wop))
        print(f"{name:<28} | With    | {swp['median']:<6.1f} | {swp['mean']:.2f} ± {swp['std']:.2f} | {swp['max']:<4} | {swp['zeros_pct']:>5.1f}%  | {swp['lt10_pct']:>5.1f}% ({swp['lt10']}/{len(wp)})")
        print(f"{'':<28} | Without | {swop['median']:<6.1f} | {swop['mean']:.2f} ± {swop['std']:.2f} | {swop['max']:<4} | {swop['zeros_pct']:>5.1f}%  | {swop['lt10_pct']:>5.1f}% ({swop['lt10']}/{len(wop)})")
        print("-" * 110)

def main():
    touch_files = sorted(glob.glob(os.path.join(DATA_DIR, "*", "*", "touch_*.npz")))
    if not touch_files:
        print("No touch files found in", DATA_DIR)
        return

    variants = [
        ("1. Baseline (80x80 Linear)",
         lambda raw: normalize_linear(raw),
         20.0),
        ("2. Destriped (80x80)",
         lambda raw: destripe(normalize_linear(raw)),
         20.0),
        ("3. Destriped+Bandpass (80x80)",
         lambda raw: bandpass(normalize_linear(raw)),
         20.0),
        ("4. Upscaled 2x (160x160 BP @20ppmm)",
         lambda raw: cv2.resize(bandpass(normalize_linear(raw)), (160, 160), interpolation=cv2.INTER_CUBIC),
         20.0),
        ("5. Upscaled 2x (160x160 BP @40ppmm)",
         lambda raw: cv2.resize(bandpass(normalize_linear(raw)), (160, 160), interpolation=cv2.INTER_CUBIC),
         40.0),
        ("6. Upscaled 2x (160x160 Lin @20ppmm)",
         lambda raw: cv2.resize(normalize_linear(raw), (160, 160), interpolation=cv2.INTER_CUBIC),
         20.0),
    ]

    results = []
    for name, fn, ppmm in variants:
        wp, wop = evaluate_variant(name, touch_files, fn, ppmm=ppmm)
        results.append((name, wp, wop))

    print_table(results)

if __name__ == "__main__":
    main()
