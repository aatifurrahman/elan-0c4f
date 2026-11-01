#!/usr/bin/env python3
"""
Protocol decoder and analyzer for ELAN 04f3:0c4f fingerprint sensor USB traces.
Works with both Linux usbmon (.pcap / .pcapng) and Windows USBPcap (.pcapng) captures.
Usage: python3 experiments/parse_trace.py [experiments/traces/<file>.pcap]
"""
import sys, os, subprocess, re, shutil

TSHARK_BIN = shutil.which("tshark") or (
    r"C:\Program Files\Wireshark\tshark.exe" if os.path.exists(r"C:\Program Files\Wireshark\tshark.exe") else "tshark"
)

KNOWN_COMMANDS = {
    "40 19": "Query Firmware Version",
    "40 21 0a": "Read Register 0x0a",
    "40 21 06": "Read Register 0x06",
    "40 24": "Read Register 0x24",
    "40 31": "LED On / Prepare Prescan",
    "00 0c": "Read Sensor Dimension (Width/Height)",
    "00 09": "Read Raw ADC Frame (80x80 x 2 = 12800 bytes)",
    "40 3f": "Wait for Finger Contact",
    "40 3e": "Poll Finger Status",
    "00 0b": "Set Sensor Idle / Stop Capture",
}

KNOWN_RESPONSES = {
    "55": "Finger Contact Detected (0x55)",
    "aa": "Finger Held / Present (0xaa)",
    "4f 00 4f 00": "Dimension: 80 x 80 pixels (0x4f = 79 index + 1)",
    "01 65": "Firmware Version 1.65",
}

def find_latest_trace():
    traces_dir = os.path.join(os.path.dirname(__file__), "traces")
    if not os.path.isdir(traces_dir):
        return None
    pcap_files = [
        os.path.join(traces_dir, f)
        for f in os.listdir(traces_dir)
        if f.endswith(".pcapng") or f.endswith(".pcap")
    ]
    if not pcap_files:
        return None
    pcap_files.sort(key=os.path.getmtime)
    return pcap_files[-1]

def get_device_address(pcap_path):
    # 1. Search in PCAP for 04f3:0c4f device descriptor
    try:
        out = subprocess.check_output([
            TSHARK_BIN, "-r", pcap_path,
            "-Y", "usb.idVendor == 0x04f3 && usb.idProduct == 0x0c4f",
            "-T", "fields", "-e", "usb.device_address"
        ], stderr=subprocess.DEVNULL).decode().strip()
        addrs = [int(a) for a in out.splitlines() if a.strip().isdigit()]
        if addrs:
            return addrs[0]
    except Exception:
        pass

    # 2. Search in PCAP by 12800-byte frame transfers
    try:
        out = subprocess.check_output([
            TSHARK_BIN, "-r", pcap_path,
            "-Y", "usb.data_len == 12800",
            "-T", "fields", "-e", "usb.device_address"
        ], stderr=subprocess.DEVNULL).decode().strip()
        addrs = [int(a) for a in out.splitlines() if a.strip().isdigit()]
        if addrs:
            return addrs[0]
    except Exception:
        pass

    # 3. Fallback to live system lsusb
    try:
        lsusb_out = subprocess.check_output(["lsusb", "-d", "04f3:0c4f"], stderr=subprocess.DEVNULL).decode()
        m = re.search(r"Device\s+(\d+):", lsusb_out)
        if m:
            return int(m.group(1))
    except Exception:
        pass

    return None

def parse_trace(pcap_path):
    print("=" * 80)
    print(f" ELAN 04f3:0c4f USB Protocol Decoder")
    print(f" Trace File: {pcap_path}")
    print("=" * 80)

    dev_addr = get_device_address(pcap_path)
    if dev_addr is not None:
        filter_expr = f"usb.device_address == {dev_addr}"
        print(f"[*] Target USB Device Address: {dev_addr}")
    else:
        filter_expr = "usb.endpoint_address"
        print("[!] Warning: Could not isolate exact device address; showing all USB endpoints")

    cmd = [
        TSHARK_BIN, "-r", pcap_path,
        "-Y", filter_expr,
        "-T", "fields",
        "-e", "frame.number",
        "-e", "frame.time_relative",
        "-e", "usb.endpoint_address",
        "-e", "usb.urb_type",
        "-e", "usb.data_len",
        "-e", "usb.capdata",
    ]

    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except Exception as e:
        print(f"Error running tshark: {e}")
        return

    lines = proc.stdout.strip().splitlines()
    if not lines or lines == ['']:
        print("No packets found matching filter.")
        return

    records = []
    frames_count = 0
    calibration_frames = 0
    touch_frames = 0
    stages_count = 0
    current_stage_frames = 0
    template_upload_detected = False

    for line in lines:
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        f_num = parts[0]
        time_rel = f"{float(parts[1]):.4f}" if parts[1] else "0.0000"
        ep_raw = parts[2] if len(parts) > 2 else ""
        urb_type = parts[3] if len(parts) > 3 else ""
        data_len = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
        capdata = parts[5] if len(parts) > 5 else ""

        ep_str = ""
        direction = ""
        if ep_raw:
            try:
                ep_val = int(ep_raw, 0)
                ep_str = f"0x{ep_val:02x}"
                direction = "IN" if (ep_val & 0x80) else "OUT"
            except ValueError:
                ep_str = ep_raw

        # In Linux usbmon, URB type is 'S' or 'C'. In Windows USBPcap, packets in trace are completions.
        type_str = "SUBMIT" if urb_type in ("'S'", "S") else ("COMPLETE" if (urb_type in ("'C'", "C") or not urb_type) else urb_type)

        hex_data = ""
        if capdata:
            hex_data = " ".join([capdata[i:i+2] for i in range(0, len(capdata), 2)])

        # Track 12,800-byte raw frames
        if data_len == 12800 and direction == "IN" and type_str == "COMPLETE":
            frames_count += 1
            if stages_count == 0:
                calibration_frames += 1
            else:
                touch_frames += 1
                current_stage_frames += 1

        # Track touch events
        if capdata == "55" and direction == "IN":
            stages_count += 1
            current_stage_frames = 0

        # Check for template upload (any bulk OUT with substantial data > 8 bytes)
        if direction == "OUT" and data_len > 8:
            template_upload_detected = True

        # Annotate description
        annotation = ""
        if hex_data in KNOWN_COMMANDS and direction == "OUT":
            annotation = KNOWN_COMMANDS[hex_data]
        elif hex_data in KNOWN_RESPONSES and direction == "IN":
            annotation = KNOWN_RESPONSES[hex_data]
        elif data_len == 12800 and direction == "IN":
            if stages_count == 0:
                annotation = f"Calibration Frame #{calibration_frames} (12,800 bytes 16-bit ADC)"
            else:
                annotation = f"Touch Frame (Stage {stages_count}, #{current_stage_frames}) (12,800 bytes)"
        elif direction == "OUT" and hex_data.startswith("40 21"):
            annotation = f"Read Register 0x{hex_data.split()[-1]}"

        # Truncate hex representation for readability
        hex_display = hex_data
        if len(hex_data) > 48:
            hex_display = hex_data[:48] + "..."

        if hex_data or (data_len > 0 and type_str == "COMPLETE") or direction == "OUT":
            records.append({
                "num": f_num,
                "time": time_rel,
                "type": type_str,
                "ep": ep_str,
                "dir": direction,
                "len": data_len,
                "hex": hex_display,
                "note": annotation
            })

    # Print Summary Analysis
    print("\n--- Biometric Protocol Summary ---")
    print(f"Total USB Packets Analyzed:    {len(lines)}")
    print(f"Calibration Frames (Pre-touch): {calibration_frames}")
    print(f"Touch Stages / Finger Taps:    {stages_count}")
    print(f"Touch Sensor Frames:           {touch_frames}")
    print(f"Total Raw Frames Ingested:     {frames_count} ({frames_count * 12800:,} bytes)")
    print(f"Template Uploaded to Hardware: {'YES (MoC Mode)' if template_upload_detected else 'NONE (100% Host-Side Matching)'}")
    print("----------------------------------\n")

    print(f"{'#':<6} {'Time(s)':<9} {'Type':<8} {'EP':<6} {'Dir':<4} {'Len':<6} {'Hex Payload':<30} {'Description'}")
    print("-" * 110)
    for r in records:
        print(f"{r['num']:<6} {r['time']:<9} {r['type']:<8} {r['ep']:<6} {r['dir']:<4} {r['len']:<6} {r['hex']:<30} {r['note']}")
    print("-" * 110)

if __name__ == "__main__":
    pcap = sys.argv[1] if len(sys.argv) > 1 else find_latest_trace()
    if not pcap or not os.path.isfile(pcap):
        print("Usage: python3 experiments/parse_trace.py <path_to_trace.pcap>")
        sys.exit(1)
    parse_trace(pcap)
