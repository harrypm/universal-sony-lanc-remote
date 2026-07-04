#!/usr/bin/env python3
"""Sony LANC remote - PyQt6 port of the LabVIEW 'Sony LANC remote.vi'.

A GUI that talks to the Arduino LANC-to-USB-serial interface
(arduino_lanc_nano-every.ino) over a serial port at 115200 baud.  It monitors
camera status / time code, sends transport and camera commands, exposes the
advanced command set via a drop-down, accepts manual 4-hex-char commands, and
provides an RM-95 style EEPROM / service-mode panel.

Protocol details and data sources are documented in lanc_protocol.py.

Run:
    python3 sony_lanc_remote.py
"""

import os
import sys

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QGroupBox, QGridLayout, QVBoxLayout,
    QHBoxLayout, QPushButton, QLabel, QComboBox, QLineEdit, QPlainTextEdit,
    QDialog, QDialogButtonBox, QMessageBox, QSizePolicy, QTabWidget,
)

import lanc_protocol as lp
from lanc_serial_worker import LancSerialWorker, list_serial_ports, start_worker


# Transport buttons shown as primary controls.  (byte0, byte1, label, hold?)
# hold=True means press-and-hold repeats the command (seek / variable zoom).
TRANSPORT_BUTTONS = [
    (lp.SUBCMD_NORMAL_VTR, 0x36, "<< Rew", True),
    (lp.SUBCMD_NORMAL_VTR, 0x30, "Stop", False),
    (lp.SUBCMD_NORMAL_VTR, 0x32, "Pause", False),
    (lp.SUBCMD_NORMAL_VTR, 0x34, "Play", False),
    (lp.SUBCMD_NORMAL_VTR, 0x38, "Fwd >>", True),
    (lp.SUBCMD_NORMAL_VTR, 0x40, "Still", False),
    (lp.SUBCMD_NORMAL_VTR, 0x33, "Rec start/stop", False),
    (lp.SUBCMD_NORMAL_VTR, 0x3A, "Record", False),
    (lp.SUBCMD_NORMAL_VTR, 0x2C, "Eject", False),
    (lp.SUBCMD_NORMAL_VTR, 0x5E, "Power off", False),
    (lp.SUBCMD_NORMAL_VTR, 0x54, "TV/VTR", False),
    (lp.SUBCMD_NORMAL_VTR, 0x60, "Frame <", False),
    (lp.SUBCMD_NORMAL_VTR, 0x62, "Frame >", False),
    (lp.SUBCMD_NORMAL_VTR, 0x8C, "Counter reset", False),
    (lp.SUBCMD_NORMAL_VTR, 0xB4, "Data screen", False),
]

CAMERA_BUTTONS = [
    (lp.SUBCMD_SPECIAL_CAM, 0x35, "Zoom T slow", True),
    (lp.SUBCMD_SPECIAL_CAM, 0x39, "Zoom T fast", True),
    (lp.SUBCMD_SPECIAL_CAM, 0x37, "Zoom W slow", True),
    (lp.SUBCMD_SPECIAL_CAM, 0x3B, "Zoom W fast", True),
    (lp.SUBCMD_SPECIAL_CAM, 0x41, "Focus/AF", False),
    (lp.SUBCMD_SPECIAL_CAM, 0x45, "Focus far", True),
    (lp.SUBCMD_SPECIAL_CAM, 0x47, "Focus near", True),
    (lp.SUBCMD_SPECIAL_CAM, 0x49, "WB toggle", False),
    (lp.SUBCMD_SPECIAL_CAM, 0x77, "WB reset", False),
    (lp.SUBCMD_SPECIAL_CAM, 0x4B, "Backlight", False),
    (lp.SUBCMD_SPECIAL_CAM, 0x25, "Fader", False),
    (lp.SUBCMD_SPECIAL_CAM, 0x27, "Rec start (DV)", False),
    (lp.SUBCMD_SPECIAL_CAM, 0x29, "Rec stop (DV)", False),
]

HOLD_REPEAT_MS = 150  # repeat interval for press-and-hold buttons
COMPACT_FONT_PT = 8
COMPACT_BUTTON_H = 20
COMPACT_LOG_H = 64

# Program keypad: 1..16 map to command bytes 0x00..0x1E in steps of 2.
KEYPAD_NUMBERS = [
    ("1", 0x00), ("2", 0x02), ("3", 0x04), ("4", 0x06),
    ("5", 0x08), ("6", 0x0A), ("7", 0x0C), ("8", 0x0E),
    ("9", 0x10), ("10", 0x12), ("11", 0x14), ("12", 0x16),
    ("13", 0x18), ("14", 0x1A), ("15", 0x1C), ("16", 0x1E),
]

# RM-95 style keypad helpers.
KEYPAD_EXTRA = [
    ("Menu", 0x9A),
    ("Enter", 0xA2),
    ("+", 0x20),      # program+
    ("-", 0x22),      # program-
    ("\u2190", 0xC4),  # menu left
    ("\u2192", 0xC2),  # menu right / next
    ("\u2191", 0x84),  # menu up
    ("\u2193", 0x86),  # menu down
]

# One-row icon transport strip (RM-95-like quick controls).
ICON_TRANSPORT = [
    ("\u23ea", 0x36, True),   # rew
    ("\u23f8", 0x32, False),  # pause
    ("\u25b6", 0x34, False),  # play
    ("\u23f9", 0x30, False),  # stop
    ("\u23fa", 0x3A, False),  # rec
    ("\u23e9", 0x38, True),   # fwd
    ("\u23ee", 0x60, False),  # frame <
    ("\u23ed", 0x62, False),  # frame >
    ("\u23cf", 0x2C, False),  # eject
]


def resource_path(*parts: str) -> str:
    """Return an absolute path to a bundled/runtime resource."""
    base_dir = getattr(sys, "_MEIPASS", None)
    if base_dir is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, *parts)


class PortDialog(QDialog):
    """Startup prompt to select the Arduino's serial port."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Arduino COM port")
        self.setMinimumWidth(420)
        self.selected_port = None

        v = QVBoxLayout(self)
        v.addWidget(QLabel("Select the Arduino Nano Every's serial port:"))

        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.refresh()
        v.addWidget(self.combo)

        ref = QPushButton("Refresh")
        ref.clicked.connect(self.refresh)
        v.addWidget(ref)

        v.addWidget(QLabel(f"Fixed serial settings: {lp.BAUDRATE} baud, 8N1, no flow control"))

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def refresh(self):
        prev = self.combo.currentText().strip()
        self.combo.clear()
        ports = list_serial_ports()
        if not ports:
            self.combo.addItem("(no ports found)")
            self.combo.setEnabled(False)
            return
        self.combo.setEnabled(True)
        for dev, desc, hwid in ports:
            self.combo.addItem(f"{dev}  -  {desc}", dev)
        # restore previous selection if still present
        if prev:
            for i in range(self.combo.count()):
                if self.combo.itemData(i) == prev or self.combo.itemText(i).startswith(prev):
                    self.combo.setCurrentIndex(i)
                    break

    def accept(self):
        idx = self.combo.currentIndex()
        data = self.combo.itemData(idx)
        if data is None:
            # editable text fallback
            data = self.combo.currentText().split(" ")[0].strip()
        if not data:
            QMessageBox.warning(self, "No port", "Please select a port.")
            return
        self.selected_port = data
        super().accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sony LANC remote (PyQt6 port)")
        self._set_window_icon()
        self.resize(767, 473)
        self.setMinimumSize(640, 400)

        # ---- serial worker + thread (one persistent loop for the session) ----
        self.worker = LancSerialWorker()
        self.thread = start_worker(self.worker)
        self.worker.frame_received.connect(self.on_frame)
        self.worker.info_received.connect(self.on_info)
        self.worker.status_message.connect(self.on_status)
        self.worker.error_occurred.connect(self.on_error)
        self.worker.connected_changed.connect(self.on_connected_changed)

        # held-seek timers: button -> QTimer
        self._hold_timers = {}

        # time-code assembly state
        self._tc_hh = None
        self._tc_mm = None
        self._tc_ss = None
        self._tc_sign = False
        self._data_year = None
        self._data_month = None
        self._data_day = None
        self._data_hour = None
        self._data_minute = None
        self._apply_compact_theme()

        self._build_ui()

    def _set_window_icon(self):
        icon_path = resource_path("assets", "lanc_remote.png")
        if os.path.exists(icon_path):
            icon = QIcon(icon_path)
            if not icon.isNull():
                self.setWindowIcon(icon)

    # ------------------------------------------------------------------ UI
    def _apply_compact_theme(self):
        self.setStyleSheet(f"""
            QWidget {{
                font-size: {COMPACT_FONT_PT}pt;
            }}
            QGroupBox {{
                margin-top: 1.0em;
                padding: 2px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 6px;
                top: 0px;
                padding: 0 2px 0 2px;
            }}
            QPushButton {{
                min-height: {COMPACT_BUTTON_H}px;
                padding: 0 1px;
            }}
            QComboBox, QLineEdit {{
                min-height: {COMPACT_BUTTON_H}px;
                padding: 0 2px;
            }}
            QPlainTextEdit {{
                padding: 2px;
            }}
        """)
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(4)

        # ---- connection bar ----
        bar = QHBoxLayout()
        bar.setSpacing(4)
        self.lbl_status = QLabel("Not connected")
        self.lbl_status.setStyleSheet("font-weight:bold; padding:2px 6px;")
        bar.addWidget(self.lbl_status)
        bar.addStretch()
        bar.addWidget(QLabel("Port:"))
        self.port_combo = QComboBox()
        self.port_combo.setEditable(True)
        self.port_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.port_combo.setMinimumContentsLength(12)
        self.port_combo.setMinimumWidth(120)
        self.port_combo.setMaximumWidth(220)
        self.port_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        bar.addWidget(self.port_combo)
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self.refresh_ports)
        bar.addWidget(self.btn_refresh)
        self.btn_connect = QPushButton("Connect")
        self.btn_connect.clicked.connect(self.connect_selected)
        bar.addWidget(self.btn_connect)
        self.btn_disconnect = QPushButton("Disconnect")
        self.btn_disconnect.clicked.connect(lambda: self.worker.close())
        bar.addWidget(self.btn_disconnect)
        outer.addLayout(bar)
        # ---- top row: keypad + command + service ----
        top = QHBoxLayout()
        top.setSpacing(4)
        top.addWidget(self._build_keypad_group())
        top.addWidget(self._build_command_group())
        top.addWidget(self._build_service_group())
        top.addStretch(1)
        outer.addLayout(top)
        # ---- deck/camera/log tabs ----
        outer.addWidget(self._build_control_tabs())

        # ---- status panel ----
        outer.addWidget(self._build_status_panel())

        self.refresh_ports()

    def _build_keypad_group(self):
        g = QGroupBox("Keypad")
        gl = QGridLayout(g)
        gl.setSpacing(2)
        gl.setContentsMargins(3, 3, 3, 3)
        gl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        for i, (label, cmd) in enumerate(KEYPAD_NUMBERS):
            b = self._make_cmd_button(lp.SUBCMD_NORMAL_VTR, cmd, label, False)
            b.setFixedHeight(COMPACT_BUTTON_H + 2)
            b.setFixedWidth(31 if len(label) <= 2 else 35)
            gl.addWidget(b, i // 8, i % 8)

        for i, (label, cmd) in enumerate(KEYPAD_EXTRA[:4]):
            b = self._make_cmd_button(lp.SUBCMD_NORMAL_VTR, cmd, label, False)
            b.setFixedHeight(COMPACT_BUTTON_H + 3)
            b.setFixedWidth(66)
            gl.addWidget(b, 2, i * 2, 1, 2)
        dpad = [KEYPAD_EXTRA[4], KEYPAD_EXTRA[7], KEYPAD_EXTRA[5], KEYPAD_EXTRA[6]]
        for i, (label, cmd) in enumerate(dpad):
            b = self._make_cmd_button(lp.SUBCMD_NORMAL_VTR, cmd, label, False)
            b.setFixedHeight(COMPACT_BUTTON_H + 3)
            b.setFixedWidth(66)
            gl.addWidget(b, 3, i * 2, 1, 2)
        return g

    def _build_status_panel(self):
        g = QGroupBox("Status")
        gl = QGridLayout(g)
        gl.setContentsMargins(4, 4, 4, 4)
        gl.setHorizontalSpacing(6)
        gl.setVerticalSpacing(2)
        mono = QFont("Monospace")
        mono.setStyleHint(QFont.StyleHint.TypeWriter)

        def mk(text="", min_w=52, max_w=140, expanding=False):
            l = QLabel(text)
            l.setFont(mono)
            l.setMinimumWidth(min_w)
            l.setMaximumWidth(max_w)
            l.setStyleSheet("border:1px solid palette(mid); padding:1px 4px;")
            if expanding:
                l.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            else:
                l.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            l.setMinimumHeight(COMPACT_BUTTON_H)
            l.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            return l
        self.lbl_raw = mk("-- -- -- -- -- -- -- --", min_w=150, max_w=260, expanding=True)
        self.lbl_mode = mk("-")
        self.lbl_warn = mk("-", min_w=90, max_w=180, expanding=True)
        self.lbl_guide = mk("-", min_w=90, max_w=180, expanding=True)
        self.lbl_counter = mk("----")
        self.lbl_timecode = mk("--:--:--")
        self.lbl_remain = mk("--:--")
        self.lbl_datacode = mk("----")

        gl.addWidget(QLabel("Latest frame"), 0, 0)
        gl.addWidget(self.lbl_raw, 0, 1, 1, 5)

        gl.addWidget(QLabel("Status"), 1, 0)
        gl.addWidget(self.lbl_mode, 1, 1)
        gl.addWidget(QLabel("Warnings"), 1, 2)
        gl.addWidget(self.lbl_warn, 1, 3, 1, 3)

        gl.addWidget(QLabel("Counter"), 2, 0)
        gl.addWidget(self.lbl_counter, 2, 1)
        gl.addWidget(QLabel("Time code"), 2, 2)
        gl.addWidget(self.lbl_timecode, 2, 3)
        gl.addWidget(QLabel("Remain"), 2, 4)
        gl.addWidget(self.lbl_remain, 2, 5)

        gl.addWidget(QLabel("Guide"), 3, 0)
        gl.addWidget(self.lbl_guide, 3, 1, 1, 3)
        gl.addWidget(QLabel("Data code"), 3, 4)
        gl.addWidget(self.lbl_datacode, 3, 5)
        return g

    def _make_cmd_button(self, byte0, byte1, label, hold):
        b = QPushButton(label)
        b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        b.setMinimumHeight(COMPACT_BUTTON_H)
        b.setMinimumWidth(40)
        b.setMaximumWidth(120)
        hex4 = lp.command_hex(byte0, byte1)
        b.setToolTip(f"Send {hex4}")
        self._wire_cmd_widget(b, hex4, label, hold)
        return b

    def _wire_cmd_widget(self, w, hex4: str, label: str, hold: bool):
        if hold:
            t = QTimer(self)
            t.setInterval(HOLD_REPEAT_MS)
            t.timeout.connect(lambda h=hex4, l=label: self._send(h, note=l))
            w.pressed.connect(lambda h=hex4, l=label, tm=t: self._hold_start(h, l, tm))
            w.released.connect(lambda tm=t: self._hold_stop(tm))
            self._hold_timers[w] = t
        else:
            # clicked emits a bool "checked" argument; swallow it explicitly.
            w.clicked.connect(lambda _checked=False, h=hex4, l=label: self._send(h, note=l))

    def _build_transport_group(self):
        g = QGroupBox("Transport")
        gl = QGridLayout(g)
        gl.setSpacing(2)
        gl.setContentsMargins(4, 4, 4, 4)
        cols = 5
        for i, (b0, b1, label, hold) in enumerate(TRANSPORT_BUTTONS):
            gl.addWidget(self._make_cmd_button(b0, b1, label, hold), i // cols, i % cols)
        gl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        return g
    def _build_control_tabs(self):
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.setElideMode(Qt.TextElideMode.ElideRight)

        deck_page = QWidget()
        deck_layout = QVBoxLayout(deck_page)
        deck_layout.setContentsMargins(2, 2, 2, 2)
        deck_layout.setSpacing(3)
        deck_layout.addWidget(self._build_transport_group())
        deck_layout.addWidget(self._build_icon_strip())
        deck_layout.addStretch()

        cam_page = QWidget()
        cam_layout = QVBoxLayout(cam_page)
        cam_layout.setContentsMargins(2, 2, 2, 2)
        cam_layout.setSpacing(3)
        cam_layout.addWidget(self._build_camera_group())
        cam_layout.addStretch()
        log_page = self._build_log_tab()

        tabs.addTab(deck_page, "Deck")
        tabs.addTab(cam_page, "Camera")
        tabs.addTab(log_page, "Log")
        return tabs

    def _build_camera_group(self):
        g = QGroupBox("Camera")
        gl = QGridLayout(g)
        gl.setSpacing(2)
        gl.setContentsMargins(4, 4, 4, 4)
        cols = 5
        for i, (b0, b1, label, hold) in enumerate(CAMERA_BUTTONS):
            gl.addWidget(self._make_cmd_button(b0, b1, label, hold), i // cols, i % cols)
        gl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        return g

    def _build_icon_strip(self):
        g = QGroupBox("Quick transport")
        row = QHBoxLayout(g)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(2)
        icon_font = QFont()
        icon_font.setPointSize(COMPACT_FONT_PT + 2)
        for icon, cmd, hold in ICON_TRANSPORT:
            b = QPushButton(icon)
            b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            b.setFixedSize(32, COMPACT_BUTTON_H + 8)
            b.setFont(icon_font)
            b.setStyleSheet("padding:0; text-align:center;")
            hex4 = lp.command_hex(lp.SUBCMD_NORMAL_VTR, cmd)
            b.setToolTip(f"Send {hex4}")
            self._wire_cmd_widget(b, hex4, icon, hold)
            row.addWidget(b)
        row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        row.addStretch()
        return g

    def _build_service_group(self):
        g = QGroupBox("EEPROM")
        gl = QGridLayout(g)
        gl.setSpacing(3)
        gl.setContentsMargins(4, 4, 4, 4)
        mono = QFont("Monospace")
        mono.setStyleHint(QFont.StyleHint.TypeWriter)

        self.lbl_sv_page = QLabel("0"); self.lbl_sv_page.setFont(mono)
        self.lbl_sv_addr = QLabel("00"); self.lbl_sv_addr.setFont(mono)
        self.lbl_sv_data = QLabel("00"); self.lbl_sv_data.setFont(mono)
        self.lbl_sv_ack = QLabel("-"); self.lbl_sv_ack.setFont(mono)
        gl.addWidget(QLabel("Page"), 0, 0); gl.addWidget(self.lbl_sv_page, 0, 1)
        gl.addWidget(QLabel("Addr"), 0, 2); gl.addWidget(self.lbl_sv_addr, 0, 3)
        gl.addWidget(QLabel("Data"), 0, 4); gl.addWidget(self.lbl_sv_data, 0, 5)
        gl.addWidget(QLabel("Ack"), 0, 6); gl.addWidget(self.lbl_sv_ack, 0, 7)

        btn_read = QPushButton("Read"); btn_read.clicked.connect(lambda: self._svc(0x00))
        btn_pp = QPushButton("Page +"); btn_pp.clicked.connect(lambda: self._svc(0x67))
        btn_pm = QPushButton("Page -"); btn_pm.clicked.connect(lambda: self._svc(0x65))
        btn_ap = QPushButton("Addr +"); btn_ap.clicked.connect(lambda: self._svc(0x38))
        btn_am = QPushButton("Addr -"); btn_am.clicked.connect(lambda: self._svc(0x36))
        btn_dp = QPushButton("Data +"); btn_dp.clicked.connect(lambda: self._svc(0x34))
        btn_dm = QPushButton("Data -"); btn_dm.clicked.connect(lambda: self._svc(0x30))
        btn_store = QPushButton("Store")
        btn_store.setToolTip("Store (NVRAM)")
        btn_store.setStyleSheet("color:#a00;font-weight:bold;")
        btn_store.clicked.connect(lambda: self._svc(0x32))
        for i, b in enumerate([btn_read, btn_pp, btn_pm, btn_ap, btn_am, btn_dp, btn_dm, btn_store]):
            gl.addWidget(b, 1 + i // 4, i % 4)

        gl.addWidget(QLabel("C:"), 3, 0)
        self.svc_quick = QLineEdit("FF00")
        self.svc_quick.setMaxLength(4)
        self.svc_quick.setMaximumWidth(70)
        self.svc_quick.returnPressed.connect(self._send_service_quick)
        gl.addWidget(self.svc_quick, 3, 1)
        btn_get = QPushButton("Get")
        btn_get.clicked.connect(lambda: self._svc(0x00))
        gl.addWidget(btn_get, 3, 2)
        btn_set = QPushButton("Set")
        btn_set.clicked.connect(self._send_service_quick)
        gl.addWidget(btn_set, 3, 3)

        warn = QLabel("WARNING: NVRAM writes can brick the device.")
        warn.setWordWrap(True)
        warn.setStyleSheet("color:#a00;")
        gl.addWidget(warn, 4, 0, 1, 8)
        return g

    def _build_command_group(self):
        g = QGroupBox("Command")
        gl = QGridLayout(g)
        gl.setSpacing(2)
        gl.setContentsMargins(4, 4, 4, 4)
        gl.setColumnStretch(3, 1)
        gl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.adv_combo = QComboBox()
        for hex4, label, cat in lp.build_advanced_list():
            self.adv_combo.addItem(f"{label}  ({hex4})", hex4)
        self.adv_combo.setCurrentIndex(0)
        self.adv_combo.setFixedWidth(132)
        self.adv_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.adv_combo.setToolTip("Advanced command")
        gl.addWidget(self.adv_combo, 0, 0)
        btn_adv = QPushButton("Send")
        btn_adv.clicked.connect(self._send_advanced)
        gl.addWidget(btn_adv, 0, 1)
        btn_exit = QPushButton("Exit")
        btn_exit.clicked.connect(self.close)
        gl.addWidget(btn_exit, 0, 2)

        self.hex_input = QLineEdit()
        self.hex_input.setPlaceholderText("hex e.g. 1834")
        self.hex_input.setMaxLength(4)
        self.hex_input.setFixedWidth(74)
        self.hex_input.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.hex_input.setToolTip("Custom 4-hex command")
        self.hex_input.returnPressed.connect(self._send_manual)
        gl.addWidget(self.hex_input, 1, 0)
        btn_manual = QPushButton("Send")
        btn_manual.clicked.connect(self._send_manual)
        gl.addWidget(btn_manual, 1, 1)
        return g

    def _build_log_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 4, 4, 4)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.log.setMinimumHeight(COMPACT_LOG_H + 48)
        font = QFont("Monospace")
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        self.log.setFont(font)
        v.addWidget(self.log)
        return w

    # ----------------------------------------------------------- sending
    def _send(self, hex4, note=""):
        hex4 = hex4.upper()
        self.worker.send_command(hex4)
        self.log.appendPlainText(f">> {hex4}" + (f"   ({note})" if note else ""))

    def _svc(self, byte1):
        self._send(lp.command_hex(lp.SUBCMD_SERVICE, byte1),
                   note=lp.command_hex(lp.SUBCMD_SERVICE, byte1))

    def _send_service_quick(self):
        text = self.svc_quick.text().strip().upper()
        if len(text) != 4 or not all(c in "0123456789ABCDEF" for c in text):
            QMessageBox.warning(self, "Invalid EEPROM cmd",
                                "Enter exactly 4 hex chars, e.g. FF00 or FF32.")
            return
        self._send(text, note="eeprom quick")

    def _send_advanced(self):
        hex4 = self.adv_combo.currentData()
        if hex4:
            label = self.adv_combo.currentText()
            self._send(hex4, note=label)

    def _send_manual(self):
        text = self.hex_input.text().strip()
        if len(text) != 4 or not all(c in "0123456789abcdefABCDEF" for c in text):
            QMessageBox.warning(self, "Invalid command",
                                "Enter exactly 4 hexadecimal characters (2 bytes).")
            return
        self._send(text, note="manual")
        self.hex_input.clear()

    def _hold_start(self, hex4, label, timer):
        self._send(hex4, note=label)
        timer.start()

    def _hold_stop(self, timer):
        if timer.isActive():
            timer.stop()

    # ----------------------------------------------------------- ports
    def refresh_ports(self):
        prev = self.port_combo.currentText().split(" ")[0].strip()
        self.port_combo.clear()
        ports = list_serial_ports()
        if not ports:
            self.port_combo.addItem("(no ports found)")
            return
        for dev, desc, hwid in ports:
            self.port_combo.addItem(dev, dev)
            self.port_combo.setItemData(
                self.port_combo.count() - 1,
                f"{dev}  -  {desc}",
                Qt.ItemDataRole.ToolTipRole,
            )
        if prev:
            for i in range(self.port_combo.count()):
                if self.port_combo.itemData(i) == prev:
                    self.port_combo.setCurrentIndex(i)
                    break

    def connect_selected(self):
        idx = self.port_combo.currentIndex()
        data = self.port_combo.itemData(idx)
        if data is None:
            data = self.port_combo.currentText().split(" ")[0].strip()
        if not data:
            QMessageBox.warning(self, "No port", "Select a port first.")
            return
        self.worker.open_port(data)

    # ----------------------------------------------------------- signals
    def on_connected_changed(self, connected: bool):
        self.lbl_status.setText("Connected" if connected else "Not connected")
        self.lbl_status.setStyleSheet(
            "font-weight:bold; padding:2px 6px; color:#080;" if connected
            else "font-weight:bold; padding:2px 6px; color:#a00;")

    def on_status(self, msg: str):
        self.log.appendPlainText(f"[status] {msg}")

    def on_info(self, text: str):
        self.log.appendPlainText(f"[info] {text}")

    def on_error(self, msg: str):
        self.log.appendPlainText(f"[error] {msg}")

    def on_frame(self, frame: bytes):
        if len(frame) != 8:
            return
        d = lp.decode_frame(frame)
        self.lbl_raw.setText(d["raw_hex"])
        self.lbl_mode.setText(d["mode4"])
        self.lbl_warn.setText(", ".join(d["warnings"]) or "none")
        self.lbl_guide.setText(f"{d['guide']:X} - {d['guide_label']}")

        b = d["b6b7"]
        if "counter" in b:
            self.lbl_counter.setText(b["counter"])
        if b.get("time_ms") is not None:
            mm, ss = b["time_ms"]
            self._tc_mm, self._tc_ss = mm, ss
        if b.get("time_hf") is not None:
            hh, _ff = b["time_hf"]
            self._tc_hh = hh
            self._tc_sign = b.get("sign", False)
        if self._tc_mm is not None or self._tc_hh is not None:
            hh = self._tc_hh if self._tc_hh is not None else 0
            mm = self._tc_mm if self._tc_mm is not None else 0
            ss = self._tc_ss if self._tc_ss is not None else 0
            sign = "-" if self._tc_sign else ""
            self.lbl_timecode.setText(f"{sign}{hh:02d}:{mm:02d}:{ss:02d}")
        if b.get("remain") is not None:
            hh, mm = b["remain"]
            calc = " (calc)" if b.get("remain_calculating") else ""
            self.lbl_remain.setText(f"{hh:02d}:{mm:02d}{calc}")
        if "data" in b:
            self._merge_data_code(b["data"])
            self.lbl_datacode.setText(self._format_data_code())

        # service / EEPROM
        if d["service"]:
            s = d["service"]
            self.lbl_sv_page.setText(f"{s['page']:X}")
            self.lbl_sv_addr.setText(f"{s['address']:02X}")
            self.lbl_sv_data.setText(f"{s['data']:02X}")
            self.lbl_sv_ack.setText("write" if s["write"] else "read")
            self.log.appendPlainText(
                f"[service] page={s['page']:X} addr={s['address']:02X} "
                f"data={s['data']:02X} ack={'W' if s['write'] else 'R'}")

    def _merge_data_code(self, data):
        for k, v in data.items():
            if v is None:
                continue
            if k.startswith("year"):
                self._data_year = v if "ones" in k else (self._data_year or 0) + v * 10
            elif k.startswith("month"):
                self._data_month = v if "ones" in k else (self._data_month or 0) + v * 10
            elif k.startswith("day"):
                self._data_day = v if "ones" in k else (self._data_day or 0) + v * 10
            elif k.startswith("hour"):
                self._data_hour = v if "ones" in k else (self._data_hour or 0) + v * 10
            elif k.startswith("minute"):
                self._data_minute = v if "ones" in k else (self._data_minute or 0) + v * 10

    def _format_data_code(self):
        def fmt(a, b):
            if a is None:
                return "----"
            return f"{a:02d}:{b:02d}" if b is not None else f"{a:02d}"
        date = (f"{self._data_year or 0:02d}-{self._data_month or 0:02d}"
                if self._data_year is not None or self._data_month is not None else "----")
        time = fmt(self._data_hour, self._data_minute)
        return f"{date} {time}"

    # ----------------------------------------------------------- shutdown
    def closeEvent(self, event):
        try:
            self.worker.stop()
            self.worker.close()
            self.thread.quit()
            self.thread.wait(2000)
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app_icon_path = resource_path("assets", "lanc_remote.png")
    if os.path.exists(app_icon_path):
        app_icon = QIcon(app_icon_path)
        if not app_icon.isNull():
            app.setWindowIcon(app_icon)
    win = MainWindow()
    win.show()
    # Startup port prompt (matches the original GUI's behaviour).
    dlg = PortDialog(win)
    if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_port:
        win.worker.open_port(dlg.selected_port)
    app.exec()


if __name__ == "__main__":
    main()
