#!/usr/bin/env python3
"""
Sony LANC protocol command tables and frame decoders.

Data sources (verified, not guessed):
  * Transport / camera command tables and byte 4/5/6/7 status layout:
      http://www.boehmel.de/lanc.htm  (the reference the original project follows)
  * EEPROM / service (RM-95) command set and returned-frame layout:
      L. Rosen's documented Arduino LANC<->RS232 interface
      (https://hackster.io/L-Rosen/serial-to-lanc-control-l-70f735) - the same
      code base the Novgorod Arduino sketch is derived from.

Wire format used by the Arduino sketch (arduino_lanc_nano-every.ino):
  * PC -> Arduino: 4 ASCII hex chars (2 bytes: byte0 sub-command, byte1 command)
    followed by a line feed.  e.g. "1834\\n" = byte0 0x18, byte1 0x34 (play).
  * Arduino -> PC: 8 raw data bytes (one LANC frame) followed by 0x0A (LF).
    Sent at 115200 baud, 8N1, no flow control.  Frames repeat at ~50 Hz (PAL)
    or ~60 Hz (NTSC).

LANC frame byte assignment:
  byte0/byte1 : command slot (written by the controller / echoed back)
  byte2/byte3 : tuner / channel
  byte4       : device status code
  byte5       : warning bits (low nibble) + guide code for byte6/7 (high nibble)
  byte6/byte7 : counter / time code / data code / remain time (per guide code)

EEPROM service frame (when byte0=0xFF commands are sent):
  byte4 hi-nibble = page, byte5 = ack (0xF0 read / 0xF1 write),
  byte6 = address, byte7 = data.
"""

# ---------------------------------------------------------------------------
# Sub-command values for byte0
# ---------------------------------------------------------------------------
SUBCMD_NORMAL_VTR = 0x18   # Normal command to VTR or video camera
SUBCMD_SPECIAL_CAM = 0x28  # Special command to video camera
SUBCMD_SPECIAL_VTR = 0x38  # Special command to VTR
SUBCMD_NORMAL_STILL = 0x1E  # Normal command to still video camera
SUBCMD_SERVICE = 0xFF      # EEPROM / service (RM-95) commands

BAUDRATE = 115200  # matches Serial.begin(115200) in the Arduino sketch


# ---------------------------------------------------------------------------
# Command tables.  Each entry: (byte1, "label").  byte0 is the sub-command.
# ---------------------------------------------------------------------------

# Transport / VTR commands (byte0 = 0x18) - from boehmel.de + RM-95 eavesdrop.
TRANSPORT_COMMANDS = [
    (0x30, "Stop"),
    (0x34, "Play"),
    (0x32, "Pause"),
    (0x33, "Rec start/stop"),
    (0x3A, "Record"),
    (0x36, "Rewind"),
    (0x38, "Forward"),
    (0x40, "Still"),
    (0x2C, "Eject"),
    (0x5E, "Power off"),
    (0x54, "TV/VTR"),
    (0x5A, "VTR"),
    (0x60, "Rev frame"),
    (0x62, "Fwd frame"),
    (0x66, "x1"),
    (0x28, "x2"),
    (0x46, "x1/5 (vis. scan)"),
    (0x44, "x1/10"),
    (0x4C, "x9"),
    (0x4A, "x14"),
    (0x7A, "Slow +"),
    (0x7C, "Slow -"),
    (0x50, "Search -"),
    (0x52, "Search +"),
    (0x65, "Edit search -"),
    (0x67, "Edit search +"),
    (0x69, "Rec review"),
    (0x74, "Rew + play"),
    (0xFA, "High-speed rew"),
    (0x8C, "Counter reset"),
    (0x8E, "Zero mem"),
    (0x88, "Tracking/fine +"),
    (0x8A, "Tracking/fine -"),
    (0x4E, "Tracking auto/manual"),
    (0x6E, "Tracking normal"),
    (0x9A, "Menu"),
    (0x84, "Menu up"),
    (0x86, "Menu down"),
    (0xC2, "Menu right / next"),
    (0xC4, "Menu left"),
    (0xA2, "Execute"),
    (0x82, "Display mode"),
    (0xB4, "Counter display / data screen"),
    (0xB2, "Goto zero / tape return"),
    (0x98, "Data code / goto"),
    (0xC0, "Timer set"),
    (0xC6, "Timer clear"),
    (0xCA, "Timer record"),
    (0xD0, "Audio dub"),
    (0xD4, "Edit assemble"),
    (0xD6, "Edit mark"),
    (0xD8, "Synchro edit"),
    (0x78, "AUX"),
    (0x2A, "Mode movie/still"),
    (0x2E, "Main/sub"),
    (0x9E, "Input select"),
    (0xB0, "Tape speed"),
    (0xA6, "Index"),
    (0xAC, "Index search +"),
    (0xAE, "Index search -"),
    (0x90, "Index mark"),
    (0x92, "Index erase"),
    (0xDE, "Speed +"),
    (0xE0, "Speed -"),
    (0x6C, "Sleep"),
]

# Camera special commands (byte0 = 0x28) - from boehmel.de + RM-95 eavesdrop.
CAMERA_COMMANDS = [
    (0x35, "Zoom Tele slow"),
    (0x37, "Zoom Wide slow"),
    (0x39, "Zoom Tele fast"),
    (0x3B, "Zoom Wide fast"),
    (0x41, "Focus / AF on-off"),
    (0x45, "Focus far"),
    (0x47, "Focus near"),
    (0x49, "White balance toggle"),
    (0x77, "White balance reset"),
    (0x4B, "Backlight (not DV)"),
    (0x51, "Backlight (DV)"),
    (0x53, "Iris more close"),
    (0x55, "Iris more open"),
    (0xAF, "Iris auto"),
    (0x25, "Fader"),
    (0x27, "Rec start (DV)"),
    (0x29, "Rec stop (DV)"),
    (0x61, "Shutter"),
    (0x85, "Memory impose"),
    (0x87, "Color / Mode"),
    (0x89, "Superimpose"),
    (0x21, "Grid (AVCHD)"),
]

# EEPROM / service (RM-95) commands (byte0 = 0xFF) - from L. Rosen docs.
SERVICE_COMMANDS = [
    (0x00, "Read (page:addr:data)"),
    (0x67, "Page +"),
    (0x65, "Page -"),
    (0x38, "Address +"),
    (0x36, "Address -"),
    (0x34, "Data +"),
    (0x30, "Data -"),
    (0x32, "Store (write to NVRAM)"),
]


def command_hex(byte0: int, byte1: int) -> str:
    """Return the 4-hex-char command string for the Arduino."""
    return f"{byte0:02X}{byte1:02X}"


def build_advanced_list():
    """Build the advanced drop-down list: (hex4, label, category)."""
    items = []
    for b1, label in TRANSPORT_COMMANDS:
        items.append((command_hex(SUBCMD_NORMAL_VTR, b1), f"{label} [VTR]", "VTR"))
    for b1, label in CAMERA_COMMANDS:
        items.append((command_hex(SUBCMD_SPECIAL_CAM, b1), f"{label} [CAM]", "CAM"))
    for b1, label in SERVICE_COMMANDS:
        items.append((command_hex(SUBCMD_SERVICE, b1), f"{label} [SERVICE]", "SERVICE"))
    return items


# ---------------------------------------------------------------------------
# byte4 status decode.  boehmel.de table is indexed (hi-nibble, lo-nibble).
# The documented table is incomplete; unknown cells fall back to raw hex.
# ---------------------------------------------------------------------------
_STATUS4 = {
    # lo = 0
    (0, 0): "initial", (1, 0): "is eject", (2, 0): "stop", (3, 0): "fwd",
    (4, 0): "rec", (5, 0): "play", (6, 0): "play/pause fwd", (7, 0): "AL insert",
    # lo = 1
    (0, 1): "dew / cass. out", (1, 1): "load", (2, 1): "rec/pause",
    (3, 1): "frame fwd", (4, 1): "AL ins-pause",
    # lo = 2
    (0, 2): "ejecting", (1, 2): "cassette busy", (2, 2): "timer-rec",
    (3, 2): "x1 fwd", (4, 2): "1/5 fwd", (5, 2): "AR insert",
    # lo = 3
    (0, 3): "unload", (1, 3): "low-battery", (2, 3): "go zero/play f.",
    (3, 3): "timer-rec s.", (4, 3): "x1 rev", (5, 3): "1/5 rev", (6, 3): "AR ins-pause",
    # lo = 4
    (0, 4): "dew stop", (1, 4): "fwd mem stop", (2, 4): "AV insert",
    (3, 4): "cue", (4, 4): "1/10 fwd", (5, 4): "AL+V insert",
    # lo = 5
    (0, 5): "emergency", (1, 5): "AV ins.-pause", (2, 5): "rev",
    (3, 5): "1/10 rev", (4, 5): "AL+V ins-ps",
    # lo = 6
    (0, 6): "tape end", (1, 6): "video insert", (2, 6): "x2/x3 fwd",
    (3, 6): "frame fwd", (4, 6): "AR+V insert",
    # lo = 7
    (0, 7): "tape top", (1, 7): "video ins.-ps", (2, 7): "x2/x3 rev",
    (3, 7): "frame rev", (4, 7): "AL+R ins-ps",
    # lo = 8
    (0, 8): "rew", (1, 8): "audio dub", (2, 8): "edit search+", (3, 8): "x9 fwd",
    # lo = 9
    (0, 9): "stp after zero", (1, 9): "a.dub pause", (2, 9): "edit search-",
    (3, 9): "x9 rev", (4, 9): "play/pause rev",
}


def decode_status_byte4(b4: int) -> str:
    hi = (b4 >> 4) & 0xF
    lo = b4 & 0xF
    label = _STATUS4.get((hi, lo))
    if label:
        return f"{label} (0x{b4:02X})"
    return f"mode 0x{b4:02X} (hi={hi:X} lo={lo:X})"


# ---------------------------------------------------------------------------
# byte5 warnings + guide code
# ---------------------------------------------------------------------------
def decode_warnings_byte5(b5: int):
    """Return (list_of_warning_strings, guide_code_int)."""
    warnings = []
    if b5 & 0x01:
        warnings.append("invalid code")
    if b5 & 0x02:
        warnings.append("rec protect / tape pre-end")
    if b5 & 0x04:
        warnings.append("battery low")
    if b5 & 0x08:
        warnings.append("zero mem / zero found")
    guide = (b5 >> 4) & 0xF
    return warnings, guide


_GUIDE_LABELS = {
    0: "Status V8/Hi8",
    1: "Status V8/Hi8",
    2: "decimal counter",
    3: "real-time counter (min/sec)",
    4: "real-time counter (hours/frames)",
    5: "remain time",
    6: "Status",
    7: "Status Betamax/DV",
    8: "Data",
    9: "Data code (date/time)",
    0xA: "Data code (date/time)",
    0xB: "Data code",
}


def guide_label(guide: int) -> str:
    return _GUIDE_LABELS.get(guide, f"guide {guide:X}")


def _bcd(nibble: int):
    """Return BCD digit 0-9, or None if blank (0xF)."""
    if 0 <= nibble <= 9:
        return nibble
    return None


def decode_counter_timecode(b6: int, b7: int, guide: int):
    """Decode bytes 6/7 according to the guide code.

    Returns a dict that may contain: counter, time_ms (mm,ss), time_hf (hh,ff),
    rctc, sign, remain (hh,mm), data (dict).  Keys are present only when the
    guide code provides them.
    """
    out = {}
    b6_lo, b6_hi = b6 & 0xF, (b6 >> 4) & 0xF
    b7_lo, b7_hi = b7 & 0xF, (b7 >> 4) & 0xF

    if guide == 2:  # decimal counter: ones, tens, hundreds, thousands
        d = [_bcd(b6_lo), _bcd(b6_hi), _bcd(b7_lo), _bcd(b7_hi)]
        if all(x is not None for x in d):
            out["counter"] = f"{d[3]}{d[2]}{d[1]}{d[0]}"
        else:
            out["counter"] = "----"

    elif guide == 3:  # real-time counter: sec ones/tens, min ones/tens
        s_o, s_t = _bcd(b6_lo), _bcd(b6_hi)
        m_o, m_t = _bcd(b7_lo), _bcd(b7_hi)
        if None in (s_o, s_t, m_o, m_t):
            out["time_ms"] = None
        else:
            out["time_ms"] = (m_t * 10 + m_o, s_t * 10 + s_o)

    elif guide == 4:  # hours ones/tens, frames ones/tens (or day), RCTC, sign
        h_o, h_t = _bcd(b6_lo), _bcd(b6_hi)
        f_o = _bcd(b7_lo)
        out["rctc"] = bool(b7_hi & 0x4)
        out["sign"] = bool(b7_hi & 0x8)
        if None in (h_o, h_t, f_o):
            out["time_hf"] = None
        else:
            f_t = (b7_hi & 0x3)
            out["time_hf"] = (h_t * 10 + h_o, f_t * 10 + f_o)

    elif guide == 5:  # remain time: min ones/tens, hours ones/tens
        m_o, m_t = _bcd(b6_lo), _bcd(b6_hi)
        h_o, h_t = _bcd(b7_lo), _bcd(b7_hi)
        calc = not (b7_hi & 0x4)  # 0 = calculating on some devices
        if None in (m_o, m_t, h_o, h_t):
            out["remain"] = None
        else:
            out["remain"] = (h_t * 10 + h_o, m_t * 10 + m_o)
        out["remain_calculating"] = not calc

    elif guide in (9, 0xA):  # data code (date + time), interleaved over frames
        # guide 9: year ones / hour ones / year tens / hour tens
        # guide A: month ones / minute ones / month tens / minute tens
        if guide == 9:
            out["data"] = {
                "year_ones": _bcd(b6_lo), "hour_ones": _bcd(b6_hi),
                "year_tens": _bcd(b7_lo), "hour_tens": _bcd(b7_hi),
            }
        else:
            out["data"] = {
                "month_ones": _bcd(b6_lo), "minute_ones": _bcd(b6_hi),
                "month_tens": _bcd(b7_lo), "minute_tens": _bcd(b7_hi),
            }

    return out


# ---------------------------------------------------------------------------
# Service / EEPROM frame decode
# ---------------------------------------------------------------------------
def decode_service(frame: bytes):
    """If frame looks like an EEPROM service reply, return dict; else None.

    A service reply has byte5 == 0xF0 (read ack) or 0xF1 (write ack).  Page is
    the high nibble of byte4, address is byte6, data is byte7.
    """
    if len(frame) != 8:
        return None
    b5 = frame[5]
    if b5 in (0xF0, 0xF1):
        return {
            "page": (frame[4] >> 4) & 0xF,
            "address": frame[6],
            "data": frame[7],
            "ack": b5,
            "write": b5 == 0xF1,
        }
    return None


# ---------------------------------------------------------------------------
# Full frame decode
# ---------------------------------------------------------------------------
def decode_frame(frame: bytes) -> dict:
    """Decode an 8-byte LANC frame into a structured dict."""
    d = {
        "raw": frame,
        "raw_hex": " ".join(f"{b:02X}" for b in frame),
        "byte0": frame[0],
        "byte1": frame[1],
        "mode4": decode_status_byte4(frame[4]),
        "warnings": [],
        "guide": 0,
        "guide_label": "",
        "b6b7": {},
        "service": decode_service(frame),
    }
    warnings, guide = decode_warnings_byte5(frame[5])
    d["warnings"] = warnings
    d["guide"] = guide
    d["guide_label"] = guide_label(guide)
    d["b6b7"] = decode_counter_timecode(frame[6], frame[7], guide)
    return d
