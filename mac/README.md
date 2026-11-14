# Mac bridge (parked use only)

    python3 fastobd_mac.py

Pair the OBDLink MX+ in macOS Bluetooth settings first (press the adapter's Connect button), and make sure
no phone is connected to it. The script opens a page at http://localhost:8765 showing the status and any
instruction from Claude. Claude drives it by dropping JSON commands into `bridge/cmd/`; results appear in
`bridge/out/` and recordings in `bridge/data/`. Only read requests are ever sent to the car.
