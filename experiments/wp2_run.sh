#!/usr/bin/env bash
# WP2: Front-End Equivalence Test Runner
# Captures simultaneous usbmon traffic while running libfprint's img-capture,
# then performs numerical pixel comparison against raw USB packets.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
LIBFPRINT_BUILD="$HERE/libfprint-upstream/build_test"
IMG_CAPTURE="$LIBFPRINT_BUILD/examples/img-capture"
LIB_DIR="$LIBFPRINT_BUILD/libfprint"

PCAP_OUT="/tmp/wp2_capture.pcap"
PGM_OUT="/tmp/driver_captured.pgm"
TCPDUMP_LOG="/tmp/wp2_tcpdump.log"

rm -f "$PCAP_OUT" "$PGM_OUT" "$TCPDUMP_LOG"

echo "=========================================================="
echo " WP2: Front-End Equivalence Live Test"
echo "=========================================================="

# 1. Check device
DEV_INFO=$(lsusb -d 04f3:0c4f || true)
if [ -z "$DEV_INFO" ]; then
  echo "error: ELAN 04f3:0c4f not detected on USB" >&2
  exit 1
fi

BUS=$(echo "$DEV_INFO" | awk '{print $2}' | sed 's/^0*//')
DEV=$(echo "$DEV_INFO" | awk '{print $4}' | tr -d ':' | sed 's/^0*//')
IFACE="usbmon${BUS}"

echo "Sensor detected: USB Bus $BUS, Device $DEV (Interface: $IFACE)"

# 2. Check usbmon kernel module
if ! lsmod | grep -q "^usbmon"; then
  echo "==> Loading usbmon kernel module (requires sudo)..."
  sudo modprobe usbmon
fi

# Ensure sudo is ready
sudo -v

echo "==> Starting background packet capture on $IFACE..."
sudo tcpdump -i "$IFACE" -w "$PCAP_OUT" -s 0 -U > "$TCPDUMP_LOG" 2>&1 &
DUMP_PID=$!
sleep 1.0

if ! kill -0 "$DUMP_PID" 2>/dev/null; then
  echo "error: tcpdump failed to start. Log output:" >&2
  cat "$TCPDUMP_LOG" >&2
  exit 1
fi

echo ""
echo "=========================================================="
echo " ==> SENSOR ACTIVE: PLACE YOUR FINGER ON THE SENSOR NOW..."
echo "=========================================================="
echo ""

# Run img-capture from the private build prefix
LD_LIBRARY_PATH="$LIB_DIR" "$IMG_CAPTURE" "$PGM_OUT" || true

sleep 1.0

echo "==> Stopping packet capture..."
sudo kill -INT "$DUMP_PID" 2>/dev/null || true
wait "$DUMP_PID" 2>/dev/null || true
sudo chown "$USER:" "$PCAP_OUT" 2>/dev/null || true

if [ ! -s "$PGM_OUT" ]; then
  echo "error: Driver failed to capture image ($PGM_OUT is missing or empty)." >&2
  exit 1
fi

if [ ! -s "$PCAP_OUT" ]; then
  echo "error: PCAP trace is missing or empty ($PCAP_OUT)." >&2
  exit 1
fi

echo ""
echo "==> Executing numerical front-end comparison..."
python3 "$HERE/compare_frontend.py" "$PCAP_OUT" "$PGM_OUT"

