# Fast OBD Logger

A single-page web app that logs OBD-II data from a **BLE ELM327-style dongle** at a much higher rate than most phone apps, using Web Bluetooth.

**Use it:** open the published page in **Chrome on Android** (or desktop Chrome), tap *Connect dongle*, pick your adapter, then *Start logging*.

## Features
- Batches up to 6 PIDs per request (falls back to single requests if the ECU doesn't support it)
- Optional ECU targeting (engine ECU 7E0 / second ECU 7E1) on 11-bit CAN
- Polls pedal D/E, commanded throttle, torque, RPM and speed every cycle; rotates in the rest
- Live plot, auto-detection of brief pedal-signal dips, and an "I FELT IT" marker button
- CSV export (with phone GPS and accelerometer), plus a recoverable autosave

## Notes
- Web Bluetooth needs a secure context (https), so open the GitHub Pages URL, not a local file.
- iOS Safari does not support Web Bluetooth. Classic-Bluetooth (non-BLE) dongles are not supported.
- Only reads standard Mode 01 data. It sends no commands that change anything on the car.
