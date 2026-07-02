"""TCP client that pushes length-prefixed JPEG frames to the phone.

The phone is the server; the Pi dials it (see PI_ZERO_VISION_PLAN.md). Each
frame is `struct.pack('>I', len) + jpeg`, matching the app's
`PiFrameServer` reassembly (`getUint32(Endian.big)`).

This class owns a single socket and raises `ConnectionError` on any failure so
the caller can apply its reconnect/backoff policy in one place.
"""

import logging
import socket
import struct

from config import (
    CONNECT_TIMEOUT_S,
    HEADER_FORMAT,
    KEEPALIVE_COUNT,
    KEEPALIVE_IDLE_S,
    KEEPALIVE_INTERVAL_S,
    MAX_FRAME_BYTES,
    SEND_TIMEOUT_S,
)

log = logging.getLogger("pi_vision.sender")


def enable_keepalive(sock):
    """Arm TCP keepalive so a silently-vanished peer (WiFi drop, no RST) is
    detected in ~15 s instead of whenever the send buffer happens to fill.
    Best-effort: the per-parameter options are Linux-specific."""
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, KEEPALIVE_IDLE_S)
        sock.setsockopt(
            socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, KEEPALIVE_INTERVAL_S
        )
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, KEEPALIVE_COUNT)
    except (OSError, AttributeError) as e:
        log.debug("keepalive tuning unavailable: %s", e)


class FrameSender:
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
        # `create_connection` handles DNS/IPv4/IPv6 and applies the timeout to
        # the connect phase.
        sock = socket.create_connection(
            (self._host, self._port), timeout=CONNECT_TIMEOUT_S
        )
        # Low latency over per-frame throughput — we send small JPEGs.
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        # Detect a silently-dropped peer (phone left WiFi) rather than blocking
        # forever; also bound each send.
        sock.settimeout(SEND_TIMEOUT_S)
        enable_keepalive(sock)
        self._sock = sock
        log.info("Connected to %s:%d", self._host, self._port)

    def send(self, jpeg):
        """Send one frame. Raises ConnectionError if the link is broken."""
        if self._sock is None:
            raise ConnectionError("Not connected")
        n = len(jpeg)
        if n <= 0 or n > MAX_FRAME_BYTES:
            # Don't transmit something the app will reject as desync — just
            # skip this frame.
            log.warning("Skipping implausible frame of %d bytes", n)
            return
        try:
            self._sock.sendall(struct.pack(HEADER_FORMAT, n) + jpeg)
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
