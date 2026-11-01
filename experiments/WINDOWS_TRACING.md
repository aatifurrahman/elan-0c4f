# Capturing Windows Native USB Traces for ELAN 04f3:0c4f

This guide outlines how to capture native Windows Hello fingerprint driver USB traffic for the **ELAN 04f3:0c4f** sensor using Wireshark and USBPcap. Comparing Windows native USB traces against Linux Lenovo TOD traces allows us to confirm whether the initialization registers, frame rates, and touch polling sequences are identical.

---

## 1. Prerequisites (Windows)

1. Download and install **Wireshark for Windows**:
   - URL: [https://www.wireshark.org/download.html](https://www.wireshark.org/download.html)
   - **Crucial**: During installation, ensure the **Install USBPcap** checkbox is **checked**.
2. **Reboot Windows** after installation so the USBPcap filter driver is properly loaded by Windows kernel.
3. > [!IMPORTANT]
   > **Run as Administrator**: Wireshark and `USBPcapCMD.exe` **must** be launched as Administrator. Opening USBPcap driver handles (`\\.\USBPcap1`, `\\.\USBPcap2`) requires elevated administrative privileges. Without elevation, Windows rejects device access with `ERROR_ACCESS_DENIED` (error code 5), causing Wireshark or `USBPcapCMD` to close or crash abruptly.

---

## 2. Identify the USBPcap Interface

Wireshark numbers USB controllers as `USBPcap1`, `USBPcap2`, etc. To find which one ELAN `04f3:0c4f` is attached to:

### Method A: Using `USBPcapCMD.exe` (Quickest)
1. Open Windows Command Prompt (`cmd.exe`) or PowerShell **as Administrator**.
2. Run:
   ```cmd
   "C:\Program Files\USBPcap\USBPcapCMD.exe"
   ```
3. It will display a list of USB Root Hubs and all connected devices.
4. Locate the entry for **ELAN:Fingerprint** (Vendor `04f3`, Product `0c4f`).
5. Note the Control Device number (e.g. `\\.\USBPcap1` or `\\.\USBPcap2`).

---

## 3. Capturing Traces

### Trace 1: Windows Hello Verification (Sign-in / Unlock)
1. Open **Wireshark as Administrator** (Right click shortcut -> "Run as administrator").
2. Double-click the `USBPcap` interface identified above to start capturing.
3. In the Wireshark display filter bar at the top, enter:
   ```text
   usb.idVendor == 0x04f3 && usb.idProduct == 0x0c4f
   ```
4. Lock your Windows session (**Win + L**).
5. Touch the fingerprint reader to unlock Windows.
6. Once unlocked, switch back to Wireshark and click the red **Stop Capture** button.
7. Go to **File > Save As...** and save as:
   `windows_verify.pcapng`

### Trace 2: Windows Hello Enrollment
1. In Wireshark (running as Administrator), click the blue shark fin (**Start Capture**), discarding previous unsaved packets if prompted.
2. Open Windows **Settings > Accounts > Sign-in options > Fingerprint recognition (Windows Hello)**.
3. Click **Set up** (or **Add another finger**).
4. Follow the Windows Hello wizard: place, lift, and tilt your finger repeatedly until Windows says enrollment is complete.
5. In Wireshark, click **Stop Capture**.
6. Go to **File > Save As...** and save as:
   `experiments/traces/windows/enroll.pcapng`

---

## 4. Analyzing Traces & Extracting Frames

You can run the python analyzer and frame extractor directly on Windows (PowerShell) or Linux/WSL:

### Run Protocol Decoder
```bash
# Windows PowerShell:
python experiments/parse_trace.py experiments/traces/windows/enroll.pcapng

# Linux / WSL:
python3 experiments/parse_trace.py experiments/traces/windows/enroll.pcapng
```
The parser isolates the ELAN device address, decodes URB submissions/completions, tallies touch taps, and decodes frame transfers.

### Extract Raw Frames to Grayscale Images
```bash
# Windows PowerShell:
python experiments/extract_frames.py experiments/traces/windows/enroll.pcapng

# Linux / WSL:
python3 experiments/extract_frames.py experiments/traces/windows/enroll.pcapng
```
This extracts all raw 16-bit ADC samples into normalized 8-bit Netpbm `.pgm` grayscale images in `experiments/traces/windows/<trace_name>_frames/` and renders an ASCII art preview of fingerprint ridges in the terminal.

---

## 5. Verified Capture Results (`enroll.pcapng`)

A complete Windows Hello enrollment session has been captured and validated:
- **Trace Location**: [`experiments/traces/windows/enroll.pcapng`](file:///D:/elan-0c4f/experiments/traces/windows/enroll.pcapng) (3.9 MB)
- **Extracted Frames**: 301 `.pgm` images (dynamically generated into `experiments/traces/windows/enroll_frames/` via `extract_frames.py`)
- **Packets Analyzed**: 1,356
- **Touch Stages**: 24 taps
- **Raw Sensor Frames**: 301 frames ($3,852,800$ bytes of raw $80 \times 80$ 16-bit ADC data)
- **Hardware Template Upload**: **0 bytes (100% Match-on-Host)**
- **Hardware State Commands**: Windows Hello uses `40 31` (LED On), `40 3f` (Wait for contact), `0x55` (Contact detected), `00 09` (Stream frame), and `00 0b` (Stop/Sleep)—matching Linux Lenovo TOD traces and upstream `libfprint` exactly.
