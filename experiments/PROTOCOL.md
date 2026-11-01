# ELAN 04f3:0c4f Protocol & Reverse-Engineering Findings

This document records the hardware characteristics, USB protocol transactions, and findings reverse-engineered from live USB packet traces (`usbmon`) using the official Lenovo Touch-on-Driver (TOD) driver on Fedora Linux.

---

## 1. Hardware Architecture

- **USB ID**: `04f3:0c4f` Elan Microelectronics Corp. ELAN:Fingerprint
- **bcdDevice**: `1.65`
- **Physical Sensor Die**: $80 \times 80$ pixels (reported via register `0x0c` as `0x4f 0x00 0x4f 0x00`)
- **Data Depth**: 16-bit raw ADC pixel values ($80 \times 80 \times 2 = \mathbf{12,800\text{ bytes}}$ per frame)
- **ADC Value Dynamics**:
  - Baseline Air/Idle: ~4,400 – 4,800 ADC counts
  - Ridge Contact: ~7,500 – 10,400 ADC counts

### USB Endpoints (`lsusb -v`)
```text
Endpoint 1 OUT (0x01) - Bulk 64 bytes (Command Submission)
Endpoint 1 IN  (0x81) - Bulk 64 bytes
Endpoint 2 IN  (0x82) - Bulk 64 bytes (High-Speed Raw Frame Ingest)
Endpoint 3 OUT (0x03) - Bulk 64 bytes
Endpoint 3 IN  (0x83) - Bulk 64 bytes (Command Responses & Event Notifications)
```
*(Notice: Endpoint 4 (`0x84`) does **not** physically exist on this chip, confirming why `elanmoc2` timed out).*

---

## 2. Key Architectural Discovery: Not Match-on-Chip (MoC)

Community efforts previously categorized `04f3:0c4f` as an ELAN Match-on-Chip device (like `04f3:0c4c` in `elanmoc2`).

Live USB tracing of successful authentication and enrollment proved this false:
1. **Templates stored on Host Filesystem**: Enrolled fingerprints are saved as standard Linux files under `/var/lib/fprint/<user>/efd_tod/efd_tod/`:
   - Finger 7 (`right-index-finger`): $52\text{ KB}$ template blob
   - Finger 8 (`right-middle-finger`): $47\text{ KB}$ template blob
   No biometric database or flash storage exists on the chip.
2. **No templates are sent to the chip**: During verification or enrollment, zero bytes of template or minutiae data are written to the USB device.
3. **No match tokens are received from the chip**: The chip never reports `MATCH` or `NO_MATCH`.
4. **The sensor streams raw images**: The hardware sends raw 16-bit ADC frames ($12,800\text{ bytes}$ each) directly to host memory over EP `0x82`.
5. **Matching happens on the Host CPU**: Lenovo's proprietary TOD binary (`libfprint-2-tod1-elan.so`) bundles ELAN's proprietary host-side image normalization and matcher (`efd_img_normalize_16to8`, `CalcuateMatchScore`).

---

## 3. Command & Register Reference

| Command (Hex) | Direction | Endpoint | Description | Expected Response |
|---|---|---|---|---|
| `40 19` | OUT | `0x01` | Query Firmware Version | `01 65` (FW 1.65) on `0x83` |
| `40 21 <reg>` | OUT | `0x01` | Read Register `<reg>` | 1 byte on `0x83` (e.g. reg `0x0a` $\to$ `0x10`) |
| `40 24` | OUT | `0x01` | Read Calibration Status | 2 bytes on `0x83` (`12 79`) |
| `00 0c` | OUT | `0x01` | Read Sensor Dimensions | `4f 00 4f 00` on `0x83` ($80 \times 80$ px) |
| `40 31` | OUT | `0x01` | Power Illumination LED / Prepare Scan | No payload response (`SKIP_READ`) |
| `40 3f` | OUT | `0x01` | Wait for Finger Touch | `0x55` on EP `0x83` when touched |
| `00 09` | OUT | `0x01` | Ingest Raw ADC Frame | 12,800 bytes on EP `0x82` |
| `40 3e` | OUT | `0x01` | Poll Finger Presence | `0xaa` on EP `0x83` if finger still held |
| `00 0b` | OUT | `0x01` | Stop Sensor / Sleep Mode | Sensor ceases streaming / idle |

---

## 4. Verification Protocol Trace (`verify_20261031_200158.pcap`)

```text
Sequence Breakdown:
1. Handshake: Driver queries FW version (0x40 0x19 -> 1.65) and dimension (0x00 0x0c -> 80x80).
2. Background Frame: Driver reads 12,800 bytes background/noise frame before finger touches.
3. Wait for Touch: Driver sends 0x40 0x3f. Sensor holds EP 0x83 until finger makes contact (0x55).
4. Frame Streaming: Sensor transfers 4 consecutive 12,800-byte frames (frames #1, #2, #3, #4) on EP 0x82.
5. Idle: Driver issues 0x00 0x0b to park sensor. Host CPU executes CalcuateMatchScore against /var/lib/fprint.
```

| Packet | Type | EP | Dir | Len | Payload | Description |
|---|---|---|---|---|---|---|
| `66` / `69` | Bulk | `0x01` / `0x83` | OUT / IN | 2 / 2 | `40 19` $\to$ `01 65` | Query FW version (`1.65`) |
| `70` / `73` | Bulk | `0x01` / `0x83` | OUT / IN | 3 / 1 | `40 21 0a` $\to$ `10` | Read register `0x0a` |
| `74` / `77` | Bulk | `0x01` / `0x83` | OUT / IN | 2 / 4 | `00 0c` $\to$ `4f 00 4f 00` | Read dimension (`80x80`) |
| `78` / `81` | Bulk | `0x01` / `0x82` | OUT / IN | 2 / 12800 | `00 09` $\to$ `2e 13 f7 12...` | Calibration / background frame |
| `82` / `85` | Bulk | `0x01` / `0x83` | OUT / IN | 3 / 1 | `40 21 06` $\to$ `9d` | Read register `0x06` |
| `86` / `89` | Bulk | `0x01` / `0x83` | OUT / IN | 2 / 2 | `40 24` $\to$ `12 79` | Read register `0x24` |
| `90` / `102` | Bulk | `0x01` / `0x83` | OUT / IN | 2 / 1 | `40 3f` $\to$ `55` | Wait for finger (`0x55` = contact) |
| `103` / `106` | Bulk | `0x01` / `0x82` | OUT / IN | 2 / 12800 | `00 09` $\to$ `16 14 0a 14...` | Live touch frame 1 |
| `107` / `110` | Bulk | `0x01` / `0x82` | OUT / IN | 2 / 12800 | `00 09` $\to$ `f0 1b 6d 1d...` | Live touch frame 2 |
| `111` / `114` | Bulk | `0x01` / `0x83` | OUT / IN | 2 / 1 | `40 3e` $\to$ `aa` | Poll status (`0xaa` = finger held) |
| `115` / `118` | Bulk | `0x01` / `0x82` | OUT / IN | 2 / 12800 | `00 09` $\to$ `c7 15 80 15...` | Live touch frame 3 |
| `119` / `122` | Bulk | `0x01` / `0x83` | OUT / IN | 2 / 1 | `40 3e` $\to$ `aa` | Poll status (`0xaa` = finger held) |
| `123` / `126` | Bulk | `0x01` / `0x82` | OUT / IN | 2 / 12800 | `00 09` $\to$ `2b 13 0c 13...` | Live touch frame 4 |
| `127` / `128` | Bulk | `0x01` / -- | OUT | 2 | `00 0b` | Stop capture / sensor idle |

---

## 5. Enrollment Protocol Trace (`enroll_20261031_202050.pcap`)

- **Total Packets**: 366
- **Calibration Frames**: 1 baseline frame (Pkt 94, 12,800 bytes, avg ADC: 4757.5)
- **Touch Stages (Finger Placements)**: 14 stages
- **Total Touch Frames Ingested**: 45 frames (each 12,800 bytes)
- **Total Raw Data Transferred**: 46 frames = 588,800 bytes
- **Hardware Template Upload**: **0 bytes** (100% Host-Side Matching)

### Stage-by-Stage Frame Breakdown
| Stage | Start Packet | Frame Count | Packets Ingested | Status |
|---|---|---|---|---|
| Calibration | `79` | 1 | `94` | Baseline reference |
| Stage 1 | `106` | 5 | `110`, `114`, `122`, `130`, `136` | `enroll-stage-passed` |
| Stage 2 | `148` | 4 | `152`, `156`, `164`, `172` | `enroll-stage-passed` |
| Stage 3 | `176` | 4 | `180`, `184`, `192`, `200` | `enroll-stage-passed` |
| Stage 4 | `204` | 4 | `208`, `212`, `220`, `228` | `enroll-stage-passed` |
| Stage 5 | `232` | 3 | `236`, `240`, `248` | `enroll-stage-passed` |
| Stage 6 | `252` | 2 | `256`, `264` | `enroll-stage-passed` |
| Stage 7 | `268` | 2 | `272`, `280` | `enroll-stage-passed` |
| Stage 8 | `284` | 2 | `288`, `296` | `enroll-stage-passed` |
| Stage 9 | `300` | 4 | `304`, `308`, `312`, `320` | `enroll-retry-scan` |
| Stage 10 | `324` | 2 | `328`, `336` | `enroll-stage-passed` |
| Stage 11 | `340` | 3 | `344`, `348`, `356` | `enroll-stage-passed` |
| Stage 12 | `360` | 3 | `364`, `368`, `376` | `enroll-stage-passed` |
| Stage 13 | `380` | 3 | `384`, `388`, `396` | `enroll-stage-passed` |
| Stage 14 | `400` | 4 | `404`, `408`, `416`, `424` | `enroll-completed` |
| Completion | `425` | -- | `425` (`00 0b`) | Sensor Idle. Template written to `/var/lib/fprint/aatif/efd_tod/efd_tod/8` |

---

## 6. Windows Hello Native Enrollment Trace (`windows/enroll.pcapng`)

Captured using Wireshark & USBPcap with Administrator privileges during a native Windows Hello fingerprint enrollment session:
- **Trace Path**: `experiments/traces/windows/enroll.pcapng`
- **File Size**: $3,942,208\text{ bytes}$
- **Total USB Packets**: 1,356
- **Touch Stages (Finger Placements)**: 24 distinct taps across the Windows Hello enrollment wizard
- **Total Raw ADC Frames**: 301 frames ($3,852,800\text{ bytes}$)
- **Frame Ingest Timing**: Exactly $26.1\text{ ms}$ per 12,800-byte frame transfer on EP `0x82` ($\sim 38.3\text{ FPS}$ streaming while finger is held)
- **Sensor Endpoints**:
  - `0x01` OUT: Bulk Command Submissions (64-byte max packet size)
  - `0x83` IN: Bulk/Interrupt Status (`0x55` Contact)
  - `0x82` IN: Bulk Image Transfer ($12,800$ bytes per frame)

### Commands Executed by Windows Driver
1. **LED Illumination & Prescan Prep**:
   Windows driver sends `40 31` (`led_on_cmd`) on EP `0x01`. Sensor responds immediately with URB success (no payload read).
2. **Finger Presence Wait**:
   Driver issues `40 3f` (`pre_scan_cmd`) on EP `0x01`. Sensor holds interrupt EP `0x83` until physical capacitive contact occurs, then returns `0x55`.
3. **Continuous Raw Frame Read**:
   Driver issues `00 09` (`get_image_cmd`) on EP `0x01`. Sensor delivers 12,800 bytes on EP `0x82`. Windows streams ~8–12 frames per tap while the finger is held.
4. **Sensor Teardown / Sleep**:
   When enrollment finishes, driver sends `00 0b` (`stop_cmd`) on EP `0x01` (Packet 1437) to turn off LEDs and park the sensor into low-power idle.
5. **Template Upload to Hardware**: **NONE (0 bytes)**.

### Cross-Platform Implementation Comparison

| Attribute | Linux Lenovo TOD (`efd_tod`) | Windows Hello Driver (`WBF`) | Upstream `libfprint` (`elan.c`) |
|---|---|---|---|
| **Matching Mode** | Match-on-Host (Host CPU) | Match-on-Host (Host CPU) | Match-on-Host (Host CPU) |
| **Die Dimensions** | $80 \times 80$ (16-bit ADC) | $80 \times 80$ (16-bit ADC) | Configurable / detected via `00 0c` |
| **Frame Payload** | $12,800\text{ bytes}$ | $12,800\text{ bytes}$ | $12,800\text{ bytes}$ |
| **Command OUT EP** | `0x01` | `0x01` | `0x01` (`ELAN_EP_CMD_OUT`) |
| **Status IN EP** | `0x83` | `0x83` | `0x83` (`ELAN_EP_CMD_IN`) |
| **Image IN EP** | `0x82` | `0x82` | `0x82` (`ELAN_EP_IMG_IN`) |
| **Wait Command** | `40 3f` $\to$ `0x55` | `40 3f` $\to$ `0x55` | `40 3f` (`pre_scan_cmd`) $\to$ `0x55` |
| **Capture Command** | `00 09` | `00 09` | `00 09` (`get_image_cmd`) |
| **Stop Command** | `00 0b` | `00 0b` | `00 0b` (`stop_cmd`) |
| **Template Storage** | Host disk (`/var/lib/fprint/`) | Host disk (Windows Vault / DPAPI) | Host disk (`/var/lib/fprint/`) |

**Definitive Architecture Conclusion**: Both Windows Hello and Linux Lenovo TOD drivers communicate with `04f3:0c4f` using the exact same hardware primitives. The chip does not possess on-chip template memory or an embedded matcher. Upstream `libfprint/drivers/elan.c` already implements the required USB command state machine natively.

---

## 7. Frame Normalization & Reconstruction

Each frame consists of $80 \times 80$ 16-bit unsigned little-endian integers (`<6400H`).
The driver performs background calibration subtraction:
$$\text{Pixel}_{\text{normalized}} = \frac{\max(\text{Pixel}_{\text{touch}} - \text{Baseline}, 0)}{\text{DynamicRange}} \times 255$$

The script [`experiments/extract_frames.py`](file:///mnt/data/Projects/elan-0c4f/experiments/extract_frames.py) extracts all frames directly from any `.pcap` / `.pcapng` capture into standard Netpbm `.pgm` grayscale images in `experiments/traces/<name>_frames/`.

---

## 8. Open-Source Driver Architecture Strategy

Given that the hardware is a raw image sensor:
1. **Target Upstream Driver**: Upstream [`libfprint/drivers/elan.c`](file:///mnt/data/Projects/elan-0c4f/experiments/libfprint-upstream/libfprint/drivers/elan.c) is already designed for ELAN raw image streaming and uses these exact command codes (`00 0c`, `00 09`, `40 3f`, `40 3e`, `00 0b`).
2. **The 80x80 Pixel Challenge**: Standard `libfprint` uses NIST NBIS (`bozorth3`), which requires $\ge 15$ minutiae points. An $80 \times 80$ sensor provides only 2–4 minutiae per single touch, leading to NBIS verification failure.
3. **Paths Forward**:
   - **Multi-frame Image Stitching**: Ingesting the 2–5 frames per touch (or across touches) to build an enlarged synthetic composite image ($160 \times 160$ or larger) before minutiae extraction.
   - **Phase Correlation Matcher (SigFM / MR !530)**: Using 2D Fourier / spectral phase correlation on raw normalized $80 \times 80$ frames directly, bypassing minutiae extraction entirely.
