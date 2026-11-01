# ELAN 04f3:0c4f Fingerprint Reader on Linux

Complete Linux support for the ELAN `04f3:0c4f` Match-on-Host (MoH) fingerprint sensor (tested and verified on the **Acer Aspire A715-51G**), offering two driver options:
1. **Open-Source Driver (Primary)**: Upstream `libfprint` combined with unmerged GitLab Merge Request !418 (SIGFM SIFT/RANSAC matcher) and our local sensor driver patch series in `experimental/` – 100% open-source, zero proprietary binary blobs, with 0 false accepts observed in initial benchmarks ($N=30$, Rule of Three 95% upper bound $\le 10\%$).
2. **Vendor TOD Driver (Instant Fallback)**: Patched proprietary Match-on-Host shim (`libfprint-2-tod1-elan.so`) derived from Lenovo package `r1slf01w.zip`.

---

## 1. Open-Source Driver (Primary)

The open-source driver is not yet merged into upstream `libfprint`. It is built by taking upstream `libfprint` master, incorporating Natasha England-Elbro's unmerged GitLab Merge Request !418 (SIGFM SIFT/RANSAC matcher infrastructure), and applying our local patch series (`experimental/elan_0c4f_sigfm_opensource.patch`). The patch introduces `04f3:0c4f` USB ID support to `drivers/elan.c`, $80 \times 80$ sensor geometry, center-frame selection, row-banding/bandpass filtering, biological scale bounds ($[0.80, 1.25]$), 25 px spatial spread constraints, and a 900 ms finger-off debounce. It installs into `/usr/local/lib64` (Fedora/Arch) or `/usr/local/lib/<multiarch>` (Debian/Ubuntu), which shadows the distro library without modifying package-managed files.

### Build & Runtime Requirements

#### Dependency Installation by Distribution

##### Fedora (RPM)
- **Open-Source Driver (Build & Runtime)**:
  ```bash
  sudo dnf install -y meson ninja-build gcc gcc-c++ pkgconf-pkg-config git \
      glib2-devel libgusb-devel opencv-devel
  ```
  *(Empirically verified in clean Fedora 44 container and on host)*
- **Vendor TOD Driver**:
  ```bash
  sudo dnf install -y dnf-plugins-core
  sudo dnf copr enable grahamwhiteuk/libfprint-tod
  sudo dnf swap libfprint libfprint-tod
  ```

##### Debian / Ubuntu 24.04 LTS (DEB)
- **Open-Source Driver (Build & Runtime)**:
  ```bash
  sudo apt install -y meson ninja-build build-essential pkg-config git \
      libglib2.0-dev libgusb-dev libopencv-dev
  ```
  *(Empirically verified in clean Ubuntu 24.04 container via full compilation)*
- **Vendor TOD Driver**:
  ```bash
  sudo apt install -y libfprint-2-tod1
  ```

##### Arch Linux
- **Open-Source Driver (Build & Runtime)**:
  ```bash
  sudo pacman -S --needed meson ninja gcc pkgconf git \
      glib2 libgusb opencv
  ```
  *(Package availability verified via pacman sync queries in Arch core/extra repositories; container build not executed)*
- **Vendor TOD Driver**:
  ```bash
  yay -S libfprint-tod-git  # Replaces libfprint
  ```

#### Minimum Versions & Toolchain Requirements
| Component | Minimum Version | Source / Rationale |
|---|---|---|
| **Meson** | `>= 0.56.0` | Specified in `meson.build` (`meson_version: '>= 0.56.0'`) for the pinned MR !418 checkout (libfprint 1.94.6). Note that newer upstream releases like 1.94.9 bump this to `>= 0.59.0`. |
| **C++ Standard** | `C++17` | Required by SIGFM matcher (`cpp_std=c++17` in `meson.build`, GCC $\ge 7$ or Clang $\ge 5$). |
| **OpenCV** | `>= 4.4.0` | SIFT moved from `opencv_contrib` nonfree module into main `opencv_features2d` in OpenCV 4.4.0 following patent expiration (March 2020). Standard distro packages without patent flags work out of the box. |
| **GObject Introspection** | *Disabled* | Built with `-Dintrospection=false`, eliminating any build dependency on `gobject-introspection-1.0` / `libgirepository1.0-dev`. |
| **doctest** | *Optional* | Declared with `required: false` in our SIGFM patch. Only required if building unit tests (`sigfm-tests`); not required to build or run the driver. |

#### Runtime Dependency & Driver Scoping Notes
- **Dynamic Linking to OpenCV**: The compiled `libfprint-2.so.2` dynamically links against OpenCV libraries (`libopencv_core`, `libopencv_features2d`, `libopencv_calib3d`, `libopencv_imgproc`, `libopencv_flann`). OpenCV runtime packages must remain installed; removing them causes `fprintd` to fail at runtime with unresolved shared library errors.
- **Single-Driver Scoping (`-Ddrivers=elan`)**: The build flags intentionally compile only the `elan` driver. If the resulting `/usr/local/lib64` (or `/usr/local/lib/<multiarch>`) library shadows the distro library, other fingerprint reader models attached to the system will not be initialized. Reverting via `./elan-0c4f.sh opensource-uninstall` restores distro multi-device support.
- **Installation Paths & Linker Fallback**: Installs into `/usr/local/lib64` on Fedora/Arch and `/usr/local/lib/<multiarch>` (e.g. `/usr/local/lib/x86_64-linux-gnu`) on Debian/Ubuntu. If `/usr/local` is not prioritized by default in the system dynamic linker search path, `elan-0c4f.sh` automatically writes `/etc/ld.so.conf.d/00-elan-0c4f.conf` to guarantee precedence.
- **Source & Revision Overrides**: Upstream repository URL and target commit ref can be customized before building via environment variables. `LIBFPRINT_MR418_REV` pins commit `bfb77a332632822196af95ea3763872d293ccd7a` (Natasha England-Elbro's tip commit on MR !418):
  ```bash
  export LIBFPRINT_URL="https://gitlab.freedesktop.org/libfprint/libfprint.git"
  export LIBFPRINT_MR418_REV="bfb77a332632822196af95ea3763872d293ccd7a"
  ./elan-0c4f.sh opensource-build
  ```
- **Preflight Verification**: Run `./elan-0c4f.sh deps` to test whether all required binaries and pkg-config modules are present before building.

#### Reproducing the Research
To run the analysis scripts under `experiments/`:
- **Python Environment**: Python 3 with `numpy` and `opencv-python` (`pip install numpy opencv-python`) for offline evaluations (`eval_offline.py`, `phase3_enrollment_design.py`, `test_matcher_parity.py`, `dataset.py`, `extract_frames.py`).
- **USB Tracing**: Linux kernel module `usbmon` with Wireshark/`tshark` or `tcpdump` (see `experiments/PROTOCOL.md`), or Windows USBPcap (see `experiments/WINDOWS_TRACING.md`).
- **C/C++ Minutiae & Scorer Tools**: `gcc`, `g++`, OpenCV development libraries, and NIST NBIS (`libnbis.a` built from `experiments/libfprint-upstream/subprojects/libnbis`) used by `sigfm_scorer.cpp` and `measure_mindtct.c` to evaluate minutiae density distributions.

### Build & Install
```bash
# Build the open-source driver (requires meson, ninja, gcc-c++, opencv)
./elan-0c4f.sh opensource-build

# Install into /usr/local/lib64 (or /usr/local/lib/<multiarch>) and activate
./elan-0c4f.sh opensource-install

# Check driver status
./elan-0c4f.sh status
```

### Enroll & Test Authentication
```bash
# Delete any old/incompatible prints
fprintd-delete "$USER"

# Enroll your finger (16 taps with touch debounce)
fprintd-enroll "$USER" -f right-middle-finger

# Verify via CLI
fprintd-verify "$USER" -f right-middle-finger

# Test desktop unlock
# Lock screen (Super+L) and unlock with your enrolled finger.
# Note: On Fedora, if `with-fingerprint` is enabled, sudo also prompts for fingerprint
# by default. To scope sudo strictly to passwords while keeping desktop lockscreen unlock:
#   sudo sed -i 's/^auth\s*include\s*system-auth/auth       include      password-auth/' /etc/pam.d/sudo
```

### Revert to Distro / TOD
To remove the open-source driver and revert back to distro/TOD libraries at any time:
```bash
./elan-0c4f.sh opensource-uninstall
```

---

## 2. Vendor TOD Driver (Proprietary Fallback)

If you prefer using the patched vendor driver:

```bash
./elan-0c4f.sh install     # build patched .so -> .deb (Ubuntu/Debian) or copy (Fedora/Arch)
./elan-0c4f.sh status      # usb id, pkg state, sha, holds, enrolled prints
./elan-0c4f.sh uninstall
fprintd-delete "$USER"; fprintd-enroll; fprintd-verify
```

### Distro Requirements for TOD
| Distro | TOD-capable libfprint | Module Install |
|---|---|---|
| Debian/Ubuntu | `libfprint-2-tod1` (in repos) | local `.deb` (dpkg-tracked) |
| Fedora | COPR `grahamwhiteuk/libfprint-tod`: `dnf swap libfprint libfprint-tod` | direct copy + `restorecon` |
| Arch | AUR `libfprint-tod-git` (replaces `libfprint`) | direct copy |

---

## 3. How the Open-Source Driver Works

Live USB packet tracing on both Linux (`usbmon`) and Windows Hello (`USBPcap`) proved that `04f3:0c4f` is an **$80 \times 80$ pixel Match-on-Host (MoH)** raw capacitive image sensor. It continuously streams 16-bit raw ADC frames ($12,800\text{ bytes}$ each) whenever a finger touches the die.

Standard minutiae matching (e.g., NIST NBIS `mindtct` / `bozorth3`) fails on small-area sensors. Across all 86 contact touches in our dataset, we measured this empirically using libfprint's compiled `mindtct`: raw frames yield a median of only **1.0 minutia** (mean $1.19 \pm 1.17$, with 34.9% yielding 0 minutiae and 100% yielding $< 6$ minutiae with perimeter removal), far below the feature density required by minutiae matchers to construct valid topological graphs.

The open-source pipeline solves this via:
1. **Center Contact Frame Extraction**: Selects the stable center frame (`len / 2`) from multi-frame contact bursts, avoiding initial touch distortion and release smearing.
2. **ADC Banding Suppression & Bandpass Filtering**: Row median subtraction eliminates 16-bit ADC line banding, followed by a Gaussian bandpass filter ($\sigma_{\text{high}}=5.0, \sigma_{\text{low}}=0.8$).
3. **OpenCV SIFT Feature Extraction**: Detects rich scale-space keypoints across ridge patterns (uncapped `nfeatures=0`, contrast threshold 0.01, edge threshold 20, upsampled $2\times$ bicubic).
4. **Biological-Constrained Affine RANSAC**: Enforces physical human skin elasticity constraints ($0.80 \le \text{scale} \le 1.25$) and spatial spread verification ($\ge 25\text{px}$), preventing false feature clustering.
5. **Touch Debounce**: $900\text{ms}$ software debounce ensures each enrollment stage requires a distinct touch-and-lift motion.

---

## 4. Benchmark Results & Known Limitations

### Initial Benchmark Measurements
- **Live Impostor Series**: 0 false accepts across $N=30$ live un-enrolled finger trials.
  - *Statistical Qualification*: By the Rule of Three, 0/30 establishes a 95% confidence upper bound on FAR of $\le 10.0\%$. In offline cross-validation with $N=100$ impostor trials, the 95% upper bound is $\le 3.0\%$. Larger datasets ($N \approx 3,000$) are required to statistically bound FAR to $\le 0.1\%$ ($1/1,000$).
- **Live Genuine Series**: 21 matches in $N=30$ trials (70.0% single-touch match rate, 95% Wilson CI: $[52.1\%, 83.3\%]$).
  - *Placement Learning Curve*: Trials 1–18 yielded 9/18 matches (50.0%); trials 19–30 yielded 12/12 consecutive matches (100.0%) as user learned centered placement.
  - *Sliding 3-Attempt Window*: 1 / 28 failed windows (3.6% empirical failure rate).
  - *Zero Inlier Scores*: Non-matching trials produced 0 inliers when fewer than 4 features satisfied the affine scale/spread constraints.

### Evaluation Limitations
1. **Single-Subject Dataset**: Tested primarily on 1 person across 3 finger classes in initial sessions. Cross-day and multi-person evaluation is ongoing.
2. **PAM Sudo Scoping**: On Fedora, `authselect enable-feature with-fingerprint` enables `pam_fprintd` globally in `system-auth` (covering `sudo`, lockscreen, and GDM). While password fallback is preserved at all times, users desiring strict security isolation can scope `pam_fprintd` to the lock screen only by changing `/etc/pam.d/sudo` from `auth include system-auth` to `auth include password-auth`:
   ```bash
   sudo sed -i 's/^auth\s*include\s*system-auth/auth       include      password-auth/' /etc/pam.d/sudo
   ```
   This leaves `gdm-fingerprint` functional while guaranteeing `sudo` remains strictly password-authenticated.

---

## Repository Layout
- `elan-0c4f.sh` – Unified management CLI (`opensource-build`, `opensource-install`, `opensource-uninstall`, `install`, `uninstall`, `status`, `deps`)
- `experimental/` – Upstream patch series (`elan_0c4f_sigfm_opensource.patch` for MR !418, `elan_0c4f_mr530.patch` for MR !530) and documentation
- `experiments/LOG.md` – Experimental log documenting Phases 0 through 7
- `experiments/PROTOCOL.md` – Reverse-engineered USB protocol specification (Linux & Windows Hello packet analyses)
- `experiments/WINDOWS_TRACING.md` – Guide for Windows Hello USBPcap capture and analysis
- `vendor/` – Local directory for vendor package archives (downloaded on demand by `elan-0c4f.sh`)

---

## Glossary

- **Match-on-Host (MoH)**: Biometric architecture where raw sensor frames are streamed over USB to the host CPU, where template extraction, filtering, and matching algorithms execute. (The ELAN `04f3:0c4f` is an MoH device.)
- **Touch OEM Drivers / TOD (`libfprint-tod`)**: libfprint's proprietary plugin ABI enabling closed-source vendor shared libraries (`libfprint-2-tod-1-*.so`) to be loaded dynamically at runtime without distributing proprietary source code.
- **SIGFM**: "SIFT Is Good For Matching", a feature-matching algorithm created by Matthieu Charette (@mpi3d) for small-area Match-on-Host sensors, integrated into libfprint via GitLab Merge Request !418 by Natasha England-Elbro.
- **SIFT**: Scale-Invariant Feature Transform (Lowe, 1999; US Patent 6,711,293 expired March 2020), an algorithm used to detect and describe scale- and rotation-invariant gradient keypoints across fingerprint ridge patterns.
- **RANSAC**: Random Sample Consensus, an iterative non-deterministic algorithm used to fit a spatial affine transformation between enrolled and candidate keypoint sets under human skin elasticity and geometric constraints.
- **FAR / FRR**: False Acceptance Rate (the probability that biometric security falsely authenticates an impostor) / False Rejection Rate (the probability that biometric security rejects a genuine enrolled finger).
- **Rule of Three**: Statistical principle ($p \le 3/N$ at 95% confidence for zero observed failure events in $N$ independent trials) used to mathematically upper-bound the true FAR when zero false accepts occur in empirical trials.
- **MR**: GitLab Merge Request (e.g., upstream libfprint MR !418 or MR !530).
