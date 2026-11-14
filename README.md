# Fast OBD Logger

A single-page web app that logs OBD-II data from a **BLE ELM327-style dongle** at a much higher rate than most phone apps, using Web Bluetooth.

**Use it:** open the published page in **Chrome on Android** (or desktop Chrome), tap *Connect dongle*, pick your adapter, then *Start logging*.

## Modes
- **Normal**: fast logging of standard channels (pedal, throttle, torque, RPM, speed, etc.).
- **Exploratory**: with the car parked, *Sweep* tests an editable list of read-only requests (services 01/09/22) against ECU 1 (7E0) or ECU 2 (7E1) and saves a report. *Start logging* then records the raw replies that answered, alongside pedal, RPM and speed, so unknown bytes can be matched to gear changes offline.

## Features
- Batches up to 6 PIDs per request (falls back to single requests if the ECU doesn't support it)
- Optional ECU targeting (engine ECU 7E0 / second ECU 7E1) on 11-bit CAN
- Polls pedal D/E, commanded throttle, torque, RPM and speed every cycle; rotates in the rest
- Live plot, auto-detection of brief pedal-signal dips, and an "I FELT IT" marker button
- Read-only probe (services 01, 09, 22 only) for checking what an ECU answers, with the car parked
- CSV export (with phone GPS and accelerometer), plus a recoverable autosave

## Notes
- Web Bluetooth needs a secure context (https), so open the GitHub Pages URL, not a local file.
- iOS Safari does not support Web Bluetooth. Classic-Bluetooth (non-BLE) dongles are not supported.
- Only reads standard Mode 01 data. It sends no commands that change anything on the car.

## Phone apps (for classic-Bluetooth dongles like the OBDLink MX+)
The same page runs inside two thin native shells that only move bytes to the dongle:
- `android/`: classic Bluetooth SPP. A GitHub Action builds the APK and publishes it under Releases ("Android app (latest)"); sideload it.
- `ios/`: Apple MFi (ExternalAccessory). See `ios/README.md`; build with XcodeGen + Xcode.
