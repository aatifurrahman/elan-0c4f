#!/usr/bin/env python3
"""
Extract raw 16-bit ADC sensor frames from ELAN 04f3:0c4f packet traces.
Exports PGM images, a lossless raw .npz, and an ASCII ridge preview. No tshark required.
Usage: python3 experiments/extract_frames.py [path_to_trace.pcap|pcapng] [--raw16]

Output dir: <trace>_frames/   (already covered by .gitignore `*_frames/`)
  frame_NNN_pktP.pgm   8-bit, air-baseline-subtracted, ONE fixed scale per session
                       (--raw16: 16-bit PGM of the untouched ADC values instead)
  raw.npz              frames uint16[N,80,80] (untouched), tap, state, t, pkt, baseline
                       state: 0 air, 1 transition (partial contact / lift-off), 2 contact (usable)

Changes vs the previous version (all verified against the three bundled captures):
  * Baseline = median of the session's AIR frames, not "frame 0". Frame 0 is air in the Linux
    traces but already a touch in the Windows trace, which produced the dark blobs.
  * One global scale per session instead of per-frame max, so contact strength stays comparable.
  * Taps are numbered (a tap starts at each `40 3f` wait-for-touch command).
  * Built-in pcap (usbmon, linktype 220) and pcapng (USBPcap, linktype 249) reader.
"""
import os, struct, sys
import numpy as np

W = H = 80
FRAME = W * H * 2                      # 12,800 bytes, little-endian uint16
EP_CMD_OUT, EP_IMG_IN = 0x01, 0x82
WAIT_TOUCH = b"\x40\x3f"
ASCII_CHARS = " .:-=+*#%@"

# ---------------------------------------------------------------- capture readers
def _read_pcap(b):
    magic = b[:4]
    if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"): end, nsec = "<", magic == b"\x4d\x3c\xb2\xa1"
    elif magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"): end, nsec = ">", magic == b"\xa1\xb2\x3c\x4d"
    else: sys.exit("not a pcap file")
    link = struct.unpack(end + "I", b[20:24])[0]
    off, n = 24, 0
    while off + 16 <= len(b):
        s, us, cap, _ = struct.unpack(end + "IIII", b[off:off + 16]); off += 16; n += 1
        yield n, s + us / (1e9 if nsec else 1e6), link, b[off:off + cap]
        off += cap

def _read_pcapng(b):
    off, n, links, res = 0, 0, [], []
    while off + 12 <= len(b):
        t, l = struct.unpack("<II", b[off:off + 8]); body = b[off + 8:off + l - 4]
        if t == 1:
            links.append(struct.unpack("<H", body[:2])[0]); res.append(1e-6)
            o = 8
            while o + 4 <= len(body):
                code, ln = struct.unpack("<HH", body[o:o + 4])
                if code == 0: break
                if code == 9 and body[o + 4] < 128: res[-1] = 10.0 ** -body[o + 4]
                o += 4 + ((ln + 3) & ~3)
        elif t == 6:
            i, hi, lo, cap, _ = struct.unpack("<IIIII", body[:20]); n += 1
            yield n, ((hi << 32) | lo) * res[i], links[i], body[20:20 + cap]
        off += l

def _usb(link, pkt):
    """-> (kind 'S'|'C', endpoint, payload) for bulk transfers, else None."""
    if link == 220:                                     # Linux usbmon, 64-byte header
        if len(pkt) < 64 or pkt[9] != 3: return None
        return chr(pkt[8]), pkt[10], pkt[64:]
    if link == 249:                                     # USBPcap
        hl = struct.unpack("<H", pkt[:2])[0]
        if pkt[22] != 3: return None
        return ("C" if pkt[16] & 1 else "S"), pkt[21], pkt[hl:]
    sys.exit(f"unsupported linktype {link}")

def read_frames(path):
    b = open(path, "rb").read()
    it = _read_pcapng(b) if b[:4] == b"\x0a\x0d\x0d\x0a" else _read_pcap(b)
    frames, tap_ids, ts, pkts, tap, t0 = [], [], [], [], 0, None
    for n, t, link, pkt in it:
        t0 = t if t0 is None else t0
        r = _usb(link, pkt)
        if not r: continue
        kind, ep, data = r
        if ep == EP_CMD_OUT and kind == "S" and data[:2] == WAIT_TOUCH: tap += 1
        elif ep == EP_IMG_IN and kind == "C" and len(data) == FRAME:
            frames.append(np.frombuffer(data, "<u2").reshape(H, W).copy())
            tap_ids.append(tap); ts.append(t - t0); pkts.append(n)
    return (np.stack(frames), np.array(tap_ids, np.int32), np.array(ts), np.array(pkts, np.int32)) if frames else None

# ---------------------------------------------------------------- analysis
def air_baseline(frames):
    m = frames.reshape(len(frames), -1).mean(1)
    air = m <= m.min() * 1.01                           # air level ~4757 on this unit in every session
    return np.median(frames[air], axis=0).astype(np.uint16), air

def classify(frames, baseline, air):
    d = frames.reshape(len(frames), -1).mean(1) - baseline.mean()
    st = np.ones(len(frames), np.uint8); st[air] = 0
    st[(d >= 0.6 * np.percentile(d, 95)) & ~air] = 2
    return st

def render_ascii_art(pixels, width=80, height=80, target_cols=40):
    sx, sy = width // target_cols, 2
    lo, hi = min(pixels), max(pixels); rng = max(hi - lo, 1)
    return "\n".join("".join(ASCII_CHARS[int((pixels[y * width + x] - lo) / rng * (len(ASCII_CHARS) - 1))]
                             for x in range(0, width, sx)) for y in range(0, height, sy))

def write_pgm(path, img, maxv):
    data = img.astype(">u2").tobytes() if maxv == 65535 else img.astype(np.uint8).tobytes()
    open(path, "wb").write(f"P5\n{W} {H}\n{maxv}\n".encode() + data)

def find_latest_trace():
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "traces")
    if not os.path.isdir(d): return None
    f = [os.path.join(d, x) for x in os.listdir(d) if x.endswith((".pcap", ".pcapng"))]
    return max(f, key=os.path.getmtime) if f else None

def extract_frames(path, raw16=False):
    print("=" * 70 + f"\n ELAN 04f3:0c4f Frame Extractor\n Trace File: {path}\n" + "=" * 70)
    got = read_frames(path)
    if got is None:
        print("No 12,800-byte frames found in capture."); return
    frames, tap, t, pkt = got
    base, air = air_baseline(frames); state = classify(frames, base, air)
    d = np.clip(frames.astype(np.int32) - base.astype(np.int32), 0, None)
    scale = np.percentile(d[state == 2], 99.5) if (state == 2).any() else max(d.max(), 1)
    n8 = np.clip(d * 255.0 / scale, 0, 255).astype(np.uint8)

    out = os.path.join(os.path.dirname(os.path.abspath(path)), os.path.splitext(os.path.basename(path))[0] + "_frames")
    os.makedirs(out, exist_ok=True)
    np.savez_compressed(os.path.join(out, "raw.npz"), frames=frames, tap=tap, state=state, t=t, pkt=pkt, baseline=base)
    print(f"[*] {len(frames)} frames, {tap.max()} taps (air {int((state==0).sum())}, transition "
          f"{int((state==1).sum())}, contact {int((state==2).sum())}). Output directory: {out}\n")
    names = ("air", "transition", "CONTACT")
    for i in range(len(frames)):
        f = frames[i]; name = f"frame_{i:03d}_pkt{pkt[i]}.pgm"
        write_pgm(os.path.join(out, name), f if raw16 else n8[i], 65535 if raw16 else 255)
        print(f"Frame {i:03d} (Pkt {pkt[i]:>4}, T={t[i]:>7.3f}s, tap {tap[i]:2d}): {names[state[i]]:<10} "
              f"Min={f.min():>5} Max={f.max():>5} Avg={f.mean():>7.1f} -> {name}")
    good = np.where(state == 2)[0]
    if len(good):
        best = good[np.argmax(d[good].mean((1, 2)))]
        print("\n" + "=" * 50 + f"\n ASCII Ridge Preview (frame {best}, strongest contact):\n" + "=" * 50)
        print(render_ascii_art(list(d[best].ravel()), W, H, 40) + "\n" + "=" * 50 + "\n")

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    pcap = args[0] if args else find_latest_trace()
    if not pcap or not os.path.isfile(pcap):
        print("Usage: python3 experiments/extract_frames.py <trace.pcap|pcapng> [--raw16]"); sys.exit(1)
    extract_frames(pcap, "--raw16" in sys.argv)