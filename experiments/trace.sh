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
DRIVER="${6:-auto}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Detect driver if set to auto
if [ "$DRIVER" = "auto" ] || [ -z "$DRIVER" ]; then
  ACTIVE_LIB=$(ldconfig -p 2>/dev/null | grep 'libfprint-2.so.2 ' | head -n 1 | awk '{print $NF}' || true)
  if [[ "$ACTIVE_LIB" == *"/usr/local/"* ]]; then
    DRIVER="ubuntu/sigfm"
  else
    DRIVER="ubuntu/lenovo-tod"
  fi
fi

TRACES_DIR="$HERE/traces/$DRIVER"
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
echo " Driver: $DRIVER (Active: ${ACTIVE_LIB:-custom})"
echo " Person: $PERSON | Finger: $FINGER | Session: $SESSION"
echo " USB Bus: $BUS, Device: $DEV (Interface: $IFACE)"
echo " PCAP: $PCAP_FILE"
echo "=========================================================="

# Ensure sudo credentials are ready
sudo -v

# Ensure usbmon kernel module is loaded
if ! lsmod | grep -q "^usbmon\b"; then
  echo "==> Loading usbmon kernel module..."
  sudo modprobe usbmon
fi

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
set +m 2>/dev/null || true
TCP_PID=$(pgrep -P "$DUMP_PID" -x tcpdump 2>/dev/null || true)
if [ -n "$TCP_PID" ]; then
  sudo kill -INT "$TCP_PID" 2>/dev/null || true
fi
sudo kill -INT "$DUMP_PID" 2>/dev/null || true

for ((w=0; w<15; w++)); do
  kill -0 "$DUMP_PID" 2>/dev/null || break
  sleep 0.1
done

if kill -0 "$DUMP_PID" 2>/dev/null; then
  if [ -n "$TCP_PID" ]; then
    sudo kill -9 "$TCP_PID" 2>/dev/null || true
  fi
  sudo kill -9 "$DUMP_PID" 2>/dev/null || true
fi
wait "$DUMP_PID" 2>/dev/null || true
sudo chown "$USER:" "$PCAP_FILE" "$LOG_FILE" 2>/dev/null || true
stty sane 2>/dev/null || true

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
python3 "$HERE/dataset.py" ingest "$PCAP_FILE" "$PERSON" "$FINGER" "$SESSION" "$PURPOSE" "$NOTES" "$DRIVER" || true

echo ""
echo "Done! Capture saved and ingested into experiments/data/."
