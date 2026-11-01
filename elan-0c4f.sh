#!/usr/bin/env bash
# ELAN 04f3:0c4f fingerprint: patched Lenovo TOD driver (match-on-chip).
# Usage: ./elan-0c4f.sh {build|install|uninstall|status}
# Debian/Ubuntu: .deb (dpkg-tracked). Fedora/Arch/other: direct copy into the TOD module dir.
set -euo pipefail

[ "$(uname -m)" = x86_64 ] || die "x86_64 only"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
B="$HERE/build"
VENDOR_URL="https://download.lenovo.com/pccbbs/mobiles/r1slf01w.zip"
VENDOR_ZIP="$HERE/vendor/r1slf01w.zip"
VENDOR_SHA256=87d7df1a4364d96f635dc85359d21f45afd9b6c56b3476be31d8e4c8f7e0960f
SO_NAME=libfprint-2-tod1-elan.so
PKG=libfprint-2-tod1-elan-0c4f
VER=0.0.8+0c4f
SHA_ORIG=a5060ccdfc0c613bd4522be29f87cd94f098e6b83294cf02cd5a958b24b27f80
SHA_PATCHED=f2ce650d9d9a0a7d547c024bf0929f2b3c45322ebb5927e642b18b0f98fc8ee6

die() { echo "error: $*" >&2; exit 1; }

# ---- distro detection ------------------------------------------------------
family() {
  . /etc/os-release
  case " ${ID:-} ${ID_LIKE:-} " in
    *" debian "*|*" ubuntu "*) echo deb ;;
    *" fedora "*|*" rhel "*)   echo rpm ;;
    *" arch "*)                echo arch ;;
    *)                         echo other ;;
  esac
}

# Module dir is compiled into the TOD-enabled libfprint; read it from there so
# /usr/lib vs /usr/lib64 vs multiarch never has to be guessed.
module_dir() {
  local lib d
  for lib in $(ldconfig -p | awk '/libfprint-2(-tod)?\.so/{print $NF}' | sort -u); do
    d=$(grep -a -o '/[A-Za-z0-9_./+-]*libfprint-2/tod-1' "$lib" 2>/dev/null | head -1) || true
    [ -n "$d" ] && { echo "$d"; return; }
  done
  return 1
}

# libfprint must be the TOD-capable build, otherwise the module is silently ignored.
tod_lib_present() { ldconfig -p | grep 'libfprint-2-tod\.so\.1' >/dev/null; }

need_tod_lib() {
  tod_lib_present && return 0
  case "$(family)" in
    rpm) echo "No TOD-capable libfprint. Fedora ships plain libfprint. Run:
  sudo dnf copr enable grahamwhiteuk/libfprint-tod && sudo dnf swap libfprint libfprint-tod
(this COPR also pulls an SELinux policy), then re-run install." ;;
    arch) echo "No TOD-capable libfprint. Install from AUR (replaces libfprint):
  yay -S libfprint-tod-git     # or any AUR helper / manual makepkg
then re-run install." ;;
    deb) echo "Run: sudo apt install libfprint-2-tod1 fprintd" ;;
    *) echo "Build libfprint-tod (https://gitlab.freedesktop.org/3v1n0/libfprint) and install it, then re-run." ;;
  esac
  return 1
}


# Remove stale dpkg diversions of the distro libfprint left by old experiments.
# Order matters: drop the custom file at the original path, un-divert with
# --rename (moves the real distro file back), then reinstall to guarantee stock.
clean_diversions() {
  local line orig
  dpkg-divert --list '*libfprint-2.so*' | while read -r line; do
    orig=$(sed -n 's/^diversion of \(.*\) to .* by .*/\1/p' <<<"$line")
    [ -n "$orig" ] || continue
    echo "removing stale dpkg diversion for $orig"
    sudo rm -f "$orig"
    sudo dpkg-divert --rename --remove "$orig"
  done
  sudo rm -f /usr/lib/x86_64-linux-gnu/libfprint-2.so.2*.distrib*   # orphaned manual backups (ldconfig soname trap)
  if [ -n "$(dpkg-divert --list '*libfprint-2.so*')" ] || dpkg -V libfprint-2-2 2>/dev/null | grep 'libfprint-2.so' >/dev/null; then
    echo "reinstalling stock libfprint"
    sudo apt-get install --reinstall -y libfprint-2-2 libfprint-2-tod1
  fi
}

# Portable path: plain copy into the directory libfprint actually scans.
install_raw() {
  local d; d=$(module_dir) || die "cannot determine TOD module dir"
  if compgen -G "/usr/local/lib*/libfprint*" >/dev/null; then
    echo "warning: /usr/local libfprint shadows the system one."
    if [ -t 0 ]; then
      read -rp "remove it? [y/N] " a
      if [[ "${a:-}" =~ ^[Yy]$ ]]; then
        sudo rm -rf /usr/local/lib*/libfprint* /usr/local/include/libfprint-2 /usr/local/lib*/pkgconfig/libfprint-2.pc
        sudo ldconfig
      fi
    fi
  fi
  sudo install -D -m 0755 "$B/patched.so" "$d/$SO_NAME"
  command -v restorecon >/dev/null && sudo restorecon -v "$d/$SO_NAME" || true
  sudo systemctl restart fprintd.service
  echo "installed $d/$SO_NAME"
}

# Extract (nested zip) -> verify stock sha -> patch 3 bytes -> verify patched sha
build_so() {
  mkdir -p "$B"
  if ! { [ -f "$VENDOR_ZIP" ] && echo "$VENDOR_SHA256  $VENDOR_ZIP" | sha256sum -c - >/dev/null 2>&1; }; then
    mkdir -p "$(dirname "$VENDOR_ZIP")"
    rm -f "$VENDOR_ZIP.part"
    echo "downloading Lenovo driver package from official source..."
    curl -fL --proto '=https' -A 'Mozilla/5.0' -o "$VENDOR_ZIP.part" "$VENDOR_URL" \
      || die "download failed; fetch $VENDOR_URL manually into vendor/"
    echo "$VENDOR_SHA256  $VENDOR_ZIP.part" | sha256sum -c - >/dev/null || { rm -f "$VENDOR_ZIP.part"; die "checksum mismatch"; }
    mv "$VENDOR_ZIP.part" "$VENDOR_ZIP"
  fi
  [ -f "$B/orig.so" ] || {
    unzip -p "$VENDOR_ZIP" '*.zip' > "$B/inner.zip"
    unzip -p "$B/inner.zip" "$SO_NAME" > "$B/orig.so"
  }
  SHA_ORIG=$SHA_ORIG SHA_PATCHED=$SHA_PATCHED B=$B python3 - <<'PY'
import hashlib, os, sys
B = os.environ["B"]
buf = bytearray(open(f"{B}/orig.so", "rb").read())
if hashlib.sha256(buf).hexdigest() != os.environ["SHA_ORIG"]:
    sys.exit("stock binary sha mismatch: offsets below are only valid for Lenovo 0.0.8")
# offsets verified against ELF symbols id_table@0x325a0, efd_parameter_init@0x18e00
for off, old, new, what in [
    (0x18E92, 0x4B, 0x4F, "efd_parameter_init: cmp $0xc4b -> $0xc4f"),
    (0x325A0, 0x42, 0x4F, "id_table[0].pid 0c42 -> 0c4f"),
    (0x32630, 0x4B, 0x4F, "id_table[3].pid 0c4b -> 0c4f"),
]:
    assert buf[off] == old, f"{what}: found {buf[off]:#x} at {off:#x}"
    buf[off] = new
if hashlib.sha256(buf).hexdigest() != os.environ["SHA_PATCHED"]:
    sys.exit("patched sha mismatch")
open(f"{B}/patched.so", "wb").write(buf)
PY
  echo "patched.so ok ($SHA_PATCHED)"
}

# Wrap in a .deb so dpkg owns the file: clean removal, no apt-mark hold needed.
build_deb() {
  build_so
  local DEST=/usr/lib/x86_64-linux-gnu/libfprint-2/tod-1/$SO_NAME
  local r="$B/deb"
  rm -rf "$r"; mkdir -p "$r/DEBIAN" "$r$(dirname "$DEST")"
  install -m 0755 "$B/patched.so" "$r$DEST"
  cat > "$r/DEBIAN/control" <<CTL
Package: $PKG
Version: $VER
Architecture: amd64
Maintainer: local <root@localhost>
Depends: libfprint-2-tod1, fprintd
Conflicts: libfprint-2-tod1-elan
Replaces: libfprint-2-tod1-elan
Provides: libfprint-2-tod1-elan
Description: Lenovo ELAN TOD module patched to bind 04f3:0c4f
 Local build; stock Lenovo 0.0.8 binary with 3 bytes changed.
CTL
  for s in postinst postrm; do
    printf '#!/bin/sh\nsystemctl restart fprintd.service >/dev/null 2>&1 || true\n' > "$r/DEBIAN/$s"
    chmod 0755 "$r/DEBIAN/$s"
  done
  dpkg-deb --root-owner-group -b "$r" "$B/${PKG}_${VER}_amd64.deb" >/dev/null
  echo "built $B/${PKG}_${VER}_amd64.deb"
}

build_opensource() {
  local src_dir="$HERE/experiments/libfprint-upstream"
  local patch_file="$HERE/experimental/elan_0c4f_sigfm_opensource.patch"

  if [ ! -d "$src_dir" ]; then
    echo "==> Upstream libfprint source not found in $src_dir."
    echo "==> Cloning upstream libfprint from GitLab..."
    command -v git >/dev/null || die "git is required to fetch upstream libfprint"
    mkdir -p "$HERE/experiments"
    git clone https://gitlab.freedesktop.org/libfprint/libfprint.git "$src_dir"
    echo "==> Fetching MR !418 (SIGFM baseline)..."
    git -C "$src_dir" fetch origin merge-requests/418/head:mr-418-sigfm
    git -C "$src_dir" checkout mr-418-sigfm
    echo "==> Applying ELAN 0c4f open-source driver patch..."
    git -C "$src_dir" apply "$patch_file"
  fi

  local bdir="$src_dir/build"
  if [ -f "$src_dir/build_test/build.ninja" ]; then
    bdir="$src_dir/build_test"
  fi

  if [ ! -f "$bdir/build.ninja" ]; then
    echo "==> Configuring meson build in $bdir..."
    command -v meson >/dev/null || die "meson is required to build (install: meson ninja opencv gcc-c++)"
    meson setup "$bdir" "$src_dir" -Ddrivers=elan -Dsigfm=enabled -Dudev_rules=disabled -Dudev_hwdb=disabled -Ddoc=false
  fi

  echo "==> Building open-source libfprint with SIGFM (OpenCV SIFT/RANSAC)..."
  ninja -C "$bdir"
  echo "==> Open-source libfprint built successfully: $bdir/libfprint/libfprint-2.so.2.0.0"
}

install_opensource() {
  local src_dir="$HERE/experiments/libfprint-upstream"
  local bdir="$src_dir/build"
  if [ -f "$src_dir/build_test/libfprint/libfprint-2.so.2.0.0" ]; then
    bdir="$src_dir/build_test"
  fi
  local src_so="$bdir/libfprint/libfprint-2.so.2.0.0"
  if [ ! -f "$src_so" ]; then
    build_opensource
    if [ -f "$src_dir/build_test/libfprint/libfprint-2.so.2.0.0" ]; then
      bdir="$src_dir/build_test"
    fi
    src_so="$bdir/libfprint/libfprint-2.so.2.0.0"
  fi
  local target_dir="/usr/local/lib64"
  echo "==> Installing open-source libfprint to $target_dir..."
  sudo mkdir -p "$target_dir"
  sudo install -m 0755 "$src_so" "$target_dir/libfprint-2.so.2.0.0"
  sudo ln -sf libfprint-2.so.2.0.0 "$target_dir/libfprint-2.so.2"
  sudo ln -sf libfprint-2.so.2 "$target_dir/libfprint-2.so"

  if command -v restorecon >/dev/null 2>&1; then
    echo "==> Restoring SELinux context for $target_dir/libfprint-2.so*..."
    sudo restorecon -v "$target_dir"/libfprint-2.so* || true
  fi

  echo "==> Updating system dynamic linker cache (ldconfig)..."
  sudo ldconfig

  echo "==> Restarting fprintd.service..."
  sudo systemctl restart fprintd.service || true

  echo "=========================================================="
  echo " Open-Source ELAN 0c4f Driver Installed Successfully!"
  echo " Active library: $(ldd /usr/libexec/fprintd 2>/dev/null | grep libfprint-2.so.2 | awk '{print $3}')"
  echo " Note: Enrolled TOD prints are incompatible with SIGFM."
  echo " Run:  fprintd-delete \"\$USER\" && fprintd-enroll"
  echo " To revert to TOD at any time: ./elan-0c4f.sh opensource-uninstall"
  echo "=========================================================="
}

uninstall_opensource() {
  local target_dir="/usr/local/lib64"
  echo "==> Removing open-source libfprint from $target_dir..."
  sudo rm -f "$target_dir"/libfprint-2.so*
  echo "==> Updating system dynamic linker cache (ldconfig)..."
  sudo ldconfig
  echo "==> Restarting fprintd.service..."
  sudo systemctl restart fprintd.service || true
  echo "=========================================================="
  echo " Reverted to stock/TOD libfprint."
  echo " Active library: $(ldd /usr/libexec/fprintd 2>/dev/null | grep libfprint-2.so.2 | awk '{print $3}')"
  echo "=========================================================="
}

case "${1:-}" in
  build)
    if [ "$(family)" = deb ]; then build_deb
    else build_so; fi
    ;;
  install)
    [ "$(family)" = deb ] && clean_diversions
    need_tod_lib || exit 1
    build_so
    if [ "$(family)" = deb ]; then
      build_deb
      sudo apt-mark unhold libfprint-2-2 libfprint-2-tod1 >/dev/null 2>&1 || true
      sudo rm -f /usr/lib/x86_64-linux-gnu/libfprint-2/tod-1/$SO_NAME.disabled
      sudo apt-get install -y "$B/${PKG}_${VER}_amd64.deb"
    else
      install_raw
    fi
    echo "next: fprintd-delete \"\$USER\"; fprintd-enroll; fprintd-verify"
    ;;
  uninstall)
    if [ "$(family)" = deb ]; then sudo apt-get remove -y "$PKG"
    else d=$(module_dir 2>/dev/null) && sudo rm -fv "$d/$SO_NAME" && sudo systemctl restart fprintd.service; fi
    ;;
  opensource-build|build-opensource)
    build_opensource
    ;;
  opensource-install|install-opensource)
    install_opensource
    ;;
  opensource-uninstall|uninstall-opensource)
    uninstall_opensource
    ;;
  status)
    echo "family: $(family)"
    lsusb -d 04f3:0c4f || echo "04f3:0c4f not present"
    local_active=$(ldd /usr/libexec/fprintd 2>/dev/null | grep libfprint-2.so.2 | awk '{print $3}' || true)
    if [[ "$local_active" =~ ^/usr/local/ ]]; then
      echo "active driver: OPEN-SOURCE (SIGFM SIFT/RANSAC) [$local_active]"
    elif tod_lib_present && [ -f "$(module_dir 2>/dev/null)/$SO_NAME" ]; then
      echo "active driver: LENOVO TOD (Proprietary Match-on-Chip shim) [$(module_dir 2>/dev/null)/$SO_NAME]"
    else
      echo "active driver: STOCK DISTRO [$local_active]"
    fi
    tod_lib_present && echo "TOD libfprint: yes" || echo "TOD libfprint: NO"
    if d=$(module_dir); then
      echo "module dir: $d"
      [ -f "$d/$SO_NAME" ] && echo "installed sha: $(sha256sum "$d/$SO_NAME" | cut -d' ' -f1)  (want $SHA_PATCHED)"
    fi
    [ "$(family)" = rpm ] && { rpm -q fprintd-pam >/dev/null 2>&1 || echo "PAM module: fprintd-pam NOT installed (run: sudo dnf install fprintd-pam)"; }
    [ "$(family)" = deb ] && { dpkg -s "$PKG" 2>/dev/null | grep -E '^(Status|Version)' || true
      echo "holds: $(apt-mark showhold | grep -E 'libfprint' || echo none)"; }
    command -v getenforce >/dev/null && echo "selinux: $(getenforce)"
    fprintd-list "${USER:-$(id -un)}" 2>&1 | head -8
    ;;
  *) die "usage: $0 {build|install|uninstall|opensource-build|opensource-install|opensource-uninstall|status}" ;;
esac
