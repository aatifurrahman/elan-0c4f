#!/usr/bin/env bash
# Interactive Multi-Driver & Bi-Manual (Left/Right Hand) Data Collection Helper
# Usage:
#   ./experiments/collect_session.sh [ubuntu/sigfm | ubuntu/lenovo-tod]

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXP_DIR="$HERE"
ROOT_DIR="$(dirname "$EXP_DIR")"
TRACE_SCRIPT="$EXP_DIR/trace.sh"
DATASET_SCRIPT="$EXP_DIR/dataset.py"

TARGET_DRIVER="${1:-auto}"
PERSON="${2:-p01}"
SESSION="${3:-s02}"

detect_active_driver() {
  local active
  active=$(ldconfig -p 2>/dev/null | grep 'libfprint-2.so.2 ' | head -n 1 | awk '{print $NF}' || true)
  if [[ "$active" == *"/usr/local/"* ]]; then
    echo "ubuntu/sigfm"
  else
    echo "ubuntu/lenovo-tod"
  fi
}

ACTIVE_DRIVER=$(detect_active_driver)

if [ "$TARGET_DRIVER" = "auto" ]; then
  DRIVER="$ACTIVE_DRIVER"
else
  DRIVER="$TARGET_DRIVER"
fi

echo "=========================================================="
echo " ELAN 04f3:0c4f Multi-Driver Data Collection Helper"
echo " Target Driver: $DRIVER"
echo " Active Driver: $ACTIVE_DRIVER"
echo " Person ID:     $PERSON | Session: $SESSION"
echo " Genuine Hand:  RIGHT (right-index-finger)"
echo " Impostor Hand: LEFT  (left-index-finger)"
echo "=========================================================="

if [ "$DRIVER" != "$ACTIVE_DRIVER" ]; then
  echo ""
  echo "[!] WARNING: Requested driver ($DRIVER) does not match active system driver ($ACTIVE_DRIVER)!"
  if [ "$DRIVER" = "ubuntu/lenovo-tod" ]; then
    echo "[!] To activate Lenovo TOD, run in another terminal:"
    echo "    ./elan-0c4f.sh opensource-uninstall"
  elif [ "$DRIVER" = "ubuntu/sigfm" ]; then
    echo "[!] To activate Upstream SIGFM, run in another terminal:"
    echo "    ./elan-0c4f.sh opensource-install"
  fi
  read -r -p "Do you want to proceed with ACTIVE driver ($ACTIVE_DRIVER)? [Y/n] " confirm
  if [[ "$confirm" =~ ^[Nn]$ ]]; then
    echo "Aborting. Please switch active driver and rerun."
    exit 1
  fi
  DRIVER="$ACTIVE_DRIVER"
fi

GENUINE_FINGER="right-index-finger"
IMPOSTOR_FINGER="left-index-finger"

# Ensure sudo credentials and usbmon module are ready
sudo -v
if ! lsmod | grep -q "^usbmon\b"; then
  echo "==> Loading usbmon kernel module..."
  sudo modprobe usbmon
fi

show_menu() {
  echo ""
  echo "Select collection routine:"
  echo "  1) Full Bi-Manual Protocol (Enroll Right -> 10 Right Probes -> 10 Left Impostor Probes)"
  echo "  2) Enroll Genuine Finger ($GENUINE_FINGER)"
  echo "  3) Collect Genuine Probes ($GENUINE_FINGER, Right Hand)"
  echo "  4) Collect Impostor Probes ($IMPOSTOR_FINGER, Left Hand)"
  echo "  5) Show Dataset Summary"
  echo "  6) Exit"
  echo ""
  read -r -p "Enter choice [1-6]: " choice
}

do_enroll() {
  echo ""
  echo "=========================================================="
  echo " STEP: Genuine Enrollment ($GENUINE_FINGER - RIGHT HAND)"
  echo "=========================================================="
  echo "Instruction: Repeatedly place and lift your RIGHT index finger"
  echo "when prompted by fprintd until enrollment completes."
  read -r -p "Press [ENTER] to begin enrollment..." _
  "$TRACE_SCRIPT" enroll "$GENUINE_FINGER" "$PERSON" "$SESSION" "genuine_enroll" "$DRIVER"
}

do_genuine_probes() {
  local count="${1:-10}"
  echo ""
  echo "=========================================================="
  echo " STEP: Genuine Verification Probes ($count Touches - RIGHT HAND)"
  echo " Finger: $GENUINE_FINGER | Driver: $DRIVER"
  echo "=========================================================="
  for ((i=1; i<=count; i++)); do
    stty sane 2>/dev/null || true
    echo ""
    echo ">>> Touch $i / $count (GENUINE: RIGHT HAND) <<<"
    read -r -p "Place RIGHT index finger on sensor and press [ENTER]..." _
    "$TRACE_SCRIPT" verify "$GENUINE_FINGER" "$PERSON" "$SESSION" "genuine_probe_touch_${i}" "$DRIVER"
    sleep 1.0
  done
}

do_impostor_probes() {
  local count="${1:-10}"
  echo ""
  echo "=========================================================="
  echo " STEP: Impostor Verification Probes ($count Touches - LEFT HAND)"
  echo " Finger: $IMPOSTOR_FINGER (Testing against $GENUINE_FINGER enrolled)"
  echo " Driver: $DRIVER"
  echo "=========================================================="
  for ((i=1; i<=count; i++)); do
    stty sane 2>/dev/null || true
    echo ""
    echo ">>> Touch $i / $count (IMPOSTOR: LEFT HAND) <<<"
    read -r -p "Place LEFT index finger on sensor and press [ENTER]..." _
    # Note: verify against the enrolled finger to record the rejection trace!
    "$TRACE_SCRIPT" verify "$GENUINE_FINGER" "$PERSON" "$SESSION" "impostor_left_probe_touch_${i}" "$DRIVER"
    sleep 1.0
  done
}

while true; do
  show_menu
  case "$choice" in
    1)
      do_enroll
      do_genuine_probes 10
      do_impostor_probes 10
      echo ""
      echo "Full routine completed for driver: $DRIVER!"
      python3 "$DATASET_SCRIPT" summary
      ;;
    2)
      do_enroll
      ;;
    3)
      read -r -p "Number of genuine touches to record [default 10]: " n_g
      do_genuine_probes "${n_g:-10}"
      ;;
    4)
      read -r -p "Number of impostor touches to record [default 10]: " n_imp
      do_impostor_probes "${n_imp:-10}"
      ;;
    5)
      python3 "$DATASET_SCRIPT" summary
      ;;
    6)
      echo "Exiting."
      exit 0
      ;;
    *)
      echo "Invalid choice: $choice"
      ;;
  esac
done
