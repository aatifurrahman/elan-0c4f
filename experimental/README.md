# Experimental Patches for ELAN 04f3:0c4f

This directory contains upstream `libfprint` patches providing open-source driver support for the ELAN `04f3:0c4f` Match-on-Host capacitive fingerprint reader.

---

## Patches Summary

| Patch File | Target Upstream Base | Description |
|---|---|---|
| [`elan_0c4f_cumulative_master.patch`](elan_0c4f_cumulative_master.patch) | Stock upstream `master` (`6f9479c`) | **All-in-one patch**: Applies SIGFM infrastructure and all ELAN 0c4f driver fixes directly to pristine upstream master in a single patch. |
| [`elan_0c4f_mr530.patch`](elan_0c4f_mr530.patch) | **GitLab MR !530** (`bc986621`) | Modern rebased baseline: Applies our driver fixes onto Tooniis's rebased MR !530 branch. |
| [`elan_0c4f_sigfm_opensource.patch`](elan_0c4f_sigfm_opensource.patch) | **GitLab MR !418** (`bfb77a33`) | Legacy tested baseline: Applies our driver fixes onto Natasha England-Elbro's MR !418 branch. |
| [`elan_0c4f_opensource.patch`](elan_0c4f_opensource.patch) | Stock upstream `master` (`6f9479c`) | Historical reference: Initial attempt using standard NIST NBIS (fails due to small-die minutiae limits). |

---

## Reviewer Scope & Diff Overview

> [!NOTE]
> **Why 34 files are touched in the cumulative patch**:
> The cumulative patch modifies 34 files across `libfprint`. The vast majority of these changes are from generalizing the internal `bz3_threshold` driver property to `score_threshold` across existing drivers, allowing non-Bozorth matchers (such as SIGFM) to set their own score scale.
>
> **Core logic reviewers should inspect**:
> - `libfprint/drivers/elan.c`: ELAN `04f3:0c4f` detection, image frame extraction ($80 \times 80$), settle delay, and touch debounce.
> - `libfprint/sigfm/`: SIFT feature extraction, scale bounding ($[0.80, 1.25]$), spatial spread verification, and RANSAC matching.

---

## Analysis: Why Our Fixes Are Required (Even on MR !530)

GitLab MR !530 (*"add sigfm algorithm implementation (rebased and enabled Elan sensors)"*) was created by rebasing MR !418 onto master and adding a single 10-line commit (`bc98662: elan: switch to sigfm`) that sets `scan_type = FP_SCAN_TYPE_PRESS` and `algorithm = SIGFM`.

However, **MR !530 alone does not work for `04f3:0c4f`** due to five critical architectural gaps:

1. **Stationary Center Frame vs Swipe Stitching**:
   MR !530 still executes `fpi_do_movement_estimation` and `fpi_assemble_frames` in `elan_submit_image`. This attempts to calculate swipe displacement vectors on a stationary touch impression, generating artifacts or empty frames. Our fix directly extracts the stable Center Contact Frame (`len / 2`).
2. **Sensor Dimension Cropping & Rotation**:
   - `04f3:0c4f` is an $80 \times 80$ row-major sensor.
   - In MR !530, `04f3:0c4f` is not in `ELAN_NOT_ROTATED`, causing frames to be wrongly rotated 90 degrees.
   - `frame_height` is clipped to 50 rows (`ELAN_MAX_FRAME_HEIGHT = 50`), discarding 37.5% of the sensor area.
   - Our fix registers `ELAN_0C4F` in `ELAN_NOT_ROTATED` and preserves the full $80 \times 80$ die.
3. **Finger-Off Debounce (Enrollment Stage Burning)**:
   MR !530 lacks a touch debounce mechanism. On a press sensor, libfprint reports finger state every polling cycle, causing all 16 enrollment stages to complete within ~200 milliseconds during a single touch. Our fix introduces a software debounce timer (600 ms) in `stop_capture_complete`, requiring distinct touch-and-lift motions.
4. **Touch Settle Delay**:
   Reading image frames immediately upon `0x55` touch detection captures partial mid-landing contact. Our fix introduces a 200 ms settle delay in `CAPTURE_GET_IMAGE` before reading the frame, allowing the finger to fully flatten across the sensor die.
5. **Matcher Noise & Biological Scale Invariance**:
   - MR !530 feeds raw 16-bit ADC values directly into SIFT without processing. Sensor ADC horizontal banding creates false keypoints that match across *different* fingers.
   - MR !530 uses an unconstrained angle-combinatorics matching loop without affine RANSAC, allowing ridges from different fingers to match through artificial scaling.
   - Our fix adds row-median ADC destriping, Gaussian bandpass filtering, and an affine RANSAC matcher with **strict biological scale bounds ($0.80 \le s \le 1.25$)** and spatial spread verification ($\ge 25\text{px}$).
6. **Build Dependency**:
   MR !530 hardcoded `doctest = dependency('doctest', required: true)`, which breaks the build on distributions that do not ship `doctest.pc`. Our fix makes doctest optional.

---

## Background Calibration & Baseline Reuse Note

> [!IMPORTANT]
> **Calibration Baseline Reuse**:
> In `dev_change_state`, the driver reuses the clean air-calibration background (`self->background`) across touches during enrollment rather than recalibrating before each stage. This prevents a lingering finger from being captured as "background", which would invert and corrupt subsequent ridge subtraction.
>
> **Known Limitations**:
> - **Initial Calibration**: The initial calibration occurs when the sensor is opened / activated. If a finger is already resting on the sensor during device activation or system boot, the baseline will be corrupted until the device re-initializes.
> - **Thermal Drift**: Extreme temperature fluctuations over long operating sessions may cause minor sensor baseline drift. Normal wake/suspend and service restarts automatically trigger a fresh calibration.

---

## Building and Applying Patches

### Option 1: Pristine Master (Cumulative Patch — Recommended)

```bash
git clone https://gitlab.freedesktop.org/libfprint/libfprint.git
cd libfprint

# Apply cumulative patch to master
git apply /path/to/elan-0c4f/experimental/elan_0c4f_cumulative_master.patch

# Build
meson setup build -Ddrivers=elan -Dudev_rules=disabled -Dudev_hwdb=disabled -Dintrospection=false
ninja -C build
```

### Option 2: Using MR !530 Baseline

Parent commit: `bc986621b906546836cb008355c1e8d5cd88a0db` by Yassine Oudjana (GitLab MR !530).

```bash
git clone https://gitlab.freedesktop.org/libfprint/libfprint.git
cd libfprint

# Fetch and checkout MR !530
git fetch origin merge-requests/530/head:mr-530-sigfm
git checkout mr-530-sigfm

# Apply patch
git apply /path/to/elan-0c4f/experimental/elan_0c4f_mr530.patch

# Build
meson setup build -Ddrivers=elan -Dudev_rules=disabled -Dudev_hwdb=disabled -Dintrospection=false
ninja -C build
```

### Option 3: Using MR !418 Baseline

Parent commit: `bfb77a332632822196af95ea3763872d293ccd7a` by Natasha England-Elbro (GitLab MR !418).

```bash
git clone https://gitlab.freedesktop.org/libfprint/libfprint.git
cd libfprint

# Fetch and checkout MR !418
git fetch origin merge-requests/418/head:mr-418-sigfm
git checkout mr-418-sigfm

# Apply patch
git apply /path/to/elan-0c4f/experimental/elan_0c4f_sigfm_opensource.patch

# Build
meson setup build -Ddrivers=elan -Dudev_rules=disabled -Dudev_hwdb=disabled -Dintrospection=false
ninja -C build
```

---

## License

As derivative works of `libfprint` and respective Merge Request contributions, all patch files in this directory (`experimental/*.patch`) are licensed under the **GNU Lesser General Public License version 2.1 or later (LGPL-2.1+)**. See [`LICENSE.md`](LICENSE.md) for details.
