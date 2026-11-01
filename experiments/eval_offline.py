#!/usr/bin/env python3
"""
Offline Evaluation Harness for ELAN 04f3:0c4f Matcher Development.
Implements Phase 2 of experiments/PLAN.md:
  - Multi-matcher comparison: NCC, Phase Correlation (POC) Refined, SIFT/RANSAC (SIGFM style).
  - Multi-frame averaging option for multi-frame touches.
  - Evaluation modes:
      1. Two raw.npz comparison:
         python3 eval_offline.py <session_A/raw.npz> <session_B/raw.npz>
      2. Full dataset evaluation:
         python3 eval_offline.py [--data-dir experiments/data] [--average-frames]
"""

import itertools
import json
import os
import sys
import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
MANIFEST_PATH = os.path.join(DATA_DIR, "manifest.json")

# ---------------------------------------------------------------- Image Preprocessing
def prep(f):
    """
    Standard preprocessing for 80x80 capacitive frames:
    1. Subtract row median to eliminate ELAN ADC line banding.
    2. Bandpass: Subtract Gaussian blur (sigma=5) to eliminate low-frequency shading/pressure gradient.
    3. Lowpass: Gaussian blur (sigma=0.8) to suppress single-pixel ADC noise.
    4. Normalize variance.
    """
    f = f.astype(np.float32)
    # Row-banding removal
    f = f - np.median(f, axis=1, keepdims=True)
    # Bandpass filter
    f = f - cv2.GaussianBlur(f, (0, 0), 5.0)
    f = cv2.GaussianBlur(f, (0, 0), 0.8)
    std = f.std()
    return (f / (std + 1e-6)).astype(np.float32)


def align_and_average(contact_frames):
    """
    Aligns consecutive contact frames from a single tap using phase correlation
    and returns the averaged composite frame.
    """
    if len(contact_frames) == 1:
        return contact_frames[0].astype(np.float32)

    ref = prep(contact_frames[0])
    aligned = [contact_frames[0].astype(np.float32)]
    h, w = ref.shape

    for frame in contact_frames[1:]:
        curr = prep(frame)
        (dx, dy), _ = cv2.phaseCorrelate(ref, curr)
        # Only align if shift is reasonable (within +/- 15 pixels)
        if abs(dx) < 15 and abs(dy) < 15:
            M = np.float32([[1, 0, dx], [0, 1, dy]])
            shifted = cv2.warpAffine(frame.astype(np.float32), M, (w, h), borderMode=cv2.BORDER_REFLECT)
            aligned.append(shifted)
        else:
            aligned.append(frame.astype(np.float32))

    return np.mean(aligned, axis=0)


# ---------------------------------------------------------------- Matchers
def match_ncc(a, b, window_size=44):
    """
    Translation-search Normalized Cross-Correlation (NCC).
    Extracts central window of template A and searches within B, and vice versa.
    """
    A, B = prep(a), prep(b)
    best = -1.0
    c = (80 - window_size) // 2

    for X, Y in ((A, B), (B, A)):
        crop = X[c : c + window_size, c : c + window_size]
        res = cv2.matchTemplate(Y, crop, cv2.TM_CCOEFF_NORMED)
        best = max(best, float(res.max()))

    return float(best)


_HANNING = cv2.createHanningWindow((80, 80), cv2.CV_32F)

def match_poc_refined(a, b):
    """
    Spectral Phase Correlation (POC) with Overlap NCC Refinement.
    Uses Phase Correlation to estimate translation (dx, dy), shifts A onto B,
    and computes NCC across the valid overlapping region.
    """
    A, B = prep(a), prep(b)
    (dx, dy), raw_peak = cv2.phaseCorrelate(A * _HANNING, B * _HANNING)

    if abs(dx) > 30 or abs(dy) > 30:
        return float(max(raw_peak, 0.0))

    # Shift A onto B
    M = np.float32([[1, 0, dx], [0, 1, dy]])
    A_shifted = cv2.warpAffine(A, M, (80, 80), borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    mask = cv2.warpAffine(np.ones((80, 80), np.float32), M, (80, 80), borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    overlap = mask > 0.9

    if overlap.sum() < 80 * 80 * 0.35:
        return float(max(raw_peak, 0.0))

    # Compute correlation on overlapping pixels
    A_vals = A_shifted[overlap]
    B_vals = B[overlap]
    std_prod = (A_vals.std() * B_vals.std()) + 1e-6
    corr = ((A_vals - A_vals.mean()) * (B_vals - B_vals.mean())).mean() / std_prod
    return float(max(corr, 0.0))


_SIFT = cv2.SIFT_create(contrastThreshold=0.01, edgeThreshold=20)
_BF = cv2.BFMatcher()

def _extract_sift(img):
    """Upscales 80x80 -> 160x160 for robust keypoint extraction on small sensors."""
    p = prep(img)
    norm = cv2.normalize(p, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    up = cv2.resize(norm, (160, 160), interpolation=cv2.INTER_CUBIC)
    return _SIFT.detectAndCompute(up, None)


def match_sift_ransac(a, b):
    """
    SIFT Keypoint Matching with Geometric RANSAC (SIGFM style).
    Filters matches with Lowe's ratio test (0.8), computes RANSAC partial affine
    model, and verifies spatial keypoint spread.
    """
    ka, da = _extract_sift(a)
    kb, db = _extract_sift(b)

    if da is None or db is None or len(ka) < 3 or len(kb) < 3:
        return 0

    matches = _BF.knnMatch(da, db, k=2)
    good = [m for m, n in matches if len((m, n)) == 2 and m.distance < 0.8 * n.distance]

    if len(good) < 3:
        return 0

    pts_a = np.float32([ka[m.queryIdx].pt for m in good])
    pts_b = np.float32([kb[m.trainIdx].pt for m in good])

    affine, inliers = cv2.estimateAffinePartial2D(pts_a, pts_b, method=cv2.RANSAC, ransacReprojThreshold=4.0)
    if affine is None or inliers is None:
        return 0

    # Biological fingerprint constraint: fixed 508 DPI sensor limits elasticity to ~20-25%
    a_param = affine[0, 0]
    b_param = affine[1, 0]
    scale = np.sqrt(a_param**2 + b_param**2)
    if scale < 0.80 or scale > 1.25:
        return 0

    num_inliers = int(inliers.sum())
    if num_inliers < 3:
        return 0

    # Minimum spread check: verify inlier keypoints span at least 25px in both x and y on 160x160
    inlier_pts = pts_a[inliers.ravel() == 1]
    span_x = inlier_pts[:, 0].max() - inlier_pts[:, 0].min()
    span_y = inlier_pts[:, 1].max() - inlier_pts[:, 1].min()

    if span_x < 25.0 or span_y < 25.0:
        return 0

    return num_inliers


# ---------------------------------------------------------------- Data Loaders
def load_taps_from_raw_npz(npz_path, average_frames=False):
    """Loads touches from an extract_frames raw.npz file."""
    d = np.load(npz_path)
    frames, baseline, tap, state = d["frames"], d["baseline"], d["tap"], d["state"]
    sub = np.clip(frames.astype(np.float32) - baseline.astype(np.float32), 0, None)
    out = []

    for k in sorted(set(tap[tap > 0])):
        idx = np.where((tap == k) & (state == 2))[0]
        if len(idx):
            if average_frames:
                out.append((k, align_and_average(sub[idx])))
            else:
                # Pick the center contact frame
                out.append((k, sub[idx[len(idx) // 2]]))
    return out


def load_dataset(data_dir=DATA_DIR, average_frames=False):
    """
    Loads dataset touches from experiments/data/manifest.json.
    Groups by class (person_id, finger) -> {enroll: [touch_imgs], probe: [touch_imgs]}.
    """
    manifest_file = os.path.join(data_dir, "manifest.json")
    if not os.path.isfile(manifest_file):
        raise FileNotFoundError(f"Manifest not found at {manifest_file}. Run dataset.py ingest first.")

    with open(manifest_file, "r") as f:
        manifest = json.load(f)

    classes = {}

    for entry in manifest.get("touches", []):
        if entry["contact_frames"] == 0:
            continue

        rel_path = entry["rel_path"]
        full_path = os.path.join(data_dir, rel_path)
        if not os.path.isfile(full_path):
            continue

        d = np.load(full_path)
        frames = d["frames"]
        state = d["state"]
        baseline = d["baseline"]
        sub = np.clip(frames.astype(np.float32) - baseline.astype(np.float32), 0, None)

        contact_idx = np.where(state == 2)[0]
        if len(contact_idx) == 0:
            continue

        if average_frames:
            touch_img = align_and_average(sub[contact_idx])
        else:
            touch_img = sub[contact_idx[len(contact_idx) // 2]]

        cls_key = f"{entry['person_id']}:{entry['finger']}"
        if cls_key not in classes:
            classes[cls_key] = {"enroll": [], "probe": []}

        purpose = entry.get("purpose", "probe")
        classes[cls_key][purpose].append({
            "img": touch_img,
            "session": entry.get("session", ""),
            "path": rel_path
        })

    return classes


# ---------------------------------------------------------------- Evaluation & Metrics
def evaluate_identification_trials(classes, match_fn):
    """
    Identification-style trial evaluation:
    Each probe touch is matched against gallery templates (best score over gallery).
    Genuine trial: probe vs its own class gallery.
    Impostor trial: probe vs all other classes' galleries.
    """
    genuine_scores = []
    impostor_scores = []

    class_names = sorted(classes.keys())

    for cls_name in class_names:
        own_enroll = classes[cls_name]["enroll"]
        own_probes = classes[cls_name]["probe"]

        # If a class has no explicit enroll touches, use its first touch as enroll gallery
        if not own_enroll and len(own_probes) > 1:
            own_enroll = own_probes[:1]
            own_probes = own_probes[1:]

        if not own_enroll:
            continue

        gallery_imgs = [item["img"] for item in own_enroll]

        # Genuine trials: probe vs own gallery
        for probe_item in own_probes:
            p_img = probe_item["img"]
            best_score = max(match_fn(p_img, g_img) for g_img in gallery_imgs)
            genuine_scores.append(best_score)

        # Impostor trials: probe vs every OTHER class's gallery
        other_galleries = [classes[o]["enroll"] for o in class_names if o != cls_name and classes[o]["enroll"]]
        for probe_item in own_probes:
            p_img = probe_item["img"]
            for o_gallery in other_galleries:
                best_impostor = max(match_fn(p_img, g_img) for g_img in (item["img"] for item in o_gallery))
                impostor_scores.append(best_impostor)

    return np.array(genuine_scores), np.array(impostor_scores)


def compute_roc(genuine, impostor, num_thresholds=200):
    """Computes FAR, FRR, and 3-try FRR across score thresholds."""
    if len(genuine) == 0 or len(impostor) == 0:
        return None

    all_scores = np.concatenate([genuine, impostor])
    thresholds = np.linspace(all_scores.min() - 1e-4, all_scores.max() + 1e-4, num_thresholds)

    far_list = []
    frr_list = []
    frr_3try_list = []

    for th in thresholds:
        far = (impostor >= th).mean()
        frr = (genuine < th).mean()
        far_list.append(far)
        frr_list.append(frr)
        frr_3try_list.append(frr ** 3)

    return {
        "thresholds": thresholds,
        "far": np.array(far_list),
        "frr": np.array(frr_list),
        "frr_3try": np.array(frr_3try_list)
    }


def run_dataset_benchmark(data_dir=DATA_DIR, average_frames=False):
    print("=" * 70)
    print(" ELAN 04f3:0c4f Matcher Evaluation Benchmark (Phase 2)")
    print(f" Dataset Path: {data_dir} (Frame Averaging: {average_frames})")
    print("=" * 70)

    classes = load_dataset(data_dir, average_frames=average_frames)
    total_enroll = sum(len(c["enroll"]) for c in classes.values())
    total_probe = sum(len(c["probe"]) for c in classes.values())

    print(f"Loaded {len(classes)} classes | {total_enroll} enroll templates | {total_probe} probe touches")
    for name, data in classes.items():
        print(f"  * {name:<30}: {len(data['enroll'])} enroll, {len(data['probe'])} probe")
    print("-" * 70)

    matchers = [
        ("NCC (Translation Search)", match_ncc),
        ("POC Refined (Phase Corr)", match_poc_refined),
        ("SIFT/RANSAC (SIGFM style)", match_sift_ransac),
    ]

    for name, fn in matchers:
        gen, imp = evaluate_identification_trials(classes, fn)
        print(f"\n>> Matcher: {name}")
        print(f"   Trials: {len(gen)} genuine, {len(imp)} impostor")

        if len(gen) == 0 or len(imp) == 0:
            print("   [!] Not enough probe/gallery pairs for trial evaluation.")
            continue

        pc = lambda v: np.percentile(v, [0, 10, 50, 90, 100]).round(3)
        print(f"   Genuine Scores  (min/p10/p50/p90/max): {pc(gen)}")
        print(f"   Impostor Scores (min/p10/p50/p90/max): {pc(imp)}")

        roc = compute_roc(gen, imp)
        if roc:
            # Zero False-Accept threshold
            zero_fa_idx = np.where(roc["far"] == 0)[0]
            if len(zero_fa_idx):
                best_idx = zero_fa_idx[0]
                th = roc["thresholds"][best_idx]
                frr = roc["frr"][best_idx]
                frr3 = roc["frr_3try"][best_idx]
                print(f"   Zero-FA Operating Point:")
                print(f"     Threshold:         {th:.3f}")
                print(f"     Single-Touch FRR:  {frr*100:.1f}%")
                print(f"     Three-Try FRR:     {frr3*100:.2f}%")
            else:
                print(f"   [!] Impostor scores overlap maximum genuine scores (No Zero-FA threshold).")

        # Statistical bound
        far_bound = 3.0 / len(imp)
        print(f"   Impostor Trials FAR Bound (Rule of Three): < {far_bound:.4f} ({far_bound*100:.2f}%)")

    print("\n" + "=" * 70)


def run_legacy_comparison(path_a, path_b):
    print("=" * 70)
    print(f" ELAN 04f3:0c4f Two-Session Comparison\n A: {path_a}\n B: {path_b}")
    print("=" * 70)

    W = load_taps_from_raw_npz(path_a)
    L = load_taps_from_raw_npz(path_b)
    print(f"Taps with contact frame: A: {len(W)}, B: {len(L)}")

    gw = [(a[1], b[1]) for a, b in itertools.combinations(W, 2)]
    gl = [(a[1], b[1]) for a, b in itertools.combinations(L, 2)]
    x = [(a[1], b[1]) for a in W for b in L]

    def auc(p, n):
        p, n = np.array(p), np.array(n)
        return ((p[:, None] > n[None, :]).mean() + 0.5 * (p[:, None] == n[None, :]).mean())

    pc = lambda v: np.percentile(v, [10, 50, 90]).round(2)

    for nm, fn in (("NCC", match_ncc), ("POC Refined", match_poc_refined), ("SIFT inliers", match_sift_ransac)):
        G1 = [fn(*p) for p in gw]
        G2 = [fn(*p) for p in gl]
        X = [fn(*p) for p in x]
        print(f"{nm:18s} A-A {pc(G1)}  B-B {pc(G2)}  Cross {pc(X)} | AUC A-A vs Cross {auc(G1, X):.2f}, B-B vs Cross {auc(G2, X):.2f}")

    print("\n-- Best-of-N Gallery Matching (Max score against gallery) --")
    def bestof(probes, gallery, fn, same):
        out = []
        for i, p in enumerate(probes):
            sc = [fn(p[1], g[1]) for j, g in enumerate(gallery) if not (same and i == j)]
            out.append(max(sc) if sc else 0)
        return out

    for nm, fn in (("NCC", match_ncc), ("POC Refined", match_poc_refined), ("SIFT inliers", match_sift_ransac)):
        a = bestof(W, W, fn, True)
        b = bestof(L, L, fn, True)
        c = bestof(L, W, fn, False)
        d = bestof(W, L, fn, False)
        pc_b = lambda v: np.percentile(v, [0, 10, 50]).round(2)
        print(f"{nm:18s} A probes vs A gallery {pc_b(a)} | B vs B {pc_b(b)} | B vs A {pc_b(c)} | A vs B {pc_b(d)}")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and os.path.isfile(sys.argv[1]) and os.path.isfile(sys.argv[2]):
        run_legacy_comparison(sys.argv[1], sys.argv[2])
    else:
        avg = "--average-frames" in sys.argv
        data_path = DATA_DIR
        for i, arg in enumerate(sys.argv):
            if arg == "--data-dir" and i + 1 < len(sys.argv):
                data_path = sys.argv[i + 1]
        run_dataset_benchmark(data_path, average_frames=avg)
