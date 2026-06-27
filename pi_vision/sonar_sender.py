"""TCP client that pushes newline-delimited distance readings to the phone.

Same role reversal as the camera path: the phone is the server, the Pi dials
it (see PI_ZERO_VISION_PLAN.md). Each reading is a short ASCII line like
`"142.3\n"` (centimetres) or `"-1\n"` (no valid reading) — exactly the format
the app's distance parser expects (`double.tryParse` after trimming; a negative
value means no-data).

Plain newline framing (not the camera's 4-byte length prefix): the messages are
tiny and human-readable, so `nc <phone> 8766` shows the live numbers when
debugging. This class owns a single socket and raises `ConnectionError` on any
failure so the caller applies its reconnect/backoff policy in one place.
"""

import logging
import socket

from config import CONNECT_TIMEOUT_S, SEND_TIMEOUT_S

log = logging.getLogger("pi_vision.sonar_sender")


class SonarSender:
    def __init__(self, host, port):
        self._host = host
        self._port = int(port)
        self._sock = None

    @property
    def connected(self):
        return self._sock is not None

    def connect(self):
        """Open the TCP connection. Raises OSError if the phone isn't ready."""
        self.close()
        sock = socket.create_connection(
            (self._host, self._port), timeout=CONNECT_TIMEOUT_S
        )
        # Tiny messages — send them immediately rather than coalescing.
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        # Detect a silently-dropped peer (phone left WiFi) and bound each send.
        sock.settimeout(SEND_TIMEOUT_S)
        self._sock = sock
        log.info("Connected to %s:%d", self._host, self._port)

    def send_cm(self, distance_cm):
        """Send one reading. Raises ConnectionError if the link is broken."""
        if self._sock is None:
            raise ConnectionError("Not connected")
        line = f"{distance_cm:.1f}\n".encode("ascii")
        try:
            self._sock.sendall(line)
        except (OSError, socket.timeout) as e:
            self.close()
            raise ConnectionError(f"send failed: {e}") from e

    def close(self):
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
