# Reverse-Engineering Findings & Experiments: ELAN 04f3:0c4f

This directory contains live USB packet traces, extracted raw biometric frames, protocol decoder tooling, and reverse-engineering findings comparing the **Lenovo ThinkPad Touch-on-Driver (TOD)** driver on Fedora Linux with the **native Windows Hello** biometric driver on Windows 11 for the **ELAN 04f3:0c4f** fingerprint sensor.

---

## 1. Executive Summary & Breakthrough Findings

Historical community efforts categorized `04f3:0c4f` as an ELAN Match-on-Chip (MoC) device (similar to `04f3:0c4c` in `elanmoc2`). Live packet tracing across both operating systems proved this false.

```text
+-------------------------------------------------------------------------------+
|                       ELAN 04f3:0c4f ARCHITECTURE REALITY                     |
+-------------------------------------------------------------------------------+
| 1. Pure Match-on-Host (MoH) Sensor: The chip contains NO on-chip biometric   |
|    matcher, NO biometric template database, and NO secure enclave storage.    |
|    Templates are stored 100% on the host filesystem (/var/lib/fprint/ or      |
|    Windows Biometric Vault).                                                  |
|                                                                               |
| 2. True Die Dimensions: Exactly 80 x 80 pixels (not 96x96). Dimension         |
|    query (00 0c) returns 0x4f 0x00 0x4f 0x00 (0x4f = 79 index + 1 = 80 px).   |
|                                                                               |
| 3. Raw 16-bit ADC Streaming: The hardware is a raw image digitizer. Each      |
|    frame is 80 x 80 x 2 = 12,800 bytes of raw uncompressed 16-bit ADC samples|
|    streamed over bulk Endpoint 0x82 at ~38 FPS (26.1 ms per frame).           |
|                                                                               |
| 4. 1:1 Universal Hardware Commands: Linux TOD, Windows Hello, and upstream    |
|    open-source libfprint (elan.c) use the identical USB control state machine:|
|      40 31 (LED On) -> 40 3f (Wait) -> 55 (Touch) -> 00 09 (Frame) -> 00 0b   |
|                                                                               |
| 5. Root Cause of Open-Source Failure: Stock libfprint uses NIST NBIS          |
|    (bozorth3), which requires >= 6-10 minutiae to build constellation graphs.  |
|    Across 86 dataset touches on this 80x80 sensor, mindtct yields a median of  |
|    only 1.0 minutia (mean 1.19 +/- 1.17, 34.9% zero minutiae, 100% < 6).      |
|    Lenovo's driver succeeds because it bundles a proprietary host-side         |
|    image cross-correlation algorithm (efd_tod), NOT because of on-chip matching|
+-------------------------------------------------------------------------------+
```

---

## 2. Cross-Platform Protocol Verification

| Metric / Parameter | Linux Lenovo TOD (`efd_tod`) | Native Windows Hello (WBF) | Upstream `libfprint` (`elan.c`) |
| :--- | :--- | :--- | :--- |
| **Trace Artifact** | `traces/enroll_20261031_202050.pcap` | `traces/windows/enroll.pcapng` | `experimental/elan_0c4f_opensource.patch` |
| **Matching Location** | **Host CPU** (`CalcuateMatchScore`) | **Host CPU** (`wbmsvc`) | **Host CPU** (NIST NBIS) |
| **Hardware Template Upload** | **0 bytes** | **0 bytes** | **0 bytes** |
| **Sensor Dimensions** | $80 \times 80$ pixels | $80 \times 80$ pixels | $80 \times 80$ pixels (detected) |
| **Frame Payload** | 12,800 bytes (16-bit LE) | 12,800 bytes (16-bit LE) | 12,800 bytes (16-bit LE) |
| **Frame Transfer Rate** | $\sim 28\text{ ms}$ interval | $26.1\text{ ms}$ interval ($\sim 38.3\text{ FPS}$) | Driver polled |
| **Command OUT Endpoint** | `0x01` (Bulk 64B) | `0x01` (Bulk 64B) | `0x01` (`ELAN_EP_CMD_OUT`) |
| **Status IN Endpoint** | `0x83` (Bulk 64B) | `0x83` (Bulk 64B) | `0x83` (`ELAN_EP_CMD_IN`) |
| **Image IN Endpoint** | `0x82` (Bulk 64B) | `0x82` (Bulk 64B) | `0x82` (`ELAN_EP_IMG_IN`) |
| **LED / Prescan Command** | `40 31` | `40 31` | `40 31` (`led_on_cmd`) |
| **Wait for Touch Command** | `40 3f` $\to$ returns `0x55` | `40 3f` $\to$ returns `0x55` | `40 3f` (`pre_scan_cmd`) $\to$ returns `0x55` |
| **Frame Ingest Command** | `00 09` $\to$ 12,800 bytes | `00 09` $\to$ 12,800 bytes | `00 09` (`get_image_cmd`) $\to$ 12,800 bytes |
| **Sleep / Stop Command** | `00 0b` | `00 0b` | `00 0b` (`stop_cmd`) |

---

## 3. Sensor Frame Characteristics & Dynamic Range

Each 12,800-byte frame represents an $80 \times 80$ grid of 16-bit unsigned integers (`<6400H`):
- **Air / Baseline Noise**: $\sim 4,400 - 4,800$ ADC counts.
- **Finger Ridge Contact**: $\sim 7,500 - 10,400$ ADC counts.
- **Dynamic Contrast Range**: $\approx 3,000 - 5,600$ counts above baseline during firm contact.

Normalization to standard 8-bit grayscale ($0 - 255$) is performed by subtracting the baseline calibration frame:
$$\text{Pixel}_{\text{norm}} = \frac{\max(\text{Pixel}_{\text{touch}} - \text{Baseline}, 0)}{\text{DynamicRange}} \times 255$$

Raw sensor frames are **not committed as static binary blobs** to avoid repository bloat; instead, they are generated on demand from the captured traces using `extract_frames.py`:
- `python extract_frames.py traces/windows/enroll.pcapng` $\to$ Generates all 301 frames into `traces/windows/enroll_frames/`
- `python extract_frames.py traces/enroll_20261031_202050.pcap` $\to$ Generates all 46 frames into `traces/enroll_20261031_202050_frames/`

---

## 4. Repository Tooling

### A. Protocol Decoder (`parse_trace.py`)
Parses PCAP/PCAPNG files, isolates the ELAN device address, decodes URB transactions, tallies touch taps, and checks hardware command compliance:
```bash
# Analyze Windows trace:
python parse_trace.py traces/windows/enroll.pcapng

# Analyze Linux TOD trace:
python parse_trace.py traces/enroll_20261031_202050.pcap
```

### B. Raw Frame Extractor & ASCII Visualizer (`extract_frames.py`)
Unpacks 12,800-byte transfers, normalizes 16-bit ADC samples to 8-bit grayscale, exports `.pgm` images, and prints terminal ASCII ridge art:
```bash
python extract_frames.py traces/windows/enroll.pcapng
```

### C. Live Linux Protocol Tracer (`trace.sh`)
Automates kernel `usbmon` packet capture, `fprintd` execution, and packet decoding on Linux:
```bash
sudo ./trace.sh enroll
sudo ./trace.sh verify
```

---

## 5. Roadmap for 100% Open-Source Linux Support

Because the hardware commands in upstream `libfprint/drivers/elan.c` already match the device 1:1, full open-source support without Lenovo proprietary binaries requires addressing the $80 \times 80$ small-area sensor limitation:

1. **Path 1: Spectral Phase Correlation (SigFM / MR !530)**:
   - Upstream `libfprint` Merge Request `!530` introduces SigFM (Signature Fingerprint Matcher).
   - Operates directly in the frequency domain (2D Fourier phase correlation) on raw grayscale frames.
   - Does not rely on minutiae points; designed specifically for small-area sensors ($\le 96 \times 96$).

2. **Path 2: Multi-Frame Image Stitching**:
   - As observed in Windows Hello (which streams 8–12 continuous frames per tap at 38 FPS), assembling consecutive overlapping frames into a composite $160 \times 160$ synthetic image provides $\ge 20$ minutiae, satisfying NIST NBIS requirements.
