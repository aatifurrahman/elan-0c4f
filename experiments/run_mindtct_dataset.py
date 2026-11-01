#!/usr/bin/env python3
"""
Evaluates NIST NBIS MINDTCT minutiae detector across all contact frames in the dataset
(86 touches across 3 fingers: right middle, right index, left index).
Measures minutiae yield both WITH perimeter removal (FPI_IMAGE_PARTIAL) and WITHOUT.
"""

import os
import glob
import tempfile
import subprocess
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data", "p01")
MEASURE_BIN = os.path.join(HERE, "measure_mindtct")

def main():
    touch_files = sorted(glob.glob(os.path.join(DATA_DIR, "*", "*", "touch_*.npz")))
    if not touch_files:
        print("No touch files found in", DATA_DIR)
        return

    print(f"Found {len(touch_files)} touch files in dataset.")

    temp_pgms = []
    with tempfile.TemporaryDirectory() as tmpdir:
        # Extract center contact frame for each touch and normalize 16-bit -> 8-bit
        for i, tf in enumerate(touch_files):
            d = np.load(tf)
            frames = d["frames"]
            state = d["state"]
            # Find contact frames (state == 2)
            contact_idx = np.where(state == 2)[0]
            if len(contact_idx) == 0:
                frame = frames[len(frames) // 2].astype(np.float32)
            else:
                frame = frames[contact_idx[len(contact_idx) // 2]].astype(np.float32)

            # Normalize to 8-bit matching elan_process_frame_linear in drivers/elan.c
            f_min = float(frame.min())
            f_max = float(frame.max())
            denom = f_max - f_min if f_max > f_min else 1.0
            frame_u8 = np.clip((frame - f_min) * 255.0 / denom, 0, 255).astype(np.uint8)

            pgm_path = os.path.join(tmpdir, f"frame_{i:03d}.pgm")
            # Write P5 binary PGM
            with open(pgm_path, "wb") as f:
                f.write(f"P5\n{frame_u8.shape[1]} {frame_u8.shape[0]}\n255\n".encode("ascii"))
                f.write(frame_u8.tobytes())
            temp_pgms.append((tf, pgm_path))

        # Batch execute measure_mindtct
        cmd = [MEASURE_BIN] + [p[1] for p in temp_pgms]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)

        lines = proc.stdout.strip().splitlines()
        with_perim_counts = []
        without_perim_counts = []

        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) == 3:
                with_perim_counts.append(int(parts[1]))
                without_perim_counts.append(int(parts[2]))

        wp = np.array(with_perim_counts)
        wop = np.array(without_perim_counts)

        print("=" * 65)
        print("NIST NBIS MINDTCT Minutiae Yield on 80x80 (4.0x4.0 mm) Sensor")
        print(f"Total Touches Evaluated: {len(wp)}")
        print("-" * 65)
        print("1. With Perimeter Removal (Standard FPI_IMAGE_PARTIAL):")
        print(f"   Min:     {wp.min()}")
        print(f"   p25:     {np.percentile(wp, 25):.1f}")
        print(f"   Median:  {np.median(wp):.1f}")
        print(f"   p75:     {np.percentile(wp, 75):.1f}")
        print(f"   Max:     {wp.max()}")
        print(f"   Mean:    {wp.mean():.2f} +/- {wp.std():.2f}")
        print(f"   Zeros:   {(wp == 0).sum()} / {len(wp)} ({(wp == 0).mean()*100:.1f}%)")
        print(f"   < 6 pts: {(wp < 6).sum()} / {len(wp)} ({(wp < 6).mean()*100:.1f}%)")
        print(f"   < 12 pts: {(wp < 12).sum()} / {len(wp)} ({(wp < 12).mean()*100:.1f}%)")
        print("-" * 65)
        print("2. Without Perimeter Removal (Raw Edge Minutiae Retained):")
        print(f"   Min:     {wop.min()}")
        print(f"   p25:     {np.percentile(wop, 25):.1f}")
        print(f"   Median:  {np.median(wop):.1f}")
        print(f"   p75:     {np.percentile(wop, 75):.1f}")
        print(f"   Max:     {wop.max()}")
        print(f"   Mean:    {wop.mean():.2f} +/- {wop.std():.2f}")
        print(f"   Zeros:   {(wop == 0).sum()} / {len(wop)} ({(wop == 0).mean()*100:.1f}%)")
        print(f"   < 6 pts: {(wop < 6).sum()} / {len(wop)} ({(wop < 6).mean()*100:.1f}%)")
        print(f"   < 12 pts: {(wop < 12).sum()} / {len(wop)} ({(wop < 12).mean()*100:.1f}%)")
        print("=" * 65)

if __name__ == "__main__":
    main()
