# Findings: 2020 Kia Sorento EX 3.3L V6 (8-speed automatic)

The single record of what has been learned about this car's diagnostic data. Keep it up to date when a log
is analysed. Each item is marked:

- **CONFIRMED**: checked against an independent reference (standard OBD value, road-speed ratio, or a
  repeated on/off test with several readings per state).
- **LIKELY**: consistent across the tests so far, but one plausible alternative remains.
- **GUESSED**: one observation or an inference; treat as a lead only.

Byte numbers count from 1 after the 3-byte positive reply header (for example `62 01 A0`).
Multi-byte values are big-endian unless marked LE.

Read-only rule: only OBD services 01 02 03 07 09 0A and UDS 19 and 22 are ever sent. Never 10, 04/14, 11,
27, 2E, 2F, 31, 3E.

Privacy: the engine computer's `22 F190` reply is the VIN. Never paste it anywhere public. The sweep report
from the app hides it.

## The problem being chased

Brief, unexplained deceleration at low, steady throttle, like an abrupt shift. Not yet caught in a log with
the "I FELT IT" marker (as of 2026-11-14).

## Hardware and addressing (CONFIRMED)

- Adapter: OBDLink MX+ (classic Bluetooth SPP, ELM327/STN command set). One connection at a time.
- Protocol: ISO 15765-4 CAN 11-bit 500k (ELM protocol 6).
- Engine computer: request `7E0`, reply `7E8`. Transmission computer: request `7E1`, reply `7E9`.
- Transmission part number `95441-4G480` (`7E1 22 F191`), software `U834` (`F189`).

## Important pitfall: never read Mode 01 pedal PIDs by broadcast (CONFIRMED 2026-11-14)

With broadcast (`7DF`) both computers answer Mode 01. The transmission computer also reports PID `49`
(pedal D), but as its own copy: 0% at rest, rising roughly with the pedal. The engine reports the real
sensor value (14.9% at rest). Whichever reply arrives first wins, so a broadcast log shows pedal D jumping
between ~0 and ~15 at rest and disagreeing with pedal E while moving.

- Evidence: Monitor drive 2026-11-14 15:06 (broadcast): 642 of 1253 samples had |D - E| > 3, 270 of them
  D = 0.0 exactly with E at its 14.5-14.9 rest value. Where pedal was pressed, D matched E's position above
  rest (correlation 0.92). Engine-only logs (drive test 12:50, pedal sweep 14:46) never show it.
- The 2026-11-13 22:22 log (first-frame parsing) had 2259 of 3845 pedal D samples below 14 for the same
  reason. Its "pedal drops" are artefacts, not sensor faults.
- Fix in the app (build 2026-11-14-e): Monitor polls the engine computer only by default.
- The original 1 Hz log from the other app (D and E dipping together to 14.9 with torque following) is a
  different thing and is still unexplained.

## Pedal sensors (engine `7E0`, Mode 01)

- PID `49` (pedal D) and `4A` (pedal E), A*100/255. Rest: D 14.90, E 14.51-14.90. Full press reached
  D 85.1 / E 84.3. CONFIRMED (pedal sweep 2026-11-14 14:46, engine off, ignition on).
- In that sweep the two sensors tracked each other within 1-2 points at every reading (largest gaps 4.3 and
  3.1 while the pedal was moving fast), with no dropouts. CONFIRMED for that 50-second sweep only.

## Transmission computer `7E1`, service 22

Identification IDs that answer: `F100 F180 F181 F182 F186 F187 F189 F18C F191 F192 F194`. Live blocks:
`01A0` (45 bytes), `01A1` (45), `01A2` (10), `01A3` (10). `01A7` (66) looks like learned adaptations.
`01F2` exists but answers "conditions not correct". Sweep 2026-11-17 17:08 (partial): `2300-73DF` answer nothing (all "not supported"). Sweep then trimmed (build 2026-11-17-b) to B100-BFFF, C100-CFFF, F200-FFFF; `73E0-AFFF` and `D100-EFFF` NOT swept. Trimmed sweep finished 2026-11-17 18:47: only `F806` answers, 4 bytes `1C A2 3D E4`. F8xx mirrors OBD Mode 09 info types, so F806 is the calibration verification number (CVN), a checksum of the transmission software. If a dealer reflashes the transmission it should change: re-read it after any service visit. Guessed IDs `0101 0102 E001 E002 1101 1940 1104 1944
1102 1941`: not supported.

### Block `22 01 A0`

| Byte | Meaning | Coding | Status |
|---|---|---|---|
| 5-6 | Engine RPM | value / 4 | CONFIRMED vs PID 0C |
| 10-11 | Turbine (input shaft) RPM | value / 4 | CONFIRMED (ratio vs road speed per gear) |
| 17-18 | Converter slip | (value - 0x0800) / 4 rpm, equals engine minus turbine exactly | CONFIRMED |
| 21 | Lever position | 0B P, 0A R, 09 N, 08 D, 0C manual gate | CONFIRMED |
| 22 | Current gear | 00 P/N, 01-08, 0E reverse | CONFIRMED (drive 2026-11-14 12:50, all 8 gears) |
| 23 low nibble | Target gear | same coding as byte 22; leads byte 22 by up to ~2 s | CONFIRMED |
| 23 high nibble | Flag, set in almost every locked sample | 0/1 | GUESSED: lock-up active |
| 25 bit 0 | Brake switch | 1 = pedal pressed | CONFIRMED (two on/off rounds + drive) |
| 29-30 | Complementary pair (sum about 0xFE), changes with lever | unknown | GUESSED |

Turbine RPM per mph by gear (drive 2026-11-14 12:50): 1st ~168 (noisy), 2nd 124, 3rd 81, 4th 63, 5th 52,
6th 43, 7th 34, 8th 28.

Converter: locked (slip within about ±10 rpm) in 5th-8th and mostly in 4th at steady speed; a few hundred
rpm in 1st-3rd. After an upshift into 8th it re-locks over 5-7 s with a controlled slip of 20-30 rpm first.
CONFIRMED (lock-up test 2026-11-14 14:30, 65 mph on cruise, two kickdowns 8>5 and 8>3).

### Block `22 01 A1`

- Bytes 17-21 sit at 0x0A or 0xDC (10 / 220), and the pattern changes with gear (for example byte 20 = DC
  in steady 8th; bytes 19-20 = DC in 2nd from the manual gate). GUESSED: per-clutch apply commands.
- Byte 43 was a lock-up candidate on 2026-11-14 12:50 but did not follow lock-up in the 14:30 test.
  Dropped.

## Engine computer `7E0`, service 22

62 blocks answer in `E000-E0FF` (`E001-E006 E009 E00A E010-E014 E016-E019 E01B-E024 E027 E02C E02D
E040-E058 E080 E091-E095 E0F1 E0F2`), plus `F1xx` identification. Blocks `E012 E013 E01C E01E E021 E024
E02C E02D E0F2` never changed in any parked test.

| Block, byte | Meaning | Coding | Status |
|---|---|---|---|
| E001, 8-9 LE | Engine RPM | value / 4 | CONFIRMED vs PID 0C |
| E002, last 12 bytes | Six 16-bit values that move together with load | unknown | GUESSED: per-cylinder |
| E004, 8, bits 0-1 | A/C request | 70 off, 73 on | CONFIRMED (3 rounds, 11-12 readings each) |
| E0F1, 6, bits 2-3 | A/C | 01 off, 0D on | CONFIRMED (same test) |
| E009, 5, bit 0 | Blower fan on | 70 off, 71 on | CONFIRMED (3 rounds) |
| E004, 13, bit 2 | Blower fan on | F8 off, FC on | CONFIRMED (3 rounds) |
| E009, 5, bit 1 | Headlights (low beam) on | 70 off, 72 on. Set for low beam, full beam, fog and AUTO when it is dark; clear for OFF and the parking-light position | CONFIRMED (3 rounds + light switch test, 2 rounds) |
| E004, 6 | Brake | D1 off, DD on | LIKELY |
| E0F1, 7 | Brake | C7 off, D7 on | LIKELY |
| E0F1, 63 | Earlier A/C candidate | flipped in other tests too | dropped |
| E004, 15, bit 0 | Cruise main switch (cruise light) | 30 off, 31 on | CONFIRMED (3 rounds, 7-9 readings each) |
| E01F, 43 | Cruise state | 01 off, 04 on in the cruise test; 00/04/08 seen in the parking-brake test | GUESSED: cruise status, coding not understood |

Not found in the engine or transmission blocks (each tested with 3 rounds or 5 steps, 4-6 readings per
state): rear defrost, drive mode button (twice), parking brake, Auto Hold, ESC OFF, steering wheel. These
likely live in other modules (body, brakes, steering), which the app does not read.
Light switch test (2026-11-14 18:10, two rounds, 5-8 readings per position): only the headlights bit above
changed. Full beam, fog lights and the parking-light position are not visible in these blocks.

Heated seats (test 2026-11-17 18:21, off/on/off, about 16 s each, engine idling): no on/off flag in any
engine or transmission block. Two bytes dipped by one count while on and recovered when off: `E018` byte 17
(A1 to A0) and `E0F1` byte 49 (83 to 82). Probably the engine computer seeing the extra electrical load
(voltage or alternator), not a seat signal. Single cycle, so GUESSED at best.

## Other computers on the diagnostic bus

Found by the Mac bridge (`discover`, 2026-11-14 morning): asking every address 700-7EF for `22 F190`, 21
answered. All reply on request address + 8. Identity from `22 F187`/`F189`/`F191`/`F194` where available.
Module roles are GUESSED from part-number prefixes and Hyundai/Kia conventions, not confirmed.

| Request | Reply | Clue | Likely role (GUESSED) |
|---|---|---|---|
| 7E0 | 7E8 | VIN, F18C | Engine (CONFIRMED) |
| 7E1 | 7E9 | 95441-4G480, U834 | Transmission (CONFIRMED) |
| 737 | 73F | F189 "AEB SCC" | Radar: smart cruise / forward collision avoidance |
| 7D1 | 7D9 | no ID returned | ABS / ESC |
| 7D4 | 7DC | refuses 22 (NRC 11) | Power steering |
| 7A0 | 7A8 | 954A0-C6090 | Body control module |
| 770, 771 | 778, 779 | 91961-C5AA7, 91950-C6527 | Junction boxes |
| 7B7 | 7BF | 95810-C6000 | Unknown |
| 7A1 | 7A9 | 93570-C6BG0 | Switch module |
| 7C3 | 7CB | 88952-C6500 | Seat module |
| 7C4 | 7CC | "HY_G0UMP" software | Head unit or camera |
| 777, 780, 7A5, 71A, 7D0, 7D2, 7D5, 7D6, 7E5 | +8 | little or no ID | Unknown |

No live data is known yet for any of these. The app's Sweep mode has a "Plan: other computers" preset
(full 0000-FFFF on each, ABS and radar first); Identify tests marked "(other computers)" use whatever it
finds. The radar and ABS/ESC are of interest for the hesitation: both can request engine torque reduction.

## Logging rates on this phone and adapter

- Mode 01 multi-PID groups to the engine only: about 8 samples/s per channel with no other blocks.
- Monitor with the transmission block every other cycle: about 1.5 samples/s per pedal channel and
  0.8/s for the transmission block (2026-11-14 15:06, broadcast). Expected to improve with engine-only
  polling; not yet measured.
- 39 service-22 blocks per cycle: one pass every ~6 s (each block 0.05-0.24 s).

## App behaviour notes

- Build 2026-11-19-a: Sweep mode removed (tabs: Monitor, Identify). The background-sweep card moved to the
  Monitor page and the "other tools" card to Identify. The background sweep now also runs with the engine off
  when the ignition is on and the phone is plugged in (new native AndroidBT.isCharging): within the first
  minutes inside the monitor loop, and after the 5-minute battery-saver point in the auto loop (bursts of up
  to 10 s, checking pedal, speed and engine speed every 4 IDs; monitoring starts within about 1 s of the engine
  starting, simulated). Not charging and engine off: no sweep, battery saver as before. Monitoring itself is
  unchanged.

- Build 2026-11-18-b, converter lock-up watch (Monitor):
  - While in D, rolling, foot on and converter slip 40+ rpm (and for 1.5 s after a lock-up) the transmission
    block is read up to 4 times in a row without switching addresses, then one engine read. Simulated: about
    4 transmission reads per engine read while unlocked, 1:1 when locked. Expect roughly 5/s transmission and
    1.3/s pedal while unlocked on the car.
  - New column tcm_engine_rpm (01A0 bytes 5-6 /4), so engine speed comes with every transmission reading.
  - Event `lock` (no beep): slip 60+ to within 20 rpm in one reading, same gear, D. Info: slip before and after,
    time between the two readings, engine rpm before/after, pedal range, and a phone score 1.2 s later:
    "decel dip" = how far the forward push fell below its level in the 1.5 s before (m/s²), when, and peak jerk.
    The tile shows the count and the hardest dip of the drive.
  - Group `A` rows: every phone motion sample (about 50 Hz) from 1.5 s before to 1 s after each lock-up and
    from 4 s before to 1 s after each mark; columns phone_ax/ay/az, acc_fwd (+ = speeding up, along the learnt
    forward axis) and acc_horiz. Written about a second late, so sort by t_s.
  - Sweep mode: plan box default "other computers" continues the shared background-sweep progress
    (obd_bg_sweep), so nothing already asked is asked again. A typed plan still runs as before.

- Build 2026-11-18-a: transmission block read every cycle (was every other). Expected on the car from the
  11-17 timings (engine group about 0.14 s, transmission read about 0.26 s with the address switches): both
  about 2.5 readings/s, against engine 3.65 and transmission 1.83 before. Clutch-slip detector now needs two
  readings in a row (one reading gave a false alarm in a braking simulation). The crash-safe copy of the log
  now writes only the rows added since the last copy (every 20 s) instead of rebuilding the whole log; the
  old way grew with drive length and is a suspect for the rate falling late in the 2026-11-18 drive.

- Background sweep (build 2026-11-17-d): in Monitor mode, whenever the car is stopped for 1 s (speed 0,
  engine running, pedal D at or under 16.5%) and either in P/N or in D/M with the brake on (TCM byte 25),
  the app asks the other computers for data IDs. Between every request in D (every 4th in P/N) it reads
  `01 49 0D` from the engine and hands back to monitoring as soon as the pedal moves or speed is above 0
  (simulated: under 0.1 s). Bursts last at most 10 s in D, 2.5 s in P/N, then one monitor cycle. Each burst
  leaves an `E` row `sweep` in the drive log saying how long monitoring paused. Order: 7D1 (likely ABS/ESC)
  and 737 (radar cruise), then the rest of FS_OTHERS; pass 1 = 0100-01FF, B000-B1FF, C000-C1FF, D000-D1FF,
  E000-E1FF of every computer, pass 2 = the rest. Progress in localStorage `obd_bg_sweep`; finds saved in
  their own file obd_bgsweep_*.txt, never in the drive CSV.

- Sweep runs only while the engine is running (RPM above 400, checked about once a second), unless the
  user unticks that option. Reason: an hour-long sweep with only the ignition on would drain the 12 V battery.
- Battery saver (build 2026-11-16-a): after 5 minutes with the engine off (car not answering, or RPM below
  400 with the ignition on), the app stops logging or sweeping, turns off GPS and the motion sensor, lets
  the screen sleep, and checks for the car every 15 s. If the phone is on battery it also releases its CPU
  wake lock, so checks may be further apart while the phone sleeps; plugging in the phone (car started)
  wakes it at once. Whether the car's USB socket switches off with the ignition, and whether the MX+ goes
  to sleep with the engine off, have not been checked.

- The Android app checks GitHub (release `android-latest`) at start and every 3 hours, and shows a banner when
  the release was built from a different commit than the installed app. The commit id is stamped into the
  page at build time.

- Monitor (build 2026-11-17-a) reads only pedal D and E, commanded throttle, torque, RPM and speed in one
  request, plus the transmission block every other cycle (ATSH/ATCRA switched to 7E1/7E9 and back). A/C,
  fan, headlights and cruise are no longer read in Monitor.
- Do not use a shared reply filter (ATCF 7E8 + ATCM 7FE) or STPX on this adapter/car: build 2026-11-16-c
  did, and on 2026-11-17 every transmission reply was lost and 42% of engine replies came back incomplete
  (99.9% complete with ATSH/ATCRA switching). The phone simulator did not catch this because it ignores
  adapter filter commands; adapter-level changes need a real drive to verify.
- Monitor flags events (rows with group E, columns `event` and `event_info`), from build 2026-11-15-a:
  - `decel`: speed falling 2 mph/s or more over about 1 s, above 8 mph, pedal held steady (within 4 points)
    or at rest, and no brake in the transmission sample that follows. Beeps.
  - `jolt`: phone accelerometer, horizontal part only, above 1.2 m/s² for at least 0.25 s, above 8 mph, no
    brake. Beeps.
  - `slip`: converter locked, gear settled, above 15 mph, speed steady, but the input shaft turns 8% or
    more faster than the gear's ratio. Beeps.
  - `flare`: engine RPM up 150 or more during an upshift with the pedal steady. Beeps.
  - `tcc`: converter goes from locked to more than 100 rpm slip in 4th or higher at steady pedal. No beep;
    it happened about 30 times in the 2026-11-15 drive.
  - Checked against the 2026-11-15 drive: decel, slip and flare would not have fired at all (every
    2 mph/s deceleration in that drive had the brake on). Jolt could not be checked (phone data in old logs
    is only 7 samples/s).
  - Measured gear ratios (turbine rpm per mph, locked, steady): 4th 61 (not 63), 5th 52, 6th 43, 7th 34;
    steady samples sit within about ±5% of these.

## Test log

| Date | File | Result |
|---|---|---|
| 2026-11-13 23:00 | obd_selector | Lever byte found (01A0 byte 21) |
| 2026-11-13 23:18 | obd_scan | Transmission live blocks 01A0-01A3 found; 62 engine blocks |
| 2026-11-14 12:50 | obd_test_drive | Gears 1-8 and slip confirmed |
| 2026-11-14 13:2x | brake, manual, drivemode, throttle, ac, loads | Brake bit, manual gate; others too short (1 reading per step) |
| 2026-11-14 14:30 | obd_test_lockup | Lock-up and re-lock behaviour normal |
| 2026-11-14 14:46 | obd_test_pedalsweep | Pedal sensors agree, no dropouts |
| 2026-11-14 14:47-14:53 | ac, fan, lights, defrost | A/C, fan, headlights decoded; defrost not visible |
| 2026-11-14 15:06 | obd_ (Monitor, 13.5 min) | No marks. Found the broadcast pedal-D artefact above |
| 2026-11-14 17:48-17:58 | drivemode, cruisebtn, parkbrake, autohold, steering, esc | Cruise main switch decoded; the rest not visible |
| 2026-11-17 18:21 | custom: heated seats | Not visible; two 1-count dips likely from electrical load |
| 2026-11-14 18:10 | obd_test_lightmodes | Only low-beam-on visible; full beam, fog, parking lights not |
| 2026-11-15 16:59 | obd_ (Monitor, 19 min) | First two marks; see the section above. Engine-only fix confirmed |
| 2026-11-16 17:15 | obd_ (Monitor, 15 min) | Three marks: two next to brief pedal releases, one on cruise control |
| 2026-11-17 08:25 | obd_ (Monitor, 14 min) | Three marks, no pedal drops near them; transmission data lost (app bug) |
| 2026-11-17 16:50 | obd_ (Monitor, 11 min) | Three marks after a steady-pedal downshift, a converter lock and a 3-4 upshift |

## First marked event (Monitor drive 2026-11-15 16:59, 19 min, engine-only polling)

Two taps at 434.4 s and 436.7 s, around 22 mph. Sequence (pedal 2.7 samples/s, transmission 1.35/s,
phone accelerometer about 7/s):

- 432.8 s: both pedal sensors back at rest (D 14.9, E 14.5), commanded throttle 3.9%. Foot off, or both
  sensors reading rest together.
- 433.5 s: upshift 4th to 5th with the pedal at rest; torque falls to 0% by 434.8 s; converter locks
  (slip about 0) at 434.2 s.
- 434.4 s: first tap. Nothing visible in speed or the accelerometer yet.
- 434.9-435.8 s: deceleration of about 0.14 g (phone) and 3-4 mph/s (speed 22.4 to 19.3 mph), then speed
  flat at 18.6 mph for 2 s.
- Brake switch: off in the transmission sample at about 434.8 s, on at 435.5-436.5 s. With samples 0.7 s
  apart, the brake may have been pressed at the start of the deceleration.
- 436.7 s: second tap. Pedal pressed again at 437.4 s.

Pedal D and E agreed throughout this drive (5 of 3107 samples differ by more than 3 points, all while the
pedal was moving). No dropouts.

The foot-off upshift followed by converter lock happened 13 times in this drive; only this one was marked,
so on its own it is not distinctive. Open: did the driver lift off at 432.8 s and touch the brake at
about 435 s? If neither, the pedal reading rest for 4 s and the deceleration are the event.

## Monitor drive 2026-11-16 17:15 (15 min, three marks; older build, pedal 2.4 samples/s)

- Marks 1 and 2 (91.3 s and 99.95 s, 37 mph, 7th gear, pedal about 31%): each sits next to a moment where
  both pedal sensors drop to their rest value (D 14.9, E 14.5) for one sample, commanded throttle falls to
  3-4% and engine torque from 47% to 14-17%, then the pedal returns over about 1 s. At 90.3 s (31.8% to
  rest, back to 31.4% by 91.8 s), at 92.6-92.9 s (19.6%, then rest), and at 100.3-100.7 s (24.3%, then rest,
  back to 32.5%). The way down passes through intermediate values (19.6%, 24.3%) and the way back rises over
  several samples, which looks like the pedal physically moving rather than an electrical dropout. Not
  decided: foot movement versus the pedal assembly.
- The same brief release-and-return happened 21 times in this drive; only 2 were marked.
- Mark 3 (260.3 s, 63 mph, 8th): on cruise control (pedal at rest, commanded throttle 17%, torque 42-44%).
  Nothing changed at the mark. 2.4 s earlier (257.9 s) the converter re-locked after 4 s of about 100 rpm
  slip (engine RPM fell 110 in half a second). If this mark was the same feeling, the pedal cannot be the
  only cause.
- Detector review: 10 "decel" events fired with the pedal at rest and no brake seen, all ordinary coasting
  (2.0-3.0 mph/s). 4 "jolt" events lasted 0.4-1.8 s with the pedal held: likely cornering. Changed in build
  2026-11-16-c: coasting logged as `coast` without a beep; jolts use only the front-back direction once it
  has been learnt from speed changes, and must last 0.25-1.5 s; new `blip` event for the pedal pattern above.

## Monitor drive 2026-11-17 08:25 (14 min, three marks; build 2026-11-16-c, no transmission data)

- The transmission block failed for the whole drive (see the filter note above), so the marks have engine
  data only. Pedal about 3.7 samples/s.
- Marks 1 and 2 (214.1 s, 217.1 s): gentle acceleration from 25 to 30 mph, pedal steady at 32%, torque
  steady 43-47%. No pedal drop near either mark. Engine RPM drops that look like upshifts at 211.4, about
  215.0-215.6 and 218.6 s; the marks fall between them.
- Mark 3 (460.9 s, 52 mph): the pedal had eased from 36% to 25.5% over 458-460 s; an RPM drop of about 250
  at 458.8 s (shift or converter lock) 2.1 s before the mark. A pedal drop to rest followed at 463.5 s.
- So these three marks are not next to pedal drops, unlike two of the 2026-11-16 marks. With transmission
  data missing, shifts and converter lock cannot be confirmed.
- 7 pedal blips in the drive, none within 10 s of a mark.

## Monitor drive 2026-11-17 16:50 (11 min, three marks; build 2026-11-17-a)

Transmission reads fixed: 99.9% complete engine replies, pedal 3.65 samples/s, transmission 1.83/s.

- Mark 1 (513.1 s, 27 mph, pedal steady 33-35%, torque 43-55%): 2.1 s after the transmission asked for a
  5th to 4th DOWNSHIFT at 511.0 s with the pedal steady and speed rising (engine 1395 to 1813 rpm; shift
  done at 512.3 s). Before it, 5th had run with large converter slip (200-490 rpm, engine about 1500).
- Mark 2 (516.7 s): 1.1 s after the converter locked in 4th at 515.3-515.6 s (slip 141 to about 0, engine
  1870 to 1654 rpm).
- Mark 3 (629.5 s, 15.5 mph): at the end of a 3rd to 4th upshift requested at 627.3 s and completed at
  629.7 s (2.4 s, slow end of normal), during which commanded throttle and torque were cut (39% to 25%) while
  the pedal eased from 31% to 25%. 1.4 s after the mark the transmission asked for 4th to 3rd again at
  630.9 s with the pedal steady (gear hunting 3-4-3 within 4 s). A jolt (0.2 g, 0.7 s) was detected at
  627.2 s.
- No pedal blip within 30 s of any mark. Pedal sensors steady and in agreement at all three.
- In the whole drive: 24 shifts with the pedal steady and the brake off, 4 of them downshifts (3>2 twice at
  10-13 mph, 5>4 before mark 1, 4>3 after mark 3).
- Shift timing (target change to gear change, at the 0.55 s sampling): median 1.6-1.9 s, 90% under 2.4 s,
  over the two most recent drives.

Pattern so far over marks with transmission data (2026-11-16 and -17): the felt events follow a shift or
the converter locking by 1-2.5 s more often than a pedal blip (pedal blip near 2 marks of 6; shift or lock
before 4). Tapping usually lags the feeling by roughly half a second to a second and a half.

Public bulletin found: Kia TSB TRA095 "3.3L GDI 8AT TCU gear shift logic improvement" for Sorento (UMa)
covers 2019MY cars built 24 Jan to 24 Sep 2018 with acceleration delay and hesitation near 0 mph. This car's
transmission software reads U834 (`7E1 22 F189`); whether a newer version exists for a 2020 car is unknown.

## Monitor drive 2026-11-18 08:08 (17 min, three marks; build 2026-11-17-d)

- Marks 1 (282.5 s, 36 mph, 7th) and 2 (610.2 s, 48 mph, 8th): each 0.7-1.2 s after the accelerator went
  fully to rest (both sensors 31% to 14.9% within one sample) and stayed there; torque fell from about 41%
  to 0 within a second, converter slip jumped to about +200 rpm then went negative (coasting). No shift in the
  5 s before either. The phone shows no sudden change before the lift, only the gentle coasting decel after.
  Open: did the foot lift on purpose (then the felt event is the tip-out, the drive line going from pull to
  coast), or was the lift a reaction to something felt?
- Mark 3 (938.6 s, 23 mph), the clearest and strongest symptom so far (owner, 2026-11-18): pedal steady at
  33%, 4th gear with the converter unlocked (slip about 144 rpm, engine about 1400 rpm). By the next
  transmission reading at 938.63 (2.0 s later) it was in 5th with the converter locked (slip 28): the 4-5
  upshift and the converter lock happened together, at low engine speed, inside one gap between transmission
  readings, so the target-gear change was never seen. Engine 1404 to 1342 to 1240 rpm, actual torque 46 to
  42% while commanded throttle rose 18 to 19% (shift torque cut). Speed kept rising. The mark came right at
  the first 5th-gear reading. Same family as the shift- and lock-linked marks on 11-16 and 11-17.
- Sample rate fell during the drive: engine group every 0.27-0.30 s until about 650 s, then 0.44-0.79 s to the
  end with replies still complete. Not the background sweep (no burst then). Cause unknown (phone throttling?).
- Background sweep: 8 pauses (1.0-10.4 s), 131 IDs, all ended as designed.

## Monitor drive 2026-11-18 17:29 (11 min, three marks; phone still on build 2026-11-17-d)

Sampling very slow for most of the drive (median 0.75 s per request against 0.14 s normally, from about 60 s
in; replies complete). Not lined up with the sweep pauses. Cause still unknown.

- Mark 1 (46.8 s, 36 mph, 7th): pedal to rest at 45.97 and back at 46.69 (blip); converter went from about
  250 rpm slip to locked (58, then 1) between 45.75 and 46.93. A jolt was flagged at 44.4 during a tip-in.
- Mark 2 (68.2 s, 25 mph): tip-in after coasting, downshifts 7>6 (63.8, converter unlocked) then 5>4 requested
  at 67.4; mark 0.8 s later. Data too sparse (readings 1+ s apart) to say more.
- Mark 3 (484.6 s, 33 mph, 4th, pedal steady 33-36%, 2000 rpm): converter locked at 483.6-483.9 (slip 90 to
  -7.5, engine 2081 to 1982 rpm); mark 0.7 s later. No shift in the 6 s before.

## Converter lock-up versus marks, three drives (2026-11-17 16:50, 11-18 08:08, 11-18 17:29)

Lock-up counted when slip went from 60+ rpm to within 20 rpm in one transmission reading, same gear, lever D,
pedal above 18% around it. 17 such lock-ups; 7 were followed by a mark within 0.7-2.1 s, and 7 of the 9 marks
follow one (11-17 marks 1-3, 11-18 morning marks 1-3 via the lock at 280.6/608.4 and the 4-5 shift with lock,
11-18 evening mark 3). This reframes the 11-18 morning marks 1 and 2: the converter locked about 0.6-1 s
before the foot came off, so the lift may have been a reaction. Felt and unfelt lock-ups do not separate by
gear, rpm, pedal or slip before (at this sample rate).

Working hypothesis: the felt event is the torque converter clutch applying (harshly, some of the time), alone
or together with a shift. Next: a drive on build 2026-11-18-a (transmission every cycle) to see how fast the
slip falls at felt versus unfelt lock-ups.

## Monitor drives 2026-11-19 16:51 (24 min) and 2026-11-20 16:56 (6 min), build 2026-11-19-a

No marks in either drive. 15 lock-ups logged with phone scores, all mild: decel dip 0.5-0.9 m/s² on 11-19 (phone
noise there about 0.26 m/s², forward axis not learnt for the first 3 minutes; jolts of 9.8 and 21.5 m/s² at 127 and
179 s look like the phone being handled) and 0.1-0.3 m/s² on 11-20 (noise 0.11). These are the baseline for
unremarkable lock-ups.

Sample rate: 11-20 good (transmission 2.1-3.5/s, engine 1.4-2.4/s; median request 0.14 s engine, 0.17 s
transmission). 11-19 poor: 215 s of the 24 min were red-light sweep pauses (by design), and outside those the
requests had a long tail (median 0.20/0.26 s, 90% 0.72/0.95 s). Cause of the slow tail still unknown.

Detector gap found: with faster reads many lock-ups take several readings. Re-counting from the logs (slip 60+
to within 20 rpm in the same gear within 2 s): 21 lock-ups, the app logged 14. Two of the missed ones overshot
(slip went negative, to -224 rpm at 1281.6 s on 11-19 and -28 rpm at 251.9 s on 11-20), the signature of the
clutch grabbing hard. Build 2026-11-20-a follows the fall over several readings and logs the overshoot and the
fastest fall rate (rpm/s).

## Other computers: background sweep finds

| Module | ID | Reply (after 62 + ID) | Notes |
|---|---|---|---|
| 7D1 (likely ABS/ESC) | 0100 | `0C` | 1 byte |
| 7D1 | 0101 | `FF` | 1 byte |
| 7D1 | 0102 | `00` | 1 byte |
| 7D1 | 0104 | 41 bytes `FB C7 FF E0 12 00 00 00 01 E4 FF 00 ...` | live block candidate (one sample, parked) |

7D1 0103 does not answer; nothing else in 0100-01FF answers. B000-B00B: nothing (sweep at B00C on 2026-11-18 17:34).
7D1 0104 second sample (2026-11-18 evening, also stopped) differs from the first in bytes 5-6, 10, 26-27,
29-30, 32, 36-37 (counted after 62 01 04): it is live data. Bytes 26-27 and 29-30 look like signed 16-bit
values near zero (for example 0x0343/0x06A8 and 0xFFF6/0x0001): candidates for yaw rate, lateral acceleration
or steering angle. Needs readings while moving to decode.

2026-11-18 17:50: the old build (2026-11-17-d) restarted the finished transmission sweep when Start was tapped
in Sweep mode (it had reached 7E1 CED0 again, nothing new). Build 2026-11-18-c marks that repeat as finished.

## Open questions

1. What happens at the moment of the hesitation? Needs a Monitor drive or "Catch the hesitation" with a tap
   at the moment it happens.
2. Does it happen on cruise control (foot off the pedal)? If yes, the pedal and foot are ruled out.
3. Live data in the other computers (ABS/ESC, radar, body): sweep them, then rerun the on/off tests.
