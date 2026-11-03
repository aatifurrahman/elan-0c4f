#!/usr/bin/env python3
"""
WP2: Front-End Equivalence Comparator.
Numerically compares the image emitted by the libfprint driver against
the raw ADC frames extracted from the simultaneous USB packet trace.

Strictly complies with Rule 2:
  - Zero image display, ASCII art, or raw pixel dumping.
  - Reports aggregate statistics only (pixel diff counts, max diff, MSE, hashes).
"""

import os
import sys
import struct
import hashlib
import numpy as np

# Setup import path for .venv_pkgs
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
_vpkgs = os.path.join(ROOT, ".venv_pkgs")
if os.path.isdir(_vpkgs) and _vpkgs not in sys.path:
    sys.path.insert(0, _vpkgs)

import cv2
from extract_frames import read_frames

W = H = 80


def read_pgm(pgm_path):
    """Reads standard PGM into a numpy uint8 array."""
    img = cv2.imread(pgm_path, cv2.IMREAD_GRAYSCALE)
    if img is not None:
        return img

    with open(pgm_path, "rb") as f:
        content = f.read()
    tokens = content.split()
    if tokens[0] != b"P5":
        raise ValueError(f"Invalid PGM header in {pgm_path}")
    w, h = int(tokens[1]), int(tokens[2])
    header_end = content.find(tokens[3]) + len(tokens[3])
    while content[header_end:header_end + 1] in b" \t\r\n":
        header_end += 1
    data = content[header_end:header_end + w * h]
    return np.frombuffer(data, dtype=np.uint8).reshape((h, w))


def simulate_driver_linear_norm(raw_frame):
    """
    Implements elan_process_frame_linear from drivers/elan.c exactly:
      unsigned short min = 0xffff, max = 0;
      ...
      px = (raw_frame[i] - min) * 0xff / (max - min);
      frame->data[i] = (unsigned char) px;
    """
    min_val = int(raw_frame.min())
    max_val = int(raw_frame.max())
    if max_val == min_val:
        return np.zeros((H, W), dtype=np.uint8)

    # Integer arithmetic matching C: (px - min) * 255 / (max - min)
    scaled = (raw_frame.astype(np.int64) - min_val) * 255 // (max_val - min_val)
    return np.clip(scaled, 0, 255).astype(np.uint8)


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <capture.pcap> <driver_output.pgm>")
        sys.exit(1)

    pcap_path = sys.argv[1]
    driver_pgm_path = sys.argv[2]

    if not os.path.isfile(pcap_path):
        print(f"Error: PCAP file not found: {pcap_path}")
        sys.exit(1)
    if not os.path.isfile(driver_pgm_path):
        print(f"Error: Driver PGM file not found: {driver_pgm_path}")
        sys.exit(1)

    print("=" * 80)
    print(" WP2: Front-End Equivalence Analysis")
    print(f" PCAP Trace:   {pcap_path}")
    print(f" Driver Image: {driver_pgm_path}")
    print("=" * 80)

    driver_img = read_pgm(driver_pgm_path)
    driver_hash = hashlib.sha256(driver_img.tobytes()).hexdigest()
    print(f"Driver Image Dimensions: {driver_img.shape[1]}x{driver_img.shape[0]}")
    print(f"Driver Image SHA256:     {driver_hash}")

    res = read_frames(pcap_path)
    if res is None:
        print("Error: No 12,800-byte frames found in PCAP trace.")
        sys.exit(1)

    frames, tap_ids, timestamps, pkts = res
    print(f"Total USB Raw Frames in Trace: {len(frames)}")

    # Classify calibration vs contact frames
    calib_mask = (tap_ids == 0)
    contact_mask = (tap_ids > 0)

    calib_indices = np.where(calib_mask)[0]
    contact_indices = np.where(contact_mask)[0]

    print(f"Calibration Frames: {len(calib_indices)} (packets: {pkts[calib_indices].tolist()})")
    print(f"Contact Frames:     {len(contact_indices)} (packets: {pkts[contact_indices].tolist()})")

    if len(calib_indices) > 0:
        # Driver stores the latest background frame from calibration
        bg_idx = calib_indices[-1]
        baseline = frames[bg_idx]
        print(f"Active Calibration Baseline: Frame {bg_idx} (packet {pkts[bg_idx]})")
    else:
        # Fallback if calibration frames not in trace (e.g. partial capture)
        print("Notice: No pre-touch calibration frames; assuming zero baseline.")
        baseline = np.zeros((H, W), dtype=np.uint16)

    # In elan.c:
    # 1. elan_save_img_frame: frame[i] = max(0, frame[i] - background[i])
    # 2. elan_submit_image: g_slist_foreach reverses prepended raw_frames back to chronological order.
    # 3. g_slist_nth_data(frames, len / 2): picks chronological index len // 2 of contact frames.
    K = len(contact_indices)
    if K == 0:
        print("Error: No contact frames found in trace.")
        sys.exit(1)

    theoretical_k = K // 2
    theoretical_frame_idx = contact_indices[theoretical_k]
    print(f"Theoretical Driver Selection: Contact Frame {theoretical_k} of {K} (Overall Frame {theoretical_frame_idx}, Packet {pkts[theoretical_frame_idx]})")

    print("\nFrame-by-Frame Comparison against Driver Output:")
    print(f"{'Contact#':<9} | {'Pkt':<6} | {'Max |Δpx|':<10} | {'Mean |Δpx|':<11} | {'Diff Pixels':<12} | {'Hash Match':<10}")
    print("-" * 75)

    best_k = -1
    best_max_diff = 999999
    best_mean_diff = 999999.0
    best_diff_count = 999999
    best_sim_hash = ""

    for k, idx in enumerate(contact_indices):
        raw = frames[idx]
        sub = np.maximum(0, raw.astype(np.int32) - baseline.astype(np.int32)).astype(np.uint16)
        sim_norm = simulate_driver_linear_norm(sub)

        diff = np.abs(driver_img.astype(np.int32) - sim_norm.astype(np.int32))
        max_d = int(diff.max())
        mean_d = float(diff.mean())
        diff_cnt = int(np.count_nonzero(diff))
        sim_hash = hashlib.sha256(sim_norm.tobytes()).hexdigest()
        hash_match = "EXACT" if sim_hash == driver_hash else "No"

        marker = " <-- driver pick" if k == theoretical_k else ""
        print(f"{k:<9} | {pkts[idx]:<6} | {max_d:<10} | {mean_d:<11.4f} | {diff_cnt:<12} | {hash_match:<10}{marker}")

        if max_d < best_max_diff or (max_d == best_max_diff and mean_d < best_mean_diff):
            best_max_diff = max_d
            best_mean_diff = mean_d
            best_diff_count = diff_cnt
            best_k = k
            best_sim_hash = sim_hash

    print("-" * 75)
    print(f"\nBest Matching Contact Frame: Contact {best_k} (Packet {pkts[contact_indices[best_k]]})")
    selection_confirmed = (best_k == theoretical_k)
    print(f"Selection Theory Confirmed:  {'YES' if selection_confirmed else 'NO'}")

    print(f"\nDiscrepancy Metrics on Selected Frame:")
    print(f"  * Max Absolute Pixel Difference: {best_max_diff} grey level(s)")
    print(f"  * Mean Absolute Pixel Difference: {best_mean_diff:.4f}")
    print(f"  * Differing Pixels (out of 6400): {best_diff_count} ({best_diff_count * 100.0 / 6400:.2f}%)")
    print(f"  * SHA256 Match:                  {'EXACT' if best_sim_hash == driver_hash else 'DIFFERENT'}")

    print("\n" + "=" * 80)
    if best_max_diff <= 1:
        print("[PASS] WP2 Acceptance Criteria Satisfied: max difference <= 1 grey level!")
        print(f"Driver selects chronological contact frame {best_k} of {K} (packet {pkts[contact_indices[best_k]]}).")
        print("Transform confirmed: Background-subtracted linear normalization (elan_process_frame_linear).")
    else:
        print(f"[FAIL] WP2 Acceptance Criteria Not Met: max difference = {best_max_diff} > 1")
        sys.exit(1)
    print("=" * 80)


if __name__ == "__main__":
    main()
