"""TCP client for the 'MCP Audio Tap' Max-for-Live relay on localhost:9878.

Mirrors AbletonConnection's shape but simpler: every tap command is an
idempotent read, so a stale socket is reconnected and retried once
unconditionally. A refused connection (device not loaded) is an expected state -
connect() returns False and send() raises ConnectionError, which the tools turn
into a friendly "drop the device on the Master" hint.
"""
import json
import logging
import socket

logger = logging.getLogger("AudioTapConnection")


class AudioTapConnection:
    def __init__(self, host="localhost", port=9878, timeout=5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None

    def _open_socket(self):
        """Create + connect a socket. Seam for tests to patch."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect((self.host, self.port))
        return s

    def connect(self):
        if self.sock:
            return True
        try:
            self.sock = self._open_socket()
            return True
        except OSError as e:
            logger.info("audio tap not reachable on %s:%s (%s)", self.host, self.port, e)
            self.sock = None
            return False

    def _reset(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None

    def _recv_full(self, buffer_size=8192):
        chunks = []
        while True:
            chunk = self.sock.recv(buffer_size)
            if not chunk:
                break
            chunks.append(chunk)
            data = b"".join(chunks)
            try:
                json.loads(data.decode("utf-8"))
                return data
            except json.JSONDecodeError:
                continue
        if chunks:
            return b"".join(chunks)
        raise OSError("audio tap closed before sending data")

    def send(self, command, params=None):
        """One round-trip; reconnect + retry once on a stale socket.

        Returns the `data` payload. Raises ConnectionError if the device is not
        reachable, RuntimeError on a device-reported {ok:false} error.
        """
        message = {"command": command}
        if params is not None:
            message.update(params)
        last_err = None
        for _attempt in (1, 2):
            if not self.sock and not self.connect():
                raise ConnectionError("audio tap not connected")
            try:
                self.sock.sendall(json.dumps(message).encode("utf-8"))
                resp = json.loads(self._recv_full().decode("utf-8"))
                if not resp.get("ok", False):
                    raise RuntimeError(resp.get("error", "audio tap error"))
                return resp.get("data", {})
            except RuntimeError:
                raise
            except (OSError, json.JSONDecodeError) as e:
                last_err = e
                self._reset()
        raise ConnectionError("audio tap round-trip failed: %s" % last_err)

    def is_connected(self):
        try:
            self.send("ping")
            return True
        except Exception:
            return False

    def disconnect(self):
        self._reset()
