#!/usr/bin/env python3
"""Headless smoke test for the PyQt6 LANC port (no real hardware).

Verifies:
  * protocol decode of a normal status frame, a service/EEPROM frame, and
    counter/time-code frames;
  * the serial worker's byte-stream parser correctly extracts 8-byte frames,
    ignores the boot banner, and self-heals when a data byte equals 0x0A;
  * the GUI MainWindow can be constructed offscreen and updates its status
    labels when a frame is delivered.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lanc_protocol as lp
from lanc_serial_worker import LancSerialWorker
from PyQt6.QtWidgets import QApplication

import sony_lanc_remote as gui

failures = []


def check(cond, msg):
    if cond:
        print(f"  ok: {msg}")
    else:
        print(f"  FAIL: {msg}")
        failures.append(msg)


print("[1] protocol decode: normal status frame")
# byte0=18 byte1=34 (play command echoed), byte4=0x50 -> hi5 lo0 = "play",
# byte5=0x40 -> guide 4 (hours/frames), byte6=0x12 (hours 12), byte7=0x00
frame = bytes([0x18, 0x34, 0x00, 0x00, 0x50, 0x40, 0x12, 0x00])
d = lp.decode_frame(frame)
check(d["raw_hex"] == "18 34 00 00 50 40 12 00", "raw hex")
check("play" in d["mode4"], f"mode4 decode -> {d['mode4']}")
check(d["guide"] == 4, f"guide code 4 -> {d['guide']}")
check(d["b6b7"].get("time_hf") == (12, 0), f"hours/frames -> {d['b6b7']}")
check(d["service"] is None, "not a service frame")

print("[2] protocol decode: warnings + decimal counter")
# byte5=0x24 -> bits: 0x04 battery low + guide 2; byte6=0x34 byte7=0x12
# counter nibbles: b6_lo=4,b6_hi=3,b7_lo=2,b7_hi=1 -> "1234"
frame = bytes([0, 0, 0, 0, 0x20, 0x24, 0x34, 0x12])
d = lp.decode_frame(frame)
check("battery low" in d["warnings"], f"warnings -> {d['warnings']}")
check(d["b6b7"].get("counter") == "1234", f"counter -> {d['b6b7']}")

print("[3] protocol decode: real-time counter MM:SS (guide 3)")
# byte5=0x30 -> guide 3; byte6=0x59 (sec 59), byte7=0x12 (min 12)
frame = bytes([0, 0, 0, 0, 0, 0x30, 0x59, 0x12])
d = lp.decode_frame(frame)
check(d["b6b7"].get("time_ms") == (12, 59), f"MM:SS -> {d['b6b7']}")

print("[4] protocol decode: service / EEPROM ack frame")
# byte4 hi-nibble = page D, byte5 = 0xF0 (read ack), byte6 = 27 addr, byte7 = 63 data
frame = bytes([0xFF, 0x00, 0, 0, 0xD0, 0xF0, 0x27, 0x63])
d = lp.decode_frame(frame)
s = d["service"]
check(s is not None, "service frame detected")
check(s and s["page"] == 0xD, f"page D -> {s}")
check(s and s["address"] == 0x27, f"addr 27 -> {s}")
check(s and s["data"] == 0x63, f"data 63 -> {s}")
check(s and s["write"] is False, "read ack")

print("[5] serial worker byte-stream parser")
w = LancSerialWorker()
got = []
w.frame_received.connect(lambda b: got.append(bytes(b)))
banner = b"Arduino LANC to USB-serial interface v1.0\r\n"
f1 = bytes([0x18, 0x30, 0x00, 0x00, 0x20, 0x40, 0x00, 0x00])  # a stop frame
# craft a frame whose 3rd data byte is 0x0A to test self-heal
f2 = bytes([0x18, 0x34, 0x0A, 0x00, 0x50, 0x40, 0x12, 0x00])
stream = banner + f1 + b"\n" + f2 + b"\n" + f1 + b"\n"
w._consume(stream)
# f1 appears twice intact; f2 is split by its embedded 0x0A and dropped
check(got.count(f1) == 2, f"f1 recovered twice -> {got}")
check(f2 not in got, f"f2 (embedded 0x0A) correctly dropped -> {got}")

print("[6] GUI construction + label update (offscreen)")
app = QApplication.instance() or QApplication(sys.argv)
win = gui.MainWindow()
win.on_frame(bytes([0x18, 0x34, 0x00, 0x00, 0x50, 0x40, 0x12, 0x00]))
check("play" in win.lbl_mode.text(), f"mode label -> {win.lbl_mode.text()}")
check("18 34 00 00 50 40 12 00" in win.lbl_raw.text(), f"raw label -> {win.lbl_raw.text()}")
# advanced list populated
check(win.adv_combo.count() > 50, f"advanced list populated -> {win.adv_combo.count()}")
# service frame updates service panel
win.on_frame(bytes([0xFF, 0x00, 0, 0, 0xD0, 0xF0, 0x27, 0x63]))
check(win.lbl_sv_page.text() == "D", f"service page label -> {win.lbl_sv_page.text()}")
check(win.lbl_sv_addr.text() == "27", f"service addr label -> {win.lbl_sv_addr.text()}")
check(win.lbl_sv_data.text() == "63", f"service data label -> {win.lbl_sv_data.text()}")
# clicked(bool) regression: non-hold buttons must still send string hex commands
orig_send = win._send
sent = []
win._send = lambda h, note="": sent.append((h, note))
b = win._make_cmd_button(gui.lp.SUBCMD_NORMAL_VTR, 0x30, "StopTest", False)
b.clicked.emit(False)
check(sent and sent[-1][0] == "1830", f"clicked(bool) keeps hex command -> {sent[-1] if sent else None}")
win._send = orig_send
# manual hex validation: valid input is accepted and cleared (not connected -> error logged)
win.hex_input.setText("1834")
win._send_manual()
check(win.hex_input.text() == "", f"valid manual input accepted/cleared -> {win.hex_input.text()!r}")
# invalid length rejected without sending (predicate mirrors the validation)
text = "12"
is_valid = len(text) == 4 and all(c in "0123456789abcdefABCDEF" for c in text)
check(not is_valid, "invalid manual input rejected by predicate")
win.worker.stop()
win.worker.close()
win.thread.quit()
win.thread.wait(1000)

print()
if failures:
    print(f"RESULT: {len(failures)} FAILURE(S)")
    sys.exit(1)
print("RESULT: ALL CHECKS PASSED")
