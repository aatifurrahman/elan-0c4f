#!/usr/bin/env bash
# WP6 / Rev3 Work Package E: Structured Live Verification & Telemetry Runner
# Wraps wp6_live_runner.py for interactive live evaluation on hardware.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXP_DIR="$(dirname "$HERE")"
PY_RUNNER="$HERE/wp6_live_runner.py"

case "${1:-help}" in
  block)
    # e.g.: ./wp6_live_runner.sh block 1 20 7
    local_block="${2:-1}"
    local_count="${3:-20}"
    local_finger="${4:-7}"
    python3 "$PY_RUNNER" --mode genuine --block "$local_block" --count "$local_count" --finger "$local_finger"
    ;;
  impostor)
    # e.g.: ./wp6_live_runner.sh impostor 30 7
    local_count="${2:-30}"
    local_finger="${3:-7}"
    python3 "$PY_RUNNER" --mode impostor --count "$local_count" --finger "$local_finger"
    ;;
  unlock-events)
    # e.g.: ./wp6_live_runner.sh unlock-events 50 7
    local_events="${2:-50}"
    local_finger="${3:-7}"
    python3 "$PY_RUNNER" --mode unlock-events --events "$local_events" --finger "$local_finger"
    ;;
  analyze)
    python3 "$PY_RUNNER" --mode analyze
    ;;
  run-full-suite)
    local_finger="${2:-7}"
    echo "=========================================================="
    echo " Rev3 Work Package E: Full Live Evidence Suite"
    echo " Finger: $local_finger"
    echo " Sequence: Block 1 (20) -> Impostor (30) -> Unlock Events (50)"
    echo "=========================================================="
    echo ""
    echo "--- Step 1: Genuine Block 1 (20 Touches) ---"
    python3 "$PY_RUNNER" --mode genuine --block 1 --count 20 --finger "$local_finger"
    echo ""
    echo "Please prepare UN-ENROLLED fingers for the impostor trials."
    read -r -p "Press [ENTER] to begin Impostor Series (30 Touches)..." _
    python3 "$PY_RUNNER" --mode impostor --count 30 --finger "$local_finger"
    echo ""
    echo "Please prepare enrolled finger for Real Unlock Events simulation."
    read -r -p "Press [ENTER] to begin Real Unlock Events (50 Events, up to 3 tries/event)..." _
    python3 "$PY_RUNNER" --mode unlock-events --events 50 --finger "$local_finger"
    echo ""
    python3 "$PY_RUNNER" --mode analyze
    ;;
  *)
    echo "Usage: $0 <command> [options]"
    echo ""
    echo "Commands:"
    echo "  block <block_id> [count=20] [finger=7]  Run genuine touch block (Block 1, 2, or 3)"
    echo "  impostor [count=30] [finger=7]          Run impostor series with un-enrolled fingers"
    echo "  unlock-events [events=50] [finger=7]    Simulate real multi-try unlock events (measured 3-try rate)"
    echo "  run-full-suite [finger=7]               Run complete E1 live protocol"
    echo "  analyze                                 Display comprehensive statistical analysis of recorded results"
    exit 1
    ;;
esac
