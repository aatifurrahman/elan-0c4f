#!/usr/bin/env bash
# USB traffic tracer for ELAN 04f3:0c4f fingerprint sensor
# Usage: ./experiments/trace.sh [enroll|verify] [finger_name] [person_id] [session_id] [notes]
# Example: ./experiments/trace.sh enroll right-index-finger p01 s01 "normal"
set -euo pipefail

MODE="${1:-verify}"
FINGER="${2:-right-index-finger}"
PERSON="${3:-p01}"
SESSION="${4:-s01}"
NOTES="${5:-normal}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRACES_DIR="$HERE/traces"
mkdir -p "$TRACES_DIR"

DEV_INFO=$(lsusb -d 04f3:0c4f || true)
if [ -z "$DEV_INFO" ]; then
  echo "error: ELAN 04f3:0c4f not detected on USB" >&2
  exit 1
fi

BUS=$(echo "$DEV_INFO" | awk '{print $2}' | sed 's/^0*//')
DEV=$(echo "$DEV_INFO" | awk '{print $4}' | tr -d ':' | sed 's/^0*//')
IFACE="usbmon${BUS}"
TS=$(date +%Y%m%d_%H%M%S)
PCAP_FILE="$TRACES_DIR/${MODE}_${TS}.pcap"
LOG_FILE="$TRACES_DIR/${MODE}_${TS}_capture.log"

echo "=========================================================="
echo " ELAN 04f3:0c4f Protocol Tracer (Mode: $MODE)"
echo " Person: $PERSON | Finger: $FINGER | Session: $SESSION"
echo " USB Bus: $BUS, Device: $DEV (Interface: $IFACE)"
echo " PCAP: $PCAP_FILE"
echo "=========================================================="

# Ensure sudo credentials are ready
sudo -v

echo "==> Starting packet capture on $IFACE..."
sudo tcpdump -i "$IFACE" -w "$PCAP_FILE" -s 0 -U > "$LOG_FILE" 2>&1 &
DUMP_PID=$!

sleep 1.0

if ! kill -0 "$DUMP_PID" 2>/dev/null; then
  echo "error: tcpdump failed to start. Log output:" >&2
  cat "$LOG_FILE" >&2
  exit 1
fi

echo "==> Running: fprintd-$MODE ($FINGER)"
if [ "$MODE" = "enroll" ]; then
  echo "==> Please place and lift your finger on the sensor repeatedly when prompted..."
  echo "----------------------------------------------------------"
  fprintd-delete "$USER" -f "$FINGER" 2>/dev/null || true
  fprintd-enroll -f "$FINGER" || true
else
  echo "==> PLACE YOUR FINGER ON THE SENSOR NOW..."
  echo "----------------------------------------------------------"
  fprintd-verify -f "$FINGER" || true
fi
echo "----------------------------------------------------------"

sleep 1.0

echo "==> Stopping capture..."
sudo kill -INT "$DUMP_PID" 2>/dev/null || true
wait "$DUMP_PID" 2>/dev/null || true
sudo chown "$USER:" "$PCAP_FILE" "$LOG_FILE" 2>/dev/null || true

if [ ! -s "$PCAP_FILE" ]; then
  echo "error: PCAP file is empty. Capture log:" >&2
  cat "$LOG_FILE" >&2
  exit 1
fi

echo "==> Parsing protocol..."
python3 "$HERE/parse_trace.py" "$PCAP_FILE" || true

echo "==> Extracting frames..."
python3 "$HERE/extract_frames.py" "$PCAP_FILE" || true

echo "==> Ingesting into dataset..."
PURPOSE="probe"
[ "$MODE" = "enroll" ] && PURPOSE="enroll"
python3 "$HERE/dataset.py" ingest "$PCAP_FILE" "$PERSON" "$FINGER" "$SESSION" "$PURPOSE" "$NOTES" || true

echo ""
echo "Done! Capture saved and ingested into experiments/data/."
