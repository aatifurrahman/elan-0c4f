#!/usr/bin/env python3
"""
Dataset manager for ELAN 04f3:0c4f experiments.
Manages touches, manifest.json, and ingests pcap/pcapng traces.

Schema:
  experiments/data/<person_id>/<finger>/<session>/touch_NN.npz
  experiments/data/manifest.json

Contents of each touch_NN.npz:
  frames: uint16[K, 80, 80]
  state: uint8[K] (0: air, 1: transition, 2: contact)
  t: float[K]
  pkt: int32[K]
  baseline: uint16[80, 80]
  tap_id: int
  person_id: str
  finger: str
  session: str
  purpose: str ('enroll' | 'probe')
  notes: str
"""

import json
import os
import sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
MANIFEST_PATH = os.path.join(DATA_DIR, "manifest.json")

# Import frame reader functions from extract_frames
sys.path.insert(0, HERE)
from extract_frames import read_frames, air_baseline, classify


def load_manifest():
    if os.path.isfile(MANIFEST_PATH):
        try:
            with open(MANIFEST_PATH, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"[!] Warning: error reading manifest ({e}), initializing empty.", file=sys.stderr)
    return {"version": 1, "touches": []}


def save_manifest(manifest):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)


def ingest_trace(pcap_path, person_id, finger, session, purpose="probe", notes="", driver=""):
    """
    Ingests all taps from a pcap/pcapng capture into experiments/data/.
    Splits into touch_NN.npz for each tap.
    """
    if not os.path.isfile(pcap_path):
        raise FileNotFoundError(f"Trace not found: {pcap_path}")

    got = read_frames(pcap_path)
    if got is None:
        print(f"[!] No frames found in {pcap_path}", file=sys.stderr)
        return []

    frames, tap, t, pkt = got
    base, air = air_baseline(frames)
    state = classify(frames, base, air)

    if driver:
        dest_dir = os.path.join(DATA_DIR, driver, person_id, finger, session)
    else:
        dest_dir = os.path.join(DATA_DIR, person_id, finger, session)
    os.makedirs(dest_dir, exist_ok=True)

    manifest = load_manifest()
    existing_paths = {entry["rel_path"] for entry in manifest["touches"]}

    ingested = []
    taps = sorted(set(tap[tap > 0]))
    if not taps:
        # Fallback if tap wasn't incremented (e.g. single touch without wait_touch marker)
        taps = [0]

    # Determine next touch index in dest_dir so new touches never overwrite existing ones
    existing_touch_files = [f for f in os.listdir(dest_dir) if f.startswith("touch_") and f.endswith(".npz")]
    start_num = 1
    if existing_touch_files:
        nums = []
        for f in existing_touch_files:
            try:
                nums.append(int(f.replace("touch_", "").replace(".npz", "")))
            except ValueError:
                pass
        if nums:
            start_num = max(nums) + 1

    for i, k in enumerate(taps):
        tap_num = start_num + i
        idx = np.where(tap == k)[0] if k > 0 else np.arange(len(frames))
        if len(idx) == 0:
            continue

        touch_file = f"touch_{tap_num:02d}.npz"
        touch_full_path = os.path.join(dest_dir, touch_file)
        rel_path = os.path.relpath(touch_full_path, DATA_DIR)

        # Slice frames for this tap
        k_frames = frames[idx]
        k_state = state[idx]
        k_t = t[idx]
        k_pkt = pkt[idx]

        contact_count = int((k_state == 2).sum())
        transition_count = int((k_state == 1).sum())

        np.savez_compressed(
            touch_full_path,
            frames=k_frames,
            state=k_state,
            t=k_t,
            pkt=k_pkt,
            baseline=base,
            tap_id=k,
            person_id=person_id,
            finger=finger,
            session=session,
            purpose=purpose,
            driver=driver,
            notes=notes,
        )

        entry = {
            "rel_path": rel_path,
            "driver": driver if driver else ("ubuntu/lenovo-tod" if session == "s01_lin" else ("windows/vendor" if session == "s01_win" else "ubuntu/sigfm")),
            "person_id": person_id,
            "finger": finger,
            "session": session,
            "purpose": purpose,
            "tap_id": int(k),
            "total_frames": int(len(idx)),
            "contact_frames": int(contact_count),
            "transition_frames": int(transition_count),
            "notes": str(notes),
            "source_trace": os.path.basename(pcap_path),
        }

        # Update or append
        if rel_path in existing_paths:
            manifest["touches"] = [e if e["rel_path"] != rel_path else entry for e in manifest["touches"]]
        else:
            manifest["touches"].append(entry)
            existing_paths.add(rel_path)

        ingested.append(entry)

    save_manifest(manifest)
    print(f"[*] Ingested {len(ingested)} touches from {os.path.basename(pcap_path)} -> {dest_dir}")
    return ingested


def show_summary():
    manifest = load_manifest()
    touches = manifest.get("touches", [])
    print("=" * 75)
    print(f" ELAN 04f3:0c4f Dataset Summary ({len(touches)} total touches)")
    print("=" * 75)

    if not touches:
        print("Dataset is currently empty. Run ingest to add data.")
        return

    # Count by driver, person, finger, purpose
    drivers = set()
    people = set()
    fingers = set()
    sessions = set()
    driver_classes = {}  # (driver, person, finger) -> {enroll: int, probe: int, usable_touches: int}

    for t in touches:
        d = t.get("driver", "unknown")
        p, f, s, pur = t["person_id"], t["finger"], t["session"], t["purpose"]
        drivers.add(d)
        people.add(p)
        fingers.add(f)
        sessions.add(s)
        key = (d, p, f)
        if key not in driver_classes:
            driver_classes[key] = {"enroll": 0, "probe": 0, "usable_touches": 0}
        driver_classes[key][pur] = driver_classes[key].get(pur, 0) + 1
        if t["contact_frames"] > 0:
            driver_classes[key]["usable_touches"] += 1

    print(f"Drivers:         {len(drivers)} ({', '.join(sorted(drivers))})")
    print(f"Unique Persons:  {len(people)} ({', '.join(sorted(people))})")
    print(f"Unique Fingers:  {len(fingers)} fingers")
    print(f"Unique Sessions: {len(sessions)} ({', '.join(sorted(sessions))})")
    print("-" * 75)
    print(f"{'Driver':<20} {'Person':<8} {'Finger':<24} {'Enroll':<8} {'Probe':<8} {'Usable':<8}")
    print("-" * 75)
    for (d, p, f), cnts in sorted(driver_classes.items()):
        print(f"{d:<20} {p:<8} {f:<24} {cnts['enroll']:<8} {cnts['probe']:<8} {cnts['usable_touches']:<8}")

    print("-" * 75)
    for d in sorted(drivers):
        d_touches = [t for t in touches if t.get("driver") == d]
        d_usable = sum(1 for t in d_touches if t["contact_frames"] > 0)
        d_probes = sum(1 for t in d_touches if t["purpose"] == "probe")
        print(f"Driver [{d}]: {len(d_touches)} touches ({d_usable} usable, {d_probes} probes)")
    print("=" * 75)


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage:")
        print("  python3 dataset.py summary")
        print("  python3 dataset.py ingest <trace.pcap|pcapng> <person_id> <finger> <session> [enroll|probe] [notes] [driver]")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "summary":
        show_summary()
    elif cmd == "ingest":
        if len(sys.argv) < 6:
            print("Usage: python3 dataset.py ingest <trace> <person_id> <finger> <session> [purpose] [notes] [driver]")
            sys.exit(1)
        pcap = sys.argv[2]
        person = sys.argv[3]
        finger = sys.argv[4]
        sess = sys.argv[5]
        purpose = sys.argv[6] if len(sys.argv) > 6 else "probe"
        notes = sys.argv[7] if len(sys.argv) > 7 else ""
        driver = sys.argv[8] if len(sys.argv) > 8 else ""
        ingest_trace(pcap, person, finger, sess, purpose, notes, driver)
        show_summary()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
