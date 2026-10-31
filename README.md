# ELAN 04f3:0c4f on Linux (patched Lenovo TOD, match-on-chip)

Installer and patch script to enable the **ELAN 04f3:0c4f** fingerprint reader on Linux using Lenovo's proprietary Touch-on-Driver (TOD) match-on-chip binary.

```bash
./elan-0c4f.sh install     # download official package, verify checksum, patch .so, and install
./elan-0c4f.sh status      # check USB device, library status, SELinux, and enrolled prints
./elan-0c4f.sh uninstall
fprintd-delete "$USER"; fprintd-enroll; fprintd-verify
sudo pam-auth-update       # enable fingerprint auth (Ubuntu/Debian)
# on Fedora: see docs/fedora.md
```

## Distros & Support Status

| Distro | TOD-capable libfprint | Installation Method | Status |
|---|---|---|---|
| **Ubuntu / Debian** | `libfprint-2-tod1` (in distro repos) | Local `.deb` (`dpkg`-tracked) | **Tested and verified** |
| **Fedora** | COPR `grahamwhiteuk/libfprint-tod` | Direct copy + `restorecon` | **Tested and verified** ([guide](docs/fedora.md)) |
| **Arch Linux** | AUR `libfprint-tod-git` (replaces stock `libfprint`) | Direct copy | **Untested** |

The script verifies architecture (`x86_64`) and checks for a TOD-capable `libfprint` before attempting installation. The module directory is discovered dynamically from the installed `libfprint` library, properly handling `/usr/lib`, `/usr/lib64`, and multiarch paths.

## Why this works

Lenovo's official TOD module targets `04f3:0c4b`. The `04f3:0c4f` sensor shares its MCU protocol and register structure, but is ignored by the driver. This tool applies a 3-byte patch to select register `0x0c` and update the USB ID tables (stock SHA-256 `a5060ccd…7f80` $\to$ patched SHA-256 `f2ce650d…8ee6`):

| Offset | Stock | New | Description |
|---|---|---|---|
| `0x18E92` | `0x4B` | `0x4F` | `efd_parameter_init`: `cmp $0xc4b` $\to$ `$0xc4f` (selects register 0x0c) |
| `0x325A0` | `0x42` | `0x4F` | `id_table[0]` PID (`0x0c42` $\to$ `0x0c4f`) |
| `0x32630` | `0x4B` | `0x4F` | `id_table[3]` PID (`0x0c4b` $\to$ `0x0c4f`) |

Lenovo's driver delegates fingerprint processing and matching to the on-chip hardware microcontroller (Match-on-Chip), which avoids the verification failures common to open-source minutiae matchers on small ($96 \times 96$) sensor arrays.

The script verifies SHA-256 sums at each stage (vendor archive, stock binary, and patched binary) to ensure integrity.

## Layout

- `elan-0c4f.sh` – Master CLI script (`build`, `install`, `uninstall`, `status`).
- `docs/fedora.md` – Fedora-specific instructions for COPR, SELinux policies, and PAM via `authselect`.
- `experimental/elan_0c4f_opensource.patch` – Upstream `libfprint` patch for `elan.c` (saved for testing if SigFM / MR !530 lands).
- `LICENSE` – MIT license.

## Troubleshooting

- **Check active driver in journal**:
  ```bash
  journalctl -u fprintd -b | grep -i -E 'elan|tod'
  ```
- **Fedora SELinux / PAM issues**:
  See [docs/fedora.md](docs/fedora.md).
- **Stale manual builds**:
  `./elan-0c4f.sh status` detects if `/usr/local` libraries shadow distro packages.

## Disclaimer

This project is unaffiliated with Lenovo or ELAN Microelectronics. It downloads and patches Lenovo's proprietary driver package locally on your machine at your own discretion. This repository does not host, redistribute, or claim ownership over any Lenovo or ELAN proprietary files or binaries.
