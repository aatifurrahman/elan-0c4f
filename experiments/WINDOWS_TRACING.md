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
> [!NOTE]
> Root hub numbering can alternate between `USBPcap1` and `USBPcap2` depending on boot enumeration order and attached external peripherals. Test with a quick 2-second capture or check `USBPcapCMD.exe -I` to verify which hub has the active ELAN device.

---

## 3. Capturing Traces

> [!WARNING]
> **Wireshark Display Filter Caution**: Do NOT set `usb.idVendor == 0x04f3` during live capture! In USB architecture, individual URB bulk/interrupt packets (finger scans and frame transfers) do **not** carry vendor ID headers—only the single initial descriptor packet does. Filtering by `usb.idVendor` will hide all 80x80 sensor data packets. Leave the filter bar **empty** or filter strictly by `usb.device_address`.

### Method A: Direct Command Line (Fastest & Most Reliable)
Run in PowerShell (e.g. on `USBPcap1`):
```powershell
& "C:\Program Files\Wireshark\tshark.exe" -i "\\.\USBPcap1" -w "capture.pcapng"
```
1. Lock your session (**Win + L**).
2. Touch the sensor to unlock.
3. Switch back to PowerShell and press **Ctrl + C**.

---

### Method B: Using Wireshark GUI

### Trace 1: Windows Hello Verification (Sign-in / Unlock)
1. Open **Wireshark as Administrator** (Right click shortcut -> "Run as administrator").
2. Double-click the active `USBPcap` interface (`USBPcap1` or `USBPcap2`).
3. Leave the display filter bar **blank** (or filter by `usb.device_address`).
4. Lock your Windows session (**Win + L**).
5. Touch the fingerprint reader to unlock Windows.
6. Once unlocked, switch back to Wireshark and click the red **Stop Capture** button.
7. Go to **File > Save As...** and save as:
   `capture_verify.pcapng`

### Trace 2: Windows Hello Enrollment
1. In Wireshark (running as Administrator), click the blue shark fin (**Start Capture**), discarding previous unsaved packets if prompted.
2. Open Windows **Settings > Accounts > Sign-in options > Fingerprint recognition (Windows Hello)**.
3. Click **Set up** (or **Add another finger**).
4. Follow the Windows Hello wizard: place, lift, and tilt your finger repeatedly until Windows says enrollment is complete.
5. In Wireshark, click **Stop Capture**.
6. Go to **File > Save As...** and save as:
   `capture_enrollment.pcapng`

---

## 4. Analyzing Traces & Extracting Frames

You can run the python analyzer and frame extractor directly on Windows (PowerShell) or Linux/WSL:

### Run Protocol Decoder
```bash
# Windows PowerShell:
python experiments/parse_trace.py <path_to_trace>.pcapng

# Linux / WSL:
python3 experiments/parse_trace.py <path_to_trace>.pcapng
```
The parser isolates the ELAN device address, decodes URB submissions/completions, tallies touch taps, and decodes frame transfers.

### Extract Raw Frames to Grayscale Images
```bash
# Windows PowerShell:
python experiments/extract_frames.py <path_to_trace>.pcapng

# Linux / WSL:
python3 experiments/extract_frames.py <path_to_trace>.pcapng
```
This extracts all raw 16-bit ADC samples into normalized 8-bit Netpbm `.pgm` grayscale images in `<trace_name>_frames/` and renders an ASCII art preview of fingerprint ridges in the terminal.

---

## 5. Architectural Verification Findings

Analysis of native Windows Hello driver communication confirms:
- **100% Match-on-Host Architecture**: Windows Hello performs all biometric template extraction and matching on the host CPU. Zero template bytes or minutiae are ever written to or stored on the ELAN sensor hardware.
- **Hardware State Commands**: Windows Hello uses `40 31` (LED On), `40 3f` (Wait for contact), `0x55` (Contact detected), `00 09` (Stream frame), and `00 0b` (Stop/Sleep)—matching Linux Lenovo TOD traces and upstream `libfprint` exactly.
- **Frame Cadence**: The sensor streams raw $80 \times 80$ 16-bit ADC frames continuously at its maximum hardware transfer speed of $\sim 26.2\text{ ms}$ per frame ($\sim 38\text{ fps}$) while physical contact is maintained.
