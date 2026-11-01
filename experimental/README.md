# Experimental Patches for ELAN 04f3:0c4f

This directory contains upstream `libfprint` patches for the ELAN `04f3:0c4f` Match-on-Host capacitive fingerprint reader.

---

## Patches Summary

| Patch File | Target Upstream Base | Status | Description |
|---|---|---|---|
| [`elan_0c4f_sigfm_opensource.patch`](file:///mnt/data/Projects/elan-0c4f/experimental/elan_0c4f_sigfm_opensource.patch) | **MR !418** (`bfb77a33`) | **Primary Tested Branch** | Full open-source driver (0/30 live false accepts, 95% bound $\le 10\%$; 3.6% empirical 3-try window failure). |
| [`elan_0c4f_mr530.patch`](file:///mnt/data/Projects/elan-0c4f/experimental/elan_0c4f_mr530.patch) | **MR !530** (`bc986621`) | **Alternative / Newer MR** | Applies all our fixes onto Tooniis's newer rebased MR !530. |
| [`elan_0c4f_opensource.patch`](file:///mnt/data/Projects/elan-0c4f/experimental/elan_0c4f_opensource.patch) | Stock `master` (`6f9479c3`) | Historical Reference | Legacy attempt using NIST NBIS (fails on 80x80). |

---

## Analysis: Why Our Fixes Are Required (Even on MR !530)

MR !530 (*"add sigfm algorithm implementation (rebased and enabled Elan sensors)"*) was created by Tooniis by rebasing MR !418 onto master and adding a single 10-line commit (`bc98662: elan: switch to sigfm`) that sets `scan_type = FP_SCAN_TYPE_PRESS` and `algorithm = SIGFM`.

However, **MR !530 alone does not work for `04f3:0c4f`** due to five critical architectural gaps:

1. **Stationary Center Frame vs Swipe Stitching**:
   MR !530 still executes `fpi_do_movement_estimation` and `fpi_assemble_frames` in `elan_submit_image`. This attempts to calculate swipe displacement vectors on a stationary touch impression, generating artifacts or empty frames. Our fix directly extracts the stable Center Contact Frame (`len / 2`).
2. **Sensor Dimension Cropping & Rotation**:
   - `04f3:0c4f` is an $80 \times 80$ row-major sensor.
   - In MR !530, `04f3:0c4f` is not in `ELAN_NOT_ROTATED`, causing frames to be wrongly rotated 90 degrees.
   - `frame_height` is clipped to 50 rows (`ELAN_MAX_FRAME_HEIGHT = 50`), discarding 37.5% of the sensor area.
   - Our fix registers `ELAN_0C4F` in `ELAN_NOT_ROTATED` and preserves the full $80 \times 80$ die.
3. **Finger-Off Debounce (Enrollment Stage Burning)**:
   MR !530 lacks a touch debounce mechanism. On a press sensor, libfprint reports finger state every polling cycle, causing all 15 enrollment stages to complete within ~200 milliseconds during a single touch. Our fix introduces a $900\text{ms}$ software debounce (`elan_0c4f_finger_off_cb`), requiring distinct touch-and-lift motions.
4. **Matcher Noise & Biological Scale Invariance**:
   - MR !530 feeds raw 16-bit ADC values directly into SIFT without processing. Sensor ADC horizontal banding creates false keypoints that match across *different* fingers.
   - MR !530 uses an unconstrained angle-combinatorics matching loop without affine RANSAC, allowing ridges from different fingers to match through artificial scaling.
   - Our fix adds row-median ADC destriping, Gaussian bandpass filtering, and an affine RANSAC matcher with **strict biological scale bounds ($0.80 \le s \le 1.25$)** and spatial spread verification ($\ge 25\text{px}$), yielding **0 false accepts in live ($N=30$) and offline ($N=100$) evaluations** (Rule of Three 95% upper bound $\le 3\%$).
5. **Build Dependency**:
   MR !530 hardcoded `doctest = dependency('doctest', required: true)`, which breaks the build on distributions like Fedora that do not ship `doctest.pc`. Our fix makes doctest optional.

---

## 1. Using MR !418 (Primary Tested Baseline)

### Base Parent Commit
```
commit bfb77a332632822196af95ea3763872d293ccd7a (mr-418-sigfm)
Author: Natasha England-Elbro <natasha@natashaee.me>
Date:   Sun Mar 19 17:42:17 2023 +0000

    fix: sigfm header not installed
```

### Steps to Clone and Apply
```bash
git clone https://gitlab.freedesktop.org/libfprint/libfprint.git
cd libfprint

# Fetch MR !418
git fetch origin merge-requests/418/head:mr-418-sigfm
git checkout mr-418-sigfm

# Apply patch
git am < /path/to/elan-0c4f/experimental/elan_0c4f_sigfm_opensource.patch

# Build
meson setup build -Ddrivers=elan -Dsigfm=enabled -Dudev_rules=disabled -Dudev_hwdb=disabled
ninja -C build
```

---

## 2. Using MR !530 (Newer Rebased Baseline)

### Base Parent Commit
```
commit bc986621b906546836cb008355c1e8d5cd88a0db (mr-530-sigfm)
Author: Yassine Oudjana <y.oudjana@protonmail.com>
Date:   Thu Sep 14 19:49:39 2023 +0300

    elan: switch to sigfm
```

### Steps to Clone and Apply
```bash
git clone https://gitlab.freedesktop.org/libfprint/libfprint.git
cd libfprint

# Fetch MR !530
git fetch origin merge-requests/530/head:mr-530-sigfm
git checkout mr-530-sigfm

# Apply patch
git am < /path/to/elan-0c4f/experimental/elan_0c4f_mr530.patch

# Build
meson setup build -Ddrivers=elan -Dsigfm=enabled -Dudev_rules=disabled -Dudev_hwdb=disabled
ninja -C build
```

---

## System Installation (Both Variants)

```bash
# Copy library to dynamic linker override path
sudo mkdir -p /usr/local/lib64
sudo install -m 0755 build/libfprint/libfprint-2.so.2.0.0 /usr/local/lib64/libfprint-2.so.2.0.0
sudo ln -sf libfprint-2.so.2.0.0 /usr/local/lib64/libfprint-2.so.2
sudo ln -sf libfprint-2.so.2 /usr/local/lib64/libfprint-2.so

# SELinux and linker cache update
sudo restorecon -v /usr/local/lib64/libfprint-2.so*
sudo ldconfig
sudo systemctl restart fprintd.service

# Enroll and test
fprintd-delete "$USER"
fprintd-enroll "$USER" -f right-middle-finger
fprintd-verify "$USER" -f right-middle-finger
```
