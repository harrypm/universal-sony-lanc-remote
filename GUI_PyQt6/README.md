# Sony LANC remote GUI - PyQt6 port

A Python/PyQt6 port of the original LabVIEW `Sony LANC remote.vi` from the
parent project (`GUI/` folder).  It talks to the Arduino LANC-to-USB-serial
sketch (`../Arduino/arduino_lanc_nano-every.ino`) and provides the same kind of
service-remote functionality: camera status/time-code monitoring, transport and
camera control, an advanced command drop-down, manual hex command entry, and an
RM-95 style EEPROM / service-mode panel.

This replaces the closed-source LabVIEW 2023 + NI-VISA/NI-Serial stack with
free, cross-platform Python libraries (PyQt6 + pyserial).

## Files

- `lanc_protocol.py` - LANC command tables and 8-byte frame decoders
  (status byte 4, warning bits / guide code byte 5, counter / time code / data
  code / remain time bytes 6-7, and EEPROM service-frame decode).
- `lanc_serial_worker.py` - QThread serial worker (115200 baud, 8N1, no flow
  control).  Reads 8-byte frames + LF, thread-safe command sending.
- `sony_lanc_remote.py` - the main window GUI.  Run this.
- `requirements.txt` - Python dependencies.

## Requirements

- Python 3.8+
- PyQt6 (`pip3 install --user PyQt6`)
- pyserial (`pip3 install --user pyserial`)

Or: `pip3 install --user -r requirements.txt`

## Running

1. Build and flash the Arduino sketch to the Arduino Nano Every as described in
   the top-level README.  Connect the Arduino to the PC and the LANC device.
2. Run the GUI:
   ```
   python3 sony_lanc_remote.py
   ```
3. Select the Arduino's serial port at the startup prompt (Linux:
   `/dev/ttyACMx`, Windows: `COMx`) and click OK.
4. Once connected, the status panel shows the live 8-byte LANC frame, the
   decoded mode (byte 4), warnings (byte 5), the guide code, and the counter /
   time code / remain time / data code (bytes 6-7).  Use the buttons, the
   advanced drop-down, or manual 4-hex-char input to send commands.

## Serial wire format (matches the Arduino sketch)

- PC -> Arduino: 4 ASCII hex chars (2 bytes: byte0 sub-command + byte1 command)
  followed by a line feed, e.g. `1834\n` = byte0 0x18 (normal VTR/camera),
  byte1 0x34 (play).
- Arduino -> PC: 8 raw data bytes (one LANC frame) followed by `0x0A`, repeated
  at ~50 Hz (PAL) / ~60 Hz (NTSC).  The boot banner line is ignored.  Because a
  data byte may legally equal `0x0A`, the reader splits on `0x0A` and accepts
  only 8-byte segments as frames; this self-heals within one frame.

## Command groups

- Transport (byte0 = `0x18`): stop, play, pause, rewind, forward, record, still,
  eject, power off, frame advance, counter reset, data screen, and more in the
  drop-down.
- Camera (byte0 = `0x28`): zoom tele/wide slow & fast, focus, white balance,
  backlight, fader, DV rec start/stop, iris.
- Service / EEPROM (byte0 = `0xFF`, RM-95 style): Read, Page +/-, Address +/-,
  Data +/-, Store.  The returned frame is decoded as page (byte4 hi-nibble),
  address (byte6), data (byte7), ack (byte5 = `F0` read / `F1` write).

Hold-to-repeat: the Rewind / Forward (and zoom / focus) buttons resend the
command every ~150 ms while held, for continuous seek / variable-speed zoom.

## Protocol sources

Command tables and the byte 4/5/6/7 status layout are from the canonical
reference the original project follows: http://www.boehmel.de/lanc.htm

The EEPROM / service (RM-95) command set and returned-frame layout are from
L. Rosen's documented Arduino LANC<->RS232 interface
(https://hackster.io/L-Rosen/serial-to-lanc-control-l-70f735), which is the
same code base the Novgorod Arduino sketch is derived from.

## Notes / caveats

- The byte 4 status table in the public LANC documentation is incomplete; cells
  that are not documented fall back to the raw hex value.
- Time code is assembled across successive frames: guide 3 gives minutes/seconds
  and guide 4 gives hours, combined into `HH:MM:SS`.  Not all cameras emit every
  guide code; missing fields stay blank.
- Writing/storing to NVRAM via the service panel can make the device inoperable.
  Always read and note original values first.  Use at your own risk.
- This port reproduces the original's functionality from its README plus the
  verified protocol references; the exact LabVIEW button labels were not
  recoverable from the binary `.vi` files.  Confirm behaviour against real
  hardware before relying on it.
