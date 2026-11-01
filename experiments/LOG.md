# ELAN 04f3:0c4f Open-Source Matching Experiment Log

All experiments for open-source driver development, image normalization, and matching benchmarks are logged chronologically here.

---

## Baseline Environment (Phase 0 Hygiene - 2026-11-01)

- **Date**: 2026-11-01
- **Hardware Platform**: Acer Aspire A715-51G laptop
- **Operating System / Distro**: Fedora Linux 44 (Workstation Edition, x86_64)
- **Kernel Version**: `7.2.13-200.fc44.x86_64`
- **fprintd Version**: `fprintd-1.94.5-5.fc44.x86_64` (PAM: `fprintd-pam-1.94.5-5.fc44.x86_64`)
- **Distro libfprint Version**: `libfprint-tod-1.94.10+tod1-1.fc44.x86_64` (COPR `grahamwhiteuk/libfprint-tod`)
- **Reference TOD Module**: `libfprint-2-tod1-elan.so` (extracted from Lenovo package `r1slf01w.zip`, patched for `0c4f`)
- **USB Device Descriptors (`lsusb -v -d 04f3:0c4f`)**:
  ```text
  Bus 003 Device 003: ID 04f3:0c4f Elan Microelectronics Corp. ELAN:Fingerprint
  Device Descriptor:
    bcdUSB               2.00
    bMaxPacketSize0        64
    idVendor           0x04f3 Elan Microelectronics Corp.
    idProduct          0x0c4f ELAN:Fingerprint
    bcdDevice            1.65
    iManufacturer           1 ELAN
    iProduct                2 ELAN:Fingerprint
    Endpoint Descriptors:
      0x81  EP 1 IN   (Bulk 64 bytes)
      0x01  EP 1 OUT  (Bulk 64 bytes)
      0x82  EP 2 IN   (Bulk 64 bytes - 16-bit raw ADC image stream)
      0x83  EP 3 IN   (Bulk 64 bytes - Status / touch events)
      0x03  EP 3 OUT  (Bulk 64 bytes)
  ```
- **Git Branch**: `lab/matcher-dev`
- **Hygiene Gate Status**: PASSED. `.gitignore` strictly excludes all biometric data (`*.pcap*`, `*.npz`, `*_frames/`, `*.pgm`, `*.variant`, `experiments/data/`). Zero biometric files tracked in git.
- **Evaluation Tooling**: Python 3.14, `numpy 2.4.6`, `opencv-python-headless 5.0.0.93`.

---

## Experiment 1: Dataset Pipeline & Automated Ingestion Setup (2026-11-01)

- **Date**: 2026-11-01
- **Objective**: Establish automated ingestion of raw USB packet captures (`pcap`) into standardized per-touch `touch_NN.npz` archives with `manifest.json` indexing.
- **Implementation**:
  - Created [`experiments/dataset.py`](file:///mnt/data/Projects/elan-0c4f/experiments/dataset.py): parses packet streams, slices touches, subtracts baseline calibration frames, and writes `manifest.json`.
  - Created [`experiments/trace.sh`](file:///mnt/data/Projects/elan-0c4f/experiments/trace.sh): orchestrates `tcpdump` on `usbmon`, executes enrollment/verification, and ingests captures.
  - Created [`experiments/eval_offline.py`](file:///mnt/data/Projects/elan-0c4f/experiments/eval_offline.py): multi-matcher harness (NCC, Phase Correlation Refined, SIFT/RANSAC) evaluating ROC and Zero-FA operating thresholds.
- **Outcome**: Successfully verified automated touch slicing and extraction. Ready for multi-finger collection.

---

## Experiment 2: Multi-Finger Dataset Collection & Offline Matcher Evaluation (2026-11-01)

- **Date**: 2026-11-01
- **Objective**: Evaluate whether Normalized Cross-Correlation (NCC), Phase Correlation (POC), or SIFT/RANSAC can separate genuine touches from impostor fingers on an $80 \times 80$ pixel (508 DPI) sensor.
- **Dataset Captured**:
  - Live session captures added via [`experiments/trace.sh`](file:///mnt/data/Projects/elan-0c4f/experiments/trace.sh):
    - `enroll_20261101_100911.pcap`: Right Index Finger (14 touches)
    - `enroll_20261101_100959.pcap`: Right Middle Finger (14 touches)
    - `enroll_20261101_101034.pcap`: Left Index Finger (15 touches)
    - `verify_20261101_101112.pcap`: Right Index Finger (1 probe touch)
    - `verify_20261101_101127.pcap`: Right Middle Finger (2 probe touches)
    - `verify_20261101_101141.pcap`: Left Index Finger (1 probe touch)
  - Dataset total: 86 touches across 3 finger classes (`p01:right-index-finger`, `p01:right-middle-finger`, `p01:left-index-finger`).
  - Analysis resolved initial trace misattributions: `enroll.pcapng` from Windows Hello was proven to be Right Middle Finger (median NCC 0.866 vs middle, max SIFT inliers 53).
- **Offline Benchmark Results**:
  - **NCC (Translation Search)**:
    - Genuine NCC: [0.33, 0.52, 0.69, 0.89, 0.94]
    - Impostor NCC: [0.27, 0.42, 0.63, 0.75, 0.80]
    - Zero-FA threshold: 0.81
    - Single-touch FRR: 76.0%, Three-try FRR: 43.9% (fails to separate sufficiently).
  - **SIFT/RANSAC Initial Baseline (Unconstrained Affine, 12px spread)**:
    - Cross-validation: 10 Gallery Touches vs 50 Probe Touches (50 Genuine, 100 Impostor Trials).
    - Genuine inliers: min 0, p50 16.5, max 65
    - Impostor inliers: min 0, p50 4.0, max 11
    - Zero-FA threshold: **11.1 inliers**
    - Single-touch FRR: **30.0%**, Three-try FRR: **2.70%**
  - **SIFT/RANSAC Parity Re-Run (2026-11-01 14:06, with Scale Bounds [0.80, 1.25] and 25px Spread)**:
    - Command: `python3 experiments/eval_offline.py`
    - Genuine probe scores: `[13.0, 16.3, 25.0, 28.8, 30.0]`
    - Impostor probe scores: `[0.0, 0.0, 0.0, 3.0, 3.0]`
    - Max impostor score dropped from 11 down to **3.0 inliers** due to elimination of warped affine matches.
- **Verdict**: Option A (SIFT/RANSAC) passed the Phase 2 Decision Gate offline.

---

## Experiment 3: Phase 3 Enrollment Design Analysis (2026-11-01)

- **Date**: 2026-11-01
- **Objective**: Characterize enrollment stage count $N$ vs FRR, frame selection rules, and diversity filtering.
- **Script**: [`experiments/phase3_enrollment_design.py`](file:///mnt/data/Projects/elan-0c4f/experiments/phase3_enrollment_design.py)
- **Findings (Re-evaluated with Exact Parity Matcher on 2026-11-01 14:08)**:
  - Command: `python3 experiments/phase3_enrollment_design.py`
  1. **Frame Selection Rule per Touch**:
     - Center Contact Frame (`state == 2` median index): **135.2 avg SIFT keypoints** (median: 138.5).
     - Phase-Aligned Averaged Frame: 129.8 avg keypoints.
     - Max Energy Frame: 124.4 avg keypoints.
     - *Selection*: Center Contact Frame avoids edge settling artifacts and lift-off smearing without subpixel softening.
  2. **Enrollment Stages $N$ vs FRR Curve (Threshold = 12 Inliers)**:
     - $N=4$:  Single-touch FRR 41.3%, 3-Try FRR 7.05% (median inliers: 13.0, max impostor: 4)
     - $N=8$:  Single-touch FRR 38.1%, 3-Try FRR 5.53% (median inliers: 15.5, max impostor: 4)
     - $N=12$: Single-touch FRR 31.6%, 3-Try FRR 3.15% (median inliers: 17.0, max impostor: 4)
     - $N=16$: Single-touch FRR **26.5%**, 3-Try FRR **1.85%** (median inliers: 19.5, max impostor: 4)
     - **Impostor Distribution**: Max impostor score across all cross-finger probe pairings is strictly **4 inliers** (down from 10 pre-parity).
     - **Separation Margin**: At the selected threshold of $12$ inliers, the separation margin to the highest offline impostor touch is **8 inliers** ($12 - 4$).
- **Verdict**: Selected $N = 16$ stages, Center Contact Frame extraction, and threshold $= 12$ inliers.

---

## Experiment 4: Phase 4 Live Evaluation & Upstream SIGFM Integration (2026-11-01)

- **Date**: 2026-11-01
- **Hardware**: Acer Aspire A715-51G (ELAN `04f3:0c4f`, 80x80 pixels, 508 DPI)
- **Sub-repository**: `experiments/libfprint-upstream` (branch `elan-0c4f-sigfm`, commit `61fa3e7`)
- **Key Implementation Details**:
  1. **`elan.c` / `elan.h`**:
     - Added `ELAN_0C4F` quirk to driver table.
     - Preserved raw frame dimensions: $80 \times 80$ (disabled swipe cropping).
     - Bound device as `FP_SCAN_TYPE_PRESS` with $16$ enrollment stages.
     - Extracted Center Contact Frame (`len / 2`) during multi-frame acquisition.
     - Added $900\text{ms}$ software finger-off debounce (`elan_0c4f_finger_off_cb`) to prevent stage burning on a single press.
  2. **`sigfm/sigfm.cpp` Enhancements**:
     - Row median subtraction (sensor ADC banding suppression).
     - Gaussian bandpass filtering ($\sigma_{\text{high}}=5.0$, $\sigma_{\text{low}}=0.8$).
     - Bicubic upsampling to $160 \times 160$.
     - OpenCV SIFT extraction with uncapped features (`nfeatures=0`, contrast threshold 0.01, edge threshold 20).
     - SIFT Lowe's ratio test ($0.80$), minimum match pairs ($3$).
     - Affine partial RANSAC with strict biological scale bounds ($0.80 \le s \le 1.25$) and spatial spread verification ($\ge 25\text{px}$ in both x and y).
     - Threshold: $12$ inliers for match decision.
- **Live Benchmark Protocol & Results (Recorded in `experiments/phase4_verify_results.csv`)**:
  - **Harness**: `experiments/phase4_live_eval.sh verify <finger> <type> <trials>`
  - **Enrollment**: Right Middle finger (Finger 7) enrolled with 16 distinct taps in ~21 seconds.
  - **Genuine Test Series (30 consecutive live trials, Finger 7)**:
    - Matches: 21 / 30 (70.0% single-touch match rate, 95% Wilson CI: [52.1%, 83.3%]; Single-Touch FRR: 30.0%).
    - Placement learning effect: Trials 1–18 had 9 matches (50.0%); trials 19–30 had 12 matches (100.0%) as user learned sensor center placement.
    - Empirical sliding 3-attempt window FRR: 1 / 28 failed windows (3.6%, 95% CI upper bound ~16%).
    - Inlier distribution (21 matches): [12, 14, 15, 15, 16, 17, 18, 20, 21, 22, 24, 24, 24, 25, 26, 28, 29, 30, 31, 32, 33], median of matches = 24.0 inliers (overall genuine median = 17.5 inliers; non-matches: 1 trial at 3 inliers, 8 trials at 0 inliers).
    - Zero scores: 8 of the 9 non-matching genuine touches produced 0 inliers (occurring when off-center contact yielded fewer than 3 features satisfying the ratio test or scale/spread constraints).
  - **Impostor Test Series (30 consecutive live trials, un-enrolled left-hand fingers)**:
    - Fingers used: Left thumb, index, middle, ring, little fingers (not enrolled in the gallery).
    - Matches: **0 / 30** (0.0% observed False Accept Rate in this 30-trial sample).
    - Statistical bound: By the Rule of Three, 0 false accepts in $N=30$ trials establishes a 95% confidence upper bound on FAR of $\le 10.0\%$ ($3/30$). Larger sample sizes ($N \approx 3000$) are required to statistically bound FAR to $\le 0.1\%$ ($1/1000$).
    - Inlier scores: all 30 impostor trials produced strictly **0 inliers** (threshold = 12), as no impostor feature pairs satisfied the affine scale bound ($0.80 \le s \le 1.25$) and $25\text{px}$ spread constraints.
- **Phase 4 Gate Verdict**: **PROVISIONAL PASS**. Operational functionality confirmed on hardware. Statistical FAR bound remains provisional pending multi-day / multi-subject testing.

---

## Experiment 5: Phase 5 System Integration (fprintd + PAM) (2026-11-01)

- **Date**: 2026-11-01
- **Platform**: Acer Aspire A715-51G on Fedora Linux 44 (SELinux Enforcing)
- **Integration Architecture**:
  - Installed open-source driver to `/usr/local/lib64/libfprint-2.so.2.0.0` with standard SELinux `lib_t` context.
  - `/usr/local/lib64` is prioritized in Fedora's `/etc/ld.so.conf.d/local.conf`, cleanly shadowing `/usr/lib64` without modifying package-managed files.
  - Zero-touch rollback: `./elan-0c4f.sh opensource-uninstall` restores stock or Lenovo TOD driver immediately.
- **Verification Outcomes**:
  1. `ldd /usr/libexec/fprintd` confirmed resolution to `/usr/local/lib64/libfprint-2.so.2`.
  2. `fprintd-enroll "$USER" -f right-middle-finger` completed 16 stages cleanly.
  3. `fprintd-verify "$USER" -f right-middle-finger` returned `verify-match (done)`.
  4. PAM authentication: `sudo -k && sudo true` prompted for fingerprint and succeeded via `pam_fprintd`.
  5. System audit confirmed: `op=PAM:authentication grantors=pam_fprintd acct="aatif" exe="/usr/bin/sudo" res=success`.
- **Security & Scoping Note**:
  - Fedora's default `authselect` profile with `with-fingerprint` enables `pam_fprintd.so` as `sufficient` in `/etc/pam.d/system-auth`, which applies globally to `sudo`, `gdm`, and `login`.
  - Because live testing ($N=30$) provides an empirical FAR bound of $\le 10\%$ (95% CI), fingerprint authentication for `sudo` can be scoped to password-only while keeping fingerprint lockscreen unlock:
    In `/etc/pam.d/sudo`, change line 2 from `auth include system-auth` to `auth include password-auth`.
    This decouples `sudo` (and `sudo-i`) from `pam_fprintd` while leaving desktop unlock (`gdm-fingerprint` -> `fingerprint-auth`) fully enabled.
- **Status**: **PROVISIONALLY DEPLOYED & OPERATIONAL**.

---

## Experiment 6: Dataset-Wide NIST NBIS MINDTCT Minutiae Yield Audit (2026-11-01)

- **Date**: 2026-11-01
- **Objective**: Empirically measure NIST NBIS `mindtct` minutiae yield across the entire 86-touch dataset on the 80x80 ($4.0 \times 4.0\text{ mm}$) sensor to prove why traditional minutiae matching fails.
- **Harness**: [`experiments/measure_mindtct.c`](file:///mnt/data/Projects/elan-0c4f/experiments/measure_mindtct.c) (linking directly against libfprint's `libnbis.a`) driven by [`experiments/run_mindtct_dataset.py`](file:///mnt/data/Projects/elan-0c4f/experiments/run_mindtct_dataset.py).
- **Test Protocol**:
  - Center contact frames extracted from all 86 dataset touches across 3 fingers (Right Middle, Right Index, Left Index).
  - 16-bit ADC values normalized to 8-bit matching `elan_process_frame_linear` in `drivers/elan.c`.
  - Evaluated with both `remove_perimeter_pts = TRUE` (standard libfprint `FPI_IMAGE_PARTIAL`) and `FALSE`.
- **Results across All 86 Touches**:
  1. **With Perimeter Removal (`FPI_IMAGE_PARTIAL`)**:
     - Min: **0 minutiae**, p25: **0.0**, Median: **1.0**, p75: **2.0**, Max: **4 minutiae**
     - Mean: $1.19 \pm 1.17$ minutiae
     - Zero minutiae detected: **30 / 86 touches (34.9%)**
     - Touches with $< 6$ minutiae: **86 / 86 touches (100.0%)**
  2. **Without Perimeter Removal (Raw Edge Points Retained)**:
     - Min: **0 minutiae**, p25: **0.0**, Median: **1.0**, p75: **2.0**, Max: **6 minutiae**
     - Mean: $1.57 \pm 1.41$ minutiae
     - Zero minutiae detected: **24 / 86 touches (27.9%)**
     - Touches with $< 6$ minutiae: **85 / 86 touches (98.8%)**
- **Conclusion**: NIST NBIS `bozorth3` requires 6–10 minutiae to construct constellation graphs. Because 100% of touches yield $< 6$ minutiae with perimeter removal (and 34.9% yield literally zero), traditional minutiae matching is mathematically and empirically incapable of supporting this sensor size.

---

## Experiment 7: Golden-Vector Parity Test (C++ vs Python Matcher) (2026-11-01)

- **Date**: 2026-11-01
- **Objective**: Verify mathematical and algorithmic decision parity between the C++ production matcher implementation (`sigfm_scorer.cpp` / `sigfm.cpp`) and the Python offline evaluation harness (`eval_offline.py` / `phase3_enrollment_design.py`).
- **Harness**: [`experiments/test_matcher_parity.py`](file:///mnt/data/Projects/elan-0c4f/experiments/test_matcher_parity.py).
- **Parameters Verified**:
  - Preprocessing: Row median subtraction + Gaussian bandpass ($\sigma=5.0, 0.8$) + bicubic $2\times$ upscaling.
  - SIFT: Uncapped `nfeatures=0`, contrast threshold 0.01, edge threshold 20.
  - Feature Pairing: Lowe's ratio test ($0.80 \times \text{distance}$).
  - Affine RANSAC: Inlier reprojection threshold 4.0 px, scale bounds $s \in [0.80, 1.25]$.
  - Spatial Spread: $\ge 25.0\text{px}$ spread in both x and y on $160 \times 160$ frame.
  - Match Decision: Threshold $= 12$ inliers.
- **Results**:
  - `enrolled.pgm` (Self Match): C++ = 165 inliers, Python = 162 inliers -> **MATCH / MATCH (Parity OK)**
  - `verify.pgm` (Self Match): C++ = 134 inliers, Python = 138 inliers -> **MATCH / MATCH (Parity OK)**
  - `enrolled.pgm` vs `verify.pgm` (Cross Match): C++ = 0 inliers, Python = 0 inliers -> **REJECT / REJECT (Parity OK)**
  - Genuine Touch RM 01 vs RM 01: C++ = 160 inliers, Python = 164 inliers -> **MATCH / MATCH (Parity OK)**
  - Genuine Touch RM 01 vs RM 02: C++ = 30 inliers, Python = 33 inliers -> **MATCH / MATCH (Parity OK)**
  - Genuine Touch RM 02 vs RM 03: C++ = 25 inliers, Python = 27 inliers -> **MATCH / MATCH (Parity OK)**
  - Impostor RM 01 vs LI 01: C++ = 0 inliers, Python = 0 inliers -> **REJECT / REJECT (Parity OK)**
  - Impostor RM 01 vs RI 01: C++ = 0 inliers, Python = 0 inliers -> **REJECT / REJECT (Parity OK)**
- **Verdict**: **100% Binary Decision Parity**. Minor variations in inlier counts are within expected bounds of OpenCV's random RANSAC sampling. Both engines produce identical MATCH/REJECT verdicts and identical zero scores for impostors.
