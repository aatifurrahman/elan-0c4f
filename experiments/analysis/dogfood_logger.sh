#!/usr/bin/env bash
# E2: Opt-In Dogfood Logger Control Script
# Usage:
#   ./dogfood_logger.sh start      Start background monitor
#   ./dogfood_logger.sh stop       Stop background monitor
#   ./dogfood_logger.sh status     Check daemon status and event count
#   ./dogfood_logger.sh summary    Show statistics from logged events
#   ./dogfood_logger.sh enable-debug  Instructions to configure system fprintd debug

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXP_DIR="$(dirname "$HERE")"
PID_FILE="$HERE/.dogfood_logger.pid"
LOG_CSV="$EXP_DIR/dogfood_log.csv"
PY_SCRIPT="$HERE/dogfood_logger.py"

case "${1:-help}" in
  start)
    existing_pid=$(pgrep -f "dogfood_logger.py --action monitor" || true)
    if [ -n "$existing_pid" ]; then
      echo "Dogfood logger is already running (PID: $existing_pid)."
      echo "$existing_pid" > "$PID_FILE"
      exit 0
    fi
    echo "Starting dogfood logger in background..."
    setsid -f python3 "$PY_SCRIPT" --action monitor --csv "$LOG_CSV" </dev/null >> "$HERE/dogfood_daemon.log" 2>&1
    sleep 0.5
    new_pid=$(pgrep -f "dogfood_logger.py --action monitor" || true)
    if [ -n "$new_pid" ]; then
      echo "$new_pid" > "$PID_FILE"
      echo "Dogfood logger started successfully (PID: $new_pid)."
      echo "Logs appending to: $LOG_CSV"
    else
      echo "Failed to start dogfood logger." >&2
      exit 1
    fi
    ;;
  stop)
    running_pids=$(pgrep -f "dogfood_logger.py --action monitor" || true)
    if [ -n "$running_pids" ]; then
      echo "Stopping dogfood logger (PID(s): $running_pids)..."
      kill $running_pids 2>/dev/null || true
      rm -f "$PID_FILE"
      echo "Stopped."
      exit 0
    fi
    rm -f "$PID_FILE"
    echo "Dogfood logger is not running."
    ;;
  status)
    running_pids=$(pgrep -f "dogfood_logger.py --action monitor" || true)
    if [ -n "$running_pids" ]; then
      echo "Status: RUNNING (PID(s): $running_pids)"
    else
      echo "Status: STOPPED"
    fi
    if [ -f "$LOG_CSV" ]; then
      lines=$(wc -l < "$LOG_CSV")
      entries=$((lines - 1))
      echo "Logged unlock attempts: $entries in $LOG_CSV"
    else
      echo "Log file: not yet created ($LOG_CSV)"
    fi
    ;;
  summary)
    python3 "$PY_SCRIPT" --action summary --csv "$LOG_CSV"
    ;;
  enable-debug)
    echo "=========================================================="
    echo " E2 Opt-In: Enable Debug Messages in System fprintd"
    echo "=========================================================="
    echo "To capture SIGFM telemetry during daily GDM lockscreen unlocks,"
    echo "fprintd must run with G_MESSAGES_DEBUG=all."
    echo ""
    echo "Run the following command to add a systemd override:"
    echo "  sudo mkdir -p /etc/systemd/system/fprintd.service.d"
    echo "  sudo tee /etc/systemd/system/fprintd.service.d/override.conf <<'EOF'"
    echo "[Service]"
    echo "Environment=\"G_MESSAGES_DEBUG=all\""
    echo "EOF"
    echo "  sudo systemctl daemon-reload"
    echo "  sudo systemctl restart fprintd"
    echo "=========================================================="
    ;;
  *)
    echo "Usage: $0 {start|stop|status|summary|enable-debug}"
    exit 1
    ;;
esac
