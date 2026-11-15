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
`01F2` exists but answers "conditions not correct". Guessed IDs `0101 0102 E001 E002 1101 1940 1104 1944
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

## Logging rates on this phone and adapter

- Mode 01 multi-PID groups to the engine only: about 8 samples/s per channel with no other blocks.
- Monitor with the transmission block every other cycle: about 1.5 samples/s per pedal channel and
  0.8/s for the transmission block (2026-11-14 15:06, broadcast). Expected to improve with engine-only
  polling; not yet measured.
- 39 service-22 blocks per cycle: one pass every ~6 s (each block 0.05-0.24 s).

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
| 2026-11-14 18:10 | obd_test_lightmodes | Only low-beam-on visible; full beam, fog, parking lights not |

## Open questions

1. What happens at the moment of the hesitation? Needs a Monitor drive or "Catch the hesitation" with a tap
   at the moment it happens.
2. Does it happen on cruise control (foot off the pedal)? If yes, the pedal and foot are ruled out.
3. Other modules (ABS/ESC, body, steering) have not been discovered yet. The Mac bridge's `discover` op
   would list which addresses answer; parked only.
