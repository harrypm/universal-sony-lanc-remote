# Sony LANC remote GUI - PyQt6 port
A Python/PyQt6 implementation of the Sony LANC service-remote GUI. It talks to the Arduino LANC-to-USB-serial sketch (`../Arduino/arduino_lanc_nano-every.ino`) and provides transport/camera control, advanced command send, manual hex commands, status/timecode decode, and RM-95 style service/EEPROM controls.

## Files
- `sony_lanc_remote.py` - main GUI application entry point.
- `lanc_serial_worker.py` - serial I/O worker (115200 baud, 8N1, no flow control).
- `lanc_protocol.py` - command tables and 8-byte frame decode helpers.
- `assets/lanc_remote.ico` - extracted icon from original upstream Windows release executable.
- `assets/lanc_remote.png` - runtime icon used by the PyQt6 app.
- `assets/lanc_remote.icns` - macOS app bundle icon for PyInstaller builds.
- `test_headless.py` - headless smoke/regression checks.
- `requirements.txt` - Python dependencies.

## Requirements
- Python 3.8+
- `PyQt6`
- `pyserial`

Install:
`pip3 install --user -r requirements.txt`

## Running
1. Flash `../Arduino/arduino_lanc_nano-every.ino` to the Arduino Nano Every and connect the hardware.
2. Start the GUI:
   `python3 sony_lanc_remote.py`
3. Pick the serial port in the startup dialog.

The UI is currently organized into three tabs:
- `Deck` (transport controls + quick transport strip)
- `Camera` (camera controls)
- `Log` (separate live log view)

Default startup window size is `767x473` with a compact minimum size of `640x400`.

## Serial wire format
- PC -> Arduino: 4 ASCII hex chars (2 bytes) + newline. Example: `1834\n`.
- Arduino -> PC: 8 raw bytes + `0x0A` per frame at ~50/60 Hz.

## Release builds (GitHub Actions)
Workflow: `.github/workflows/build.yml`

Build/release behavior:
- Runs preflight headless test.
- Builds self-contained artifacts with PyInstaller for Linux, Windows, and macOS.
- Uses icon assets during packaging:
  - Windows EXE icon: `assets/lanc_remote.ico`
  - macOS app icon: `assets/lanc_remote.icns`
  - Bundles `assets/lanc_remote.png` for runtime app/window icon loading
- Publishes release assets on tag pushes (`v*`) or manual workflow dispatch with release enabled.

## Notes
- The app sets icon at both application and window level, and resolves icon paths for both source runs and PyInstaller bundles.
- Service/NVRAM write operations can alter camera configuration; verify values before storing.
- Validate behavior on real hardware before relying on capture/service operations.
