#!/usr/bin/env python3
"""Serial worker thread for the LANC USB interface.

Owns the pyserial connection so that all serial I/O happens in one thread
(no concurrent read/write on the same Serial object).  Reads the byte stream
from the Arduino, splits it into 8-byte LANC frames, and emits Qt signals.
Outgoing commands (4 hex chars) are queued from any thread and written here.

Frame stream format produced by the Arduino sketch:
    <8 raw bytes><0x0A>
The banner line "Arduino LANC to USB-serial interface v1.0\\r\\n" is emitted
once at boot and is ignored.  Because a data byte may legally equal 0x0A, we
split on 0x0A and accept only segments whose length is exactly 8 as frames;
any other segment length (banner text, or a frame split by an embedded 0x0A)
is discarded.  This self-heals within one frame at 50/60 Hz.
"""

import queue

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtCore import QObject

import serial
import serial.tools.list_ports

from lanc_protocol import BAUDRATE


def list_serial_ports():
    """Return a list of (device, description, hwid) tuples, Arduino-ish first."""
    ports = list(serial.tools.list_ports.comports())
    def rank(p):
        d = (p.description or "").lower() + " " + (p.hwid or "").lower()
        s = 0
        if "arduino" in d:
            s -= 100
        if "acm" in (p.device or "").lower():
            s -= 50
        if "2341" in d or "03eb" in d or "2a03" in d:  # Arduino / Atmel VID
            s -= 80
        return s
    ports.sort(key=rank)
    return [(p.device, p.description or "", p.hwid or "") for p in ports]


class LancSerialWorker(QObject):
    frame_received = pyqtSignal(bytes)
    info_received = pyqtSignal(str)        # non-frame text line (banner etc.)
    status_message = pyqtSignal(str)       # human-readable connection status
    error_occurred = pyqtSignal(str)
    connected_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._serial = None
        self._port = None
        self._running = False
        self._send_q = queue.Queue()
        self._buf = bytearray()

    # ---- public API (thread-safe enough: called from GUI thread) ----
    def open_port(self, port: str):
        """Open a port.  If already open, close first.  Safe to call from GUI."""
        self.close()
        self._port = port
        try:
            self._serial = serial.Serial(
                port=port,
                baudrate=BAUDRATE,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
                timeout=0.1,        # read timeout so the loop can poll
                write_timeout=1.0,
            )
        except Exception as e:  # noqa: BLE001
            self._serial = None
            self.error_occurred.emit(f"Failed to open {port}: {e}")
            self.connected_changed.emit(False)
            return
        self._buf.clear()
        self.connected_changed.emit(True)
        self.status_message.emit(f"Connected to {port} @ {BAUDRATE} baud")

    def close(self):
        """Close the serial port but keep the worker loop alive for reconnect."""
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:  # noqa: BLE001
                pass
            self._serial = None
            self.connected_changed.emit(False)
            self.status_message.emit("Disconnected")

    def stop(self):
        """Stop the worker loop and close the port (used on app shutdown)."""
        self._running = False

    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def send_command(self, hex4: str):
        """Queue a 4-hex-char command for sending (validated by caller)."""
        if not self.is_connected():
            self.error_occurred.emit("Not connected")
            return
        self._send_q.put(hex4.upper())

    # ---- worker loop (runs in a QThread for the whole app session) ----
    def process(self):
        """Persistent loop.  Survives open/close; never exits until stop()."""
        while self._running:
            ser = self._serial  # local ref so GUI close/open can't clobber us
            if ser is None or not ser.is_open:
                self.msleep(50)
                continue
            # flush any pending outbound commands
            while not self._send_q.empty():
                try:
                    hex4 = self._send_q.get_nowait()
                except queue.Empty:
                    break
                self._write_command(hex4, ser)
            # read available bytes
            try:
                n = ser.in_waiting
                if n:
                    chunk = ser.read(n)
                else:
                    chunk = ser.read(1)  # blocks up to timeout, avoids spin
            except Exception as e:  # noqa: BLE001
                self.error_occurred.emit(f"Read error: {e}")
                # only clear if it is still the same object (GUI may have reopened)
                if self._serial is ser:
                    self._serial = None
                    self.connected_changed.emit(False)
                    self.status_message.emit("Disconnected (read error)")
                self.msleep(200)
                continue
            if chunk:
                self._consume(chunk)
        # final cleanup on stop()
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:  # noqa: BLE001
                pass
            self._serial = None
        self.connected_changed.emit(False)

    def _write_command(self, hex4: str, ser):
        data = (hex4 + "\n").encode("ascii")
        try:
            ser.write(data)
            ser.flush()
        except Exception as e:  # noqa: BLE001
            self.error_occurred.emit(f"Write error: {e}")
            if self._serial is ser:
                self._serial = None
                self.connected_changed.emit(False)
                self.status_message.emit("Disconnected (write error)")

    def _consume(self, chunk: bytes):
        self._buf.extend(chunk)
        while True:
            idx = self._buf.find(0x0A)
            if idx < 0:
                break
            seg = bytes(self._buf[:idx])
            del self._buf[:idx + 1]
            if len(seg) == 8:
                self.frame_received.emit(seg)
            elif seg:
                # likely banner text or a fragment; surface printable lines
                try:
                    text = seg.decode("ascii", errors="replace").strip()
                except Exception:  # noqa: BLE001
                    text = ""
                if text:
                    self.info_received.emit(text)
        # guard against runaway buffer if no newlines ever arrive
        if len(self._buf) > 4096:
            del self._buf[: len(self._buf) - 4096]

    @staticmethod
    def msleep(ms):
        QThread.msleep(ms)


class _WorkerThread(QThread):
    """QThread that drives a LancSerialWorker.process() loop."""
    def __init__(self, worker: LancSerialWorker, parent=None):
        super().__init__(parent)
        self._worker = worker

    def run(self):
        self._worker.process()


def start_worker(worker: LancSerialWorker, parent=None) -> _WorkerThread:
    """Create + start a QThread running the worker loop for the app session."""
    worker._running = True
    t = _WorkerThread(worker, parent)
    t.start()
    return t
