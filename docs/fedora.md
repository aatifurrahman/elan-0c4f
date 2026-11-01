# ELAN 04f3:0c4f on Fedora Linux

This guide covers the Fedora-specific setup, SELinux considerations, and PAM configuration for the ELAN `04f3:0c4f` fingerprint sensor using the patched Lenovo Touch-on-Driver (TOD) driver.

---

## 1. Prerequisites (TOD-Capable libfprint)

Stock Fedora packages upstream `libfprint`, which does not support loading Touch OEM Driver (`tod-1`) plugins. 

Swap to the community TOD build from COPR:

```bash
sudo dnf copr enable grahamwhiteuk/libfprint-tod -y
sudo dnf swap libfprint libfprint-tod -y
```

*(This COPR repository also provides the necessary SELinux policy package `libfprint-tod-selinux` for fprintd plugin execution).*

Verify that the TOD library is installed:

```bash
ldconfig -p | grep libfprint-2-tod.so.1
```

---

## 2. Driver Installation

Run the installer from this repository:

```bash
./elan-0c4f.sh install
```

The script will:
1. Download Lenovo's official driver package and verify its SHA-256 hash.
2. Apply the 3-byte PID and parameter patch.
3. Discover Fedora's compiled-in module directory (`/usr/lib64/libfprint-2/tod-1/`).
4. Install `libfprint-2-tod1-elan.so`.
5. Restore the appropriate SELinux context via `restorecon`.
6. Restart `fprintd.service`.

Check status:

```bash
./elan-0c4f.sh status
```

---

## 3. Enrollment and Verification

```bash
# Clear any existing prints for the current user:
fprintd-delete "$USER" || true

# Enroll (press your finger firmly on the sensor when prompted):
fprintd-enroll

# Verify matching:
fprintd-verify
```

---

## 4. Enabling PAM Authentication (authselect)

On Fedora, the PAM module `pam_fprintd.so` is packaged separately in `fprintd-pam`:

```bash
# Install PAM module
sudo dnf install -y fprintd-pam

# Enable fingerprint authentication in your authselect profile
sudo authselect enable-feature with-fingerprint
sudo authselect apply-changes
```

Test PAM authentication:

```bash
# Verify via CLI:
fprintd-verify "$USER"
```

### Scoping Sudo to Password-Only (Recommended)
By default, `authselect enable-feature with-fingerprint` enables `pam_fprintd.so` globally in `/etc/pam.d/system-auth`, which applies to `sudo`, lockscreen, and GDM.
To scope `sudo` strictly to password authentication while keeping desktop lockscreen fingerprint unlock intact:

```bash
sudo sed -i 's/^auth\s*include\s*system-auth/auth       include      password-auth/' /etc/pam.d/sudo
```

This isolates `sudo` (and `sudo-i`) to passwords, leaving `gdm-fingerprint` (which includes `fingerprint-auth`) fully functional for fast screen unlock.

---

## 5. Troubleshooting & SELinux

### SELinux Contexts
If `fprintd` cannot load the module, verify and restore the file context:

```bash
sudo restorecon -v /usr/lib64/libfprint-2/tod-1/libfprint-2-tod1-elan.so
```

To inspect recent SELinux AVC denials related to `fprintd`:

```bash
sudo ausearch -m avc -ts recent
```

### Daemon Logs
To monitor driver initialization and fingerprint matching in real time:

```bash
journalctl -u fprintd -f
```

If you see `reject! finger area ... < 75%`, place your finger flatter on the reader to ensure sufficient surface coverage.
