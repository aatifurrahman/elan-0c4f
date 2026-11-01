# PLAN.md: open-source matching for ELAN 04f3:0c4f

Goal: replace the patched Lenovo TOD module with an open-source path that logs in reliably
and rejects other fingers. The TOD module stays installed and working until a gate below says otherwise.

Audience: a human or an agent running on the Linux laptop. Read **Rules** first.

---

## 0. Rules (hard constraints)

1. **Nothing is published.** No `git push`, no uploads, no pastebins. The traces branch is local-only.
2. **Biometric data stays local.** Never commit or share `*.pcap*`, `*.npz`, `*_frames/`, `data/`, or any image of a fingerprint.
   Share code, protocol notes and aggregate numbers only. Confirm `.gitignore` covers these before the first commit.
3. **Do not replace system libfprint/fprintd.** Build into a private prefix (`~/elan-dev/prefix`) and run with
   `LD_LIBRARY_PATH` / `GI_TYPELIB_PATH`. The Lenovo TOD setup must stay re-installable with `./elan-0c4f.sh install`.
4. **Never weaken authentication.** Keep the password fallback in PAM. No fingerprint login on sudo or the lock screen
   until the Phase 5 gate passes.
5. **Log every experiment** in `experiments/LOG.md`: date, hypothesis, exact command, raw result, conclusion. Negative results count.
6. **Ask before** any `sudo` action that changes system packages or PAM.

---

## 1. Where we are

### Our own evidence (verified on the three captures we have)
- 04f3:0c4f streams **80×80, 16-bit** frames (12,800 bytes) on bulk EP 0x82; nothing is matched on the chip.
  This is a match-on-host sensor, so the matcher is software we can choose.
- With an air-frame baseline and one fixed scale, frames show clean ridges (about 8–10 across the width).
  The earlier dark-blob frames were an extractor artifact (frame 0 was used as baseline; Windows frame 0 is already a touch).
- Linux/Lenovo gives only 1–2 good frames per tap (about 140 ms apart); Windows gives about 10–15 steady frames per tap (about 27 ms apart).
- Offline single-pair matching is inconclusive. Best-of-N against a gallery gave NCC ≥ 0.74 for every same-session probe.
  **No impostor data exists yet, so the false-accept rate is unmeasured.**

### What upstream `libfprint/drivers/elan.c` does (read from its published coverage report)
- All ELAN devices use `FP_SCAN_TYPE_SWIPE`, frame stitching (`fpi_do_movement_estimation` + `fpi_assemble_frames`),
  clip frame height to `ELAN_MAX_FRAME_HEIGHT`, normalize with a 3-level mapping, then NBIS with `bz3_threshold = 24`.
- Its own header comment says the matcher "doesn't like small images" and the 96×96 square sensors were never confirmed usable.
- `0c4f` is already in its id table, which is why users see it "supported" yet failing.
- Our `experimental/elan_0c4f_opensource.patch` already adds `ELAN_0C4F`, `FP_SCAN_TYPE_PRESS`, skips the height clip,
  lowers min frames and tolerates the protocol errors. **The remaining gap is the matcher and the enrollment strategy.**

### What the community has (confidence in brackets)
| Finding | Source | Confidence |
|---|---|---|
| Upstream issue: "0c4f is mistakenly implemented as a swipe sensor instead of a touch sensor" | libfprint issue #586 | high (exists); fix status unknown |
| Many 0c4f users: enroll works or dies, `verify-no-match`, "scans only 4 times" | linux-hardware.org probes, Manjaro/Zorin forums | medium (anecdotal) |
| Same ELAN **eFSA80SC 80×80** die in SPI laptops (04f3:3104, 322d). One write-up measured bozorth3 genuine 0–26 vs impostor 0–27 (no usable threshold) and SIGFM separating them by orders of magnitude; 5/5 genuine, 0/3 impostor live | dev.to "(working) fingerprint reader on Linux" (swipe sensor, 1 author) | low-medium: single source, small n |
| SIGFM = SIFT keypoints + ratio test + geometric consistency, single-image matching, OpenCV dependency; enabled per driver with `algorithm = FPI_DEVICE_ALGO_SIGFM` (score threshold shares `score_threshold`) | libfprint MR !418 | high (design); **merge status unconfirmed, check the MR page** |
| Goodix 27c6:521d, 64×80 press sensor, SIGFM: same-finger single press accepted 5/10 live (16-press enrollment), 60–67% offline with 20–24 presses; driver enrolls 32; impostors never accepted; NBIS accepted other fingers | github.com/t0mka14/goodix-521d-sigfm | medium: one project, but closest analogue to our sensor |
| A Goodix 53x5 project replaced SIGFM with a native port of the vendor's matcher because of its limits | AndyHazz/goodix53x5-libfprint PR #33 | medium |
| SigFM-enabled libfprint forks exist on upstream 1.94.10 | goodix-fp-linux-dev/libfprint, lbssousa/libfprint | medium |
| Depau `elanmoc2` is match-on-chip for 0c4c/0c00. **Not applicable to 0c4f.** Its protocol notes may still help | Arch wiki Fprint, Depau PoC repo | high |

Takeaways: (1) NBIS is the wrong tool for sensors this small and can even false-accept; (2) SIGFM is the proven community route;
(3) expect single-touch false-reject rates of tens of percent unless enrollment is rich, so the enrollment design matters as much as the matcher.

---

## 2. Options, ranked

| # | Option | Effort | Risk | Verdict |
|---|---|---|---|---|
| A | SIGFM on top of our patched `elan.c` (press mode, many enroll stages, multi-frame frames per touch) | medium | medium (OpenCV dep, off-upstream) | **Primary** |
| B | Prototype and tune a matcher in Python/OpenCV first (alignment, preprocessing, best-of-N, frame averaging), then port the winner | low per iteration | low | **Do first, it decides A** |
| C | Tune NBIS (`bz3_threshold`, mindtct options) | low | high (evidence says it cannot separate) | Baseline only, run once to document |
| D | Reverse-engineer Lenovo/ELAN's matcher | very high | legal/clean-room risk | Not planned |
| E | Stay on patched Lenovo TOD | none | closed binary | **Fallback and default until gates pass** |

---

## 3. Phases

Each phase has a gate. Do not start the next phase until the gate passes or you record why you skipped it in `LOG.md`.

### Phase 0: hygiene (30 min)
- Confirm `.gitignore` excludes `experiments/traces/**/*.pcap*`, `**/*.npz`, `**/*_frames/`, `experiments/data/`.
- `git status` shows no biometric files staged. Work on a local branch (`lab/*`), never `main`.
- Record versions in `LOG.md`: kernel, distro, `fprintd --version`, libfprint package version, `lsusb -v -d 04f3:0c4f`.
- **Gate:** clean `git status`, environment recorded.

### Phase 1: build a proper dataset (the blocker for everything)
Without impostor data no FAR can be claimed. Use the Lenovo TOD setup for capture if it is the only thing that works,
or write `capture_usb.py` (pyusb/libusb, replaying the init and frame loop from `PROTOCOL.md`) to get frames directly with no pcap step.
Try `capture_usb.py` only after stopping `fprintd` and detaching the driver; fall back to `trace.sh` if the sensor misbehaves.

Protocol:
- **Fingers:** ≥ 8 distinct fingers, ≥ 2 people (with consent). Own fingers count as separate classes (index, middle, ring, both hands).
- **Per finger:** 3 sessions on different days, each with ≥ 10 normal touches (the way you would really unlock) plus ≥ 8 deliberate
  enroll-style touches covering different areas (centre, left, right, tip, base).
- **Conditions:** include some dry, some slightly moist, some slightly rotated touches. Real login varies.
- **Per touch:** keep all frames, not one. Record the sensor air frames at session start.
- **Layout:** `experiments/data/<person>/<finger>/<session>/touch_NN.npz` plus `manifest.json`
  (`person_id` as an opaque code, finger, session date, purpose = enroll|probe, notes). Never put real names in paths.
- Extend `extract_frames.py` output if needed, but keep one raw `.npz` schema.

**Gate:** manifest validates; per-finger counts printed; ≥ 3000 impostor trials possible (see Phase 2 maths).

### Phase 2: offline evaluation harness (`eval_offline.py` → grow it)
Evaluate by **identification-style trials**: enroll a gallery from a finger's enroll touches (session 1), probe with later sessions.
Genuine trial = probe vs its own finger's gallery; impostor trial = probe vs every other finger's gallery. Score = best match over the gallery.

Matchers to compare (same preprocessing: air-baseline subtraction, row-banding removal, high-pass, optional CLAHE):
1. NBIS (`mindtct` + `bozorth3`) as the baseline (apt: `nbis` or via libfprint build)
2. Translation-search NCC (existing)
3. Phase correlation + NCC refinement
4. SIFT/RANSAC (SIGFM-style): ratio test, `estimateAffinePartial2D`, inlier count, plus a minimum-spread check
5. Option: average N aligned frames per touch before matching (the Windows set shows 10–15 steady frames per touch)

Report per matcher: score distributions, ROC, **FRR at FAR bound**, and single-touch vs "3 tries" (PAM allows retries; report both).
Statistics rule: with zero false accepts in *n* impostor trials, FAR < 3/n at 95%. So 1/1000 needs ~3000 trials; 8 fingers × 10 probes × 7 other galleries ≈ 560 trials only bounds FAR at about 0.5%. Say so in results.

**Gate (decides Option A):** a matcher reaches **FRR ≤ 25% single-touch (≤ 8% with 3 tries) at an impostor-trial FAR bound ≤ 1/1000**, with a threshold that is stable across sessions.
If none does, stop at Option E and write up the negative result.

### Phase 3: enrollment design
Test offline before coding in C:
- Number of enroll touches (8 / 16 / 24 / 32) vs FRR (the Goodix analogue needed 16–32).
- Selecting diverse enroll touches (reject near-duplicates, require overlap with the gallery median).
- Template update on successful match (the analogue project patched fprintd for this; evaluate the gain offline first).
- Frame selection rule per touch (`state == 2` contact frames, strongest ridge energy).

**Gate:** pick enroll count N and rules; document the expected FRR curve.

### Phase 4: libfprint integration (private prefix only)
1. Get libfprint source at the version your distro ships (`git clone` from gitlab.freedesktop.org/libfprint/libfprint, or the Ubuntu/Fedora source package).
2. Apply `experimental/elan_0c4f_opensource.patch`. Keep `ELAN_0C4F`, press mode, no height clip.
3. Bring in SIGFM: read MR !418 and the goodix-fp-linux-dev / lbssousa forks; port only the `sigfm/` library, the `algorithm` field, the
   `FpImage` extraction hook and the verify branch. Check first whether your base already contains them.
4. In `dev_init` for `ELAN_0C4F`: `img_class->algorithm = FPI_DEVICE_ALGO_SIGFM;`, `dev_class->scan_type = FP_SCAN_TYPE_PRESS`,
   `dev_class->nr_enroll_stages = N` (from Phase 3), skip the swipe assembly path, feed the best frame (or an average) as one image.
5. Match the Python harness: same preprocessing and threshold. Differences between the two are bugs to find, not tuning knobs.
6. Build: `meson setup build --prefix=$HOME/elan-dev/prefix -Dexamples=true -Ddoc=false`, then use `examples/enroll`, `examples/verify`,
   `examples/img-capture` with `LD_LIBRARY_PATH` set. udev rule or run with a group that can access the USB node.
7. Optional: libfprint's test suite replays captured USB traffic via umockdev; if feasible, add a replay test from a **synthetic or consented, redacted** capture.

**Gate:** live `enroll` then 30 `verify` runs with the real finger and 30 with another person's finger, results logged. Compare with Phase 2 predictions.

### Phase 5: system integration (only after Phase 4 passes)
- Install into the private prefix first. Test `fprintd` from that prefix on a **user-bus** session before touching system services.
- PAM: add fingerprint as `sufficient` with password fallback. Test locally with a second terminal logged in as root.
- Enrolled prints from different algorithms are not interchangeable; document `fprintd-delete` / re-enroll.
- Do not enable it for `sudo` until a week of normal use with no false accepts.
- Packaging (optional, after the above): extend `elan-0c4f.sh` with an `opensource` subcommand that builds into the prefix,
  leaving the TOD path intact.

### Phase 6: contribute, only what is safe
- Document the protocol and the 0c4f sensor facts (80×80, 16-bit, EP 0x82 frames, touch not swipe) on libfprint issue #586. **No images.**
- Share the extractor, the evaluation harness and aggregate ROC numbers.
- Propose the `ELAN_0C4F` press-mode change upstream **only** once the matcher dependency is settled.

---

## 4. Decision gates (summary)

| Gate | Pass | Fail |
|---|---|---|
| Phase 2 | FRR ≤ 25% single / ≤ 8% three-try at FAR bound ≤ 1/1000, stable across sessions | stay on E, publish the negative result |
| Phase 3 | enroll N and rules chosen with a measured FRR curve | revisit matcher |
| Phase 4 | live results within a few points of the offline prediction | fix the C/Python mismatch before anything else |
| Phase 5 | one week, no false accepts, fallback tested | do not enable for sudo |

---

## 5. Known unknowns
- Is SigFM merged upstream, and in which release? (Check MR !418 and the target libfprint version before porting.)
- Does 0c4f need the swipe-style init commands or does the press path need different `calibrate` handling? (Check `PROTOCOL.md`; our patch already runs.)
- Do Windows Hello's 10–15 frames per touch come from a different capture mode, and can we reproduce it on Linux? That would be a real data gain for matching.
- Sensor drift / calibration per session (air baseline moves?) and temperature effects.
- Whether OpenCV is acceptable as a dependency for the final deliverable. The Goodix 53x5 project moved away from it; a lighter native matcher may be preferable for packaging.

## 6. References
- libfprint `elan.c` coverage report: https://libfprint.pages.freedesktop.org/libfprint/coverage/index.elan.c.7cff9621e130bbfc25372e3fe67e440e.html
- libfprint issue #586 (0c4f swipe vs touch): https://gitlab.freedesktop.org/libfprint/libfprint/-/issues/586
- libfprint MR !418 (SIGFM): https://gitlab.freedesktop.org/libfprint/libfprint/-/merge_requests/418
- libfprint issue #174 (ELAN verify problems): https://gitlab.freedesktop.org/libfprint/libfprint/issues/174
- eFSA80SC / SIGFM write-up: https://dev.to/matemiller/working-fingerprint-reader-on-linux-42b3
- Goodix 521d + SIGFM (small press sensor, numbers): https://github.com/t0mka14/goodix-521d-sigfm
- Goodix 53x5 native matcher replacing SIGFM: https://github.com/AndyHazz/goodix53x5-libfprint/pull/33
- Depau elan 0c4c PoC (match-on-chip, not 0c4f): https://github.com/depau/Elan-Fingerprint-0c4c-PoC
- Arch wiki Fprint (TOD, elanmoc2 notes): https://wiki.archlinux.org/title/Fprint
- linux-hardware probes for 04f3:0c4f: https://linux-hardware.org/?id=usb%3A04f3-0c4f

## 7. Task checklist
- [ ] Phase 0: gitignore check, environment log
- [ ] Phase 1: dataset protocol, `manifest.json`, `capture_usb.py` (optional)
- [ ] Phase 2: harness with NBIS baseline, NCC, POC, SIFT, frame averaging; ROC plus FAR bound
- [ ] Phase 2 gate decision recorded in `LOG.md`
- [ ] Phase 3: enrollment count and selection rules
- [ ] Phase 4: private-prefix libfprint build with SIGFM, live tests
- [ ] Phase 5: PAM with fallback, one-week trial
- [ ] Phase 6: safe upstream notes