# ELAN 04f3:0c4f Fingerprint Reader on Linux

Complete Linux support for the ELAN `04f3:0c4f` Match-on-Host fingerprint sensor (tested and verified on the **Acer Aspire A715-51G**), offering two driver options:
1. **Open-Source Driver (Primary)**: Native upstream `libfprint` with OpenCV SIFT/RANSAC (SIGFM matcher) – 100% open-source, zero proprietary binary blobs, with 0 false accepts observed in initial benchmarks ($N=30$, Rule of Three 95% upper bound $\le 10\%$).
2. **Vendor TOD Driver (Instant Fallback)**: Patched proprietary Match-on-Host shim (`libfprint-2-tod1-elan.so`) derived from Lenovo package `r1slf01w.zip`.

---

## 1. Open-Source Driver (Primary)

The open-source driver compiles upstream `libfprint` with native ELAN `04f3:0c4f` press-type support and the SIGFM SIFT/RANSAC matcher. It installs into `/usr/local/lib64`, which shadows the distro library without modifying package-managed files.

### Build & Install
```bash
# Build the open-source driver (requires meson, ninja, gcc-c++, opencv-devel)
./elan-0c4f.sh opensource-build

# Install into /usr/local/lib64 and activate
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
- `elan-0c4f.sh` – Unified management CLI (`opensource-build`, `opensource-install`, `opensource-uninstall`, `install`, `uninstall`, `status`)
- `experimental/` – Upstream patch series (`elan_0c4f_sigfm_opensource.patch` for MR !418, `elan_0c4f_mr530.patch` for MR !530) and documentation
- `experiments/LOG.md` – Experimental log documenting Phases 0 through 7
- `experiments/PROTOCOL.md` – Reverse-engineered USB protocol specification (Linux & Windows Hello packet analyses)
- `experiments/WINDOWS_TRACING.md` – Guide for Windows Hello USBPcap capture and analysis
- `vendor/` – Local directory for vendor package archives (downloaded on demand by `elan-0c4f.sh`)
