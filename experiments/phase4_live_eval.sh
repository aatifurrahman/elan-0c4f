#!/usr/bin/env bash
# Phase 4 Live Evaluation Script for ELAN 04f3:0c4f with SIGFM
# Usage:
#   ./experiments/phase4_live_eval.sh setup-perms
#   ./experiments/phase4_live_eval.sh enroll [finger_num]
#   ./experiments/phase4_live_eval.sh verify [finger_num] [trial_type] [count]
# Example:
#   ./experiments/phase4_live_eval.sh setup-perms
#   ./experiments/phase4_live_eval.sh enroll 7
#   ./experiments/phase4_live_eval.sh verify 7 genuine 30
#   ./experiments/phase4_live_eval.sh verify 7 impostor 30

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$HERE/libfprint-upstream/build_test"
ENROLL_BIN="$BUILD_DIR/examples/enroll"
VERIFY_BIN="$BUILD_DIR/examples/verify"
STORAGE_FILE="$HERE/test-storage.variant"
RESULTS_CSV="$HERE/phase4_verify_results.csv"

# Finger index mapping:
# 0: left thumb, 1: left index, 2: left middle, 3: left ring, 4: left little
# 5: right thumb, 6: right index, 7: right middle, 8: right ring, 9: right little
MODE="${1:-help}"
FINGER="${2:-7}"

find_usb_dev() {
  local dev_info
  dev_info=$(lsusb -d 04f3:0c4f || true)
  if [ -z "$dev_info" ]; then
    echo "error: ELAN 04f3:0c4f not detected on USB" >&2
    exit 1
  fi
  local bus dev
  bus=$(echo "$dev_info" | awk '{print $2}')
  dev=$(echo "$dev_info" | awk '{print $4}' | tr -d ':')
  echo "/dev/bus/usb/$bus/$dev"
}

setup_perms() {
  local dev_node
  dev_node=$(find_usb_dev)
  echo "==> Configuring permissions for $dev_node..."
  echo "==> Stopping system fprintd service to prevent USB contention..."
  sudo systemctl stop fprintd 2>/dev/null || true
  sudo setfacl -m "u:$USER:rw" "$dev_node"
  echo "==> Permissions successfully granted to $USER for $dev_node."
}

check_device_access() {
  local dev_node
  dev_node=$(find_usb_dev)
  if [ ! -r "$dev_node" ] || [ ! -w "$dev_node" ]; then
    echo "[!] Warning: No read/write access to $dev_node." >&2
    echo "[!] Run: ./experiments/phase4_live_eval.sh setup-perms" >&2
    exit 1
  fi
}

do_enroll() {
  check_device_access
  echo "=========================================================="
  echo " Phase 4 Live Enrollment"
  echo " Binary: $ENROLL_BIN"
  echo " Target Storage: $STORAGE_FILE"
  echo "=========================================================="
  echo "INSTRUCTIONS:"
  echo " 1. Select your finger from the menu when prompted (e.g. 7 for right middle)."
  echo " 2. If prompted whether to update or replace, type 'n'."
  echo " 3. Place and LIFT your finger 16 times as prompted."
  echo "    (Wait for 'Enroll stage X passed' before lifting and tapping again)."
  echo "----------------------------------------------------------"

  cd "$HERE"
  export G_MESSAGES_DEBUG=libfprint
  "$ENROLL_BIN" 2> "$HERE/phase4_enroll.log"

  if [ -f "$STORAGE_FILE" ]; then
    echo "----------------------------------------------------------"
    echo "==> Enrollment SUCCESSFUL! Storage saved to $STORAGE_FILE"
  else
    echo "----------------------------------------------------------"
    echo "==> Enrollment did not produce $STORAGE_FILE"
  fi
}

do_verify() {
  check_device_access
  local trial_type="${3:-genuine}"
  local count="${4:-30}"

  if [ ! -f "$STORAGE_FILE" ]; then
    echo "error: $STORAGE_FILE not found. Please run enroll first." >&2
    exit 1
  fi

  echo "=========================================================="
  echo " Phase 4 Live Verification (Finger: $FINGER, Type: $trial_type, Trials: $count)"
  echo "=========================================================="

  if [ ! -f "$RESULTS_CSV" ]; then
    echo "timestamp,finger,trial_type,trial_idx,matched,score,threshold" > "$RESULTS_CSV"
  fi

  cd "$HERE"
  local matches=0
  local total=0

  for ((i=1; i<=count; i++)); do
    echo ""
    echo ">>> Trial $i / $count ($trial_type) - PLACE FINGER ON SENSOR NOW <<<"
    export G_MESSAGES_DEBUG=all
    local raw_output
    raw_output=$(echo "$FINGER" | "$VERIFY_BIN" 2>&1 || true)

    local score
    score=$(echo "$raw_output" | grep -o 'sigfm score [0-9]*/[0-9]*' | tail -n 1 | awk '{print $3}' || true)
    local score_val="0"
    local thresh_val="12"
    if [ -n "$score" ]; then
      score_val=$(echo "$score" | cut -d'/' -f1)
      thresh_val=$(echo "$score" | cut -d'/' -f2)
    fi

    local matched="no"
    if echo "$raw_output" | grep -q -E "^MATCH!" || [ "$score_val" -ge "$thresh_val" ]; then
      matched="yes"
      matches=$((matches + 1))
    fi
    total=$((total + 1))

    local ts
    ts=$(date +%Y-%m-%d_%H:%M:%S)
    echo "$ts,$FINGER,$trial_type,$i,$matched,$score_val,$thresh_val" >> "$RESULTS_CSV"

    echo "--- Trial $i Result: Matched=$matched, Score=$score_val / $thresh_val (Cumulative Matches: $matches / $total) ---"
    
    if [ "$i" -lt "$count" ]; then
      sleep 1.0
    fi
  done

  echo ""
  echo "=========================================================="
  echo " Verification Series Summary ($trial_type)"
  echo " Total Trials: $total"
  echo " Matches:      $matches"
  echo " Non-Matches:  $((total - matches))"
  local match_rate
  match_rate=$(awk "BEGIN {printf \"%.2f\", ($matches / $total) * 100}")
  echo " Match Rate:   $match_rate %"
  echo " Log saved to: $RESULTS_CSV"
  echo "=========================================================="
}

case "$MODE" in
  setup-perms)
    setup_perms
    ;;
  enroll)
    do_enroll
    ;;
  verify)
    do_verify "$@"
    ;;
  *)
    echo "Usage:"
    echo "  $0 setup-perms                 # Configure USB device permissions"
    echo "  $0 enroll [finger_num]         # Enroll finger (e.g., 7 for right middle)"
    echo "  $0 verify [finger_num] [genuine|impostor] [count]  # Run live verify series"
    exit 1
    ;;
esac
