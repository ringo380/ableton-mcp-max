import json
import socket
import threading
from collections import deque


def parse_frames(buf):
    """Split a newline-delimited JSON buffer into (frames, remainder).

    Tolerates blank lines and a trailing partial frame (kept in remainder).
    A complete-but-malformed line is skipped.
    """
    frames = []
    while "\n" in buf:
        line, buf = buf.split("\n", 1)
        line = line.strip()
        if not line:
            continue
        try:
            frames.append(json.loads(line))
        except ValueError:
            continue
    return frames, buf


class TapState:
    """In-memory registry state: connection -> track identity + ring buffer.
    Keyed by track uuid (stable across rename/reorder). Pure; no sockets."""
    def __init__(self, buffer_max=36000):
        self.buffer_max = buffer_max
        self._by_conn = {}        # conn_id -> uuid
        self._identity = {}       # uuid -> identity dict
        self._buffers = {}        # uuid -> deque
        self._sr = {}             # uuid -> sample_rate
        # TapState is self-synchronized: handler threads mutate while the main
        # thread reads. A plain Lock is safe because no method below calls
        # another locked method while holding the lock (no nesting).
        self._lock = threading.Lock()

    def handle_frame(self, conn_id, frame):
        t = frame.get("type")
        if t == "hello":
            ident = dict(frame.get("track") or {})
            uuid = ident.get("uuid")
            if not uuid:
                return
            with self._lock:
                self._by_conn[conn_id] = uuid
                self._identity[uuid] = ident
                self._sr[uuid] = frame.get("sample_rate", 48000)
                self._buffers.setdefault(uuid, deque(maxlen=self.buffer_max))
        elif t == "block":
            with self._lock:
                uuid = self._by_conn.get(conn_id)
                if uuid is None:
                    return
                self._buffers[uuid].append(frame.get("data") or {})

    def tracks(self):
        with self._lock:
            return [dict(self._identity[u], sample_rate=self._sr.get(u, 48000),
                         block_count=len(self._buffers.get(u, ())))
                    for u in self._identity]

    def buffer(self, uuid):
        with self._lock:
            return list(self._buffers.get(uuid, ()))

    def reset(self, uuid=None):
        with self._lock:
            # `uuid is not None` (not truthiness): a falsy-but-not-None uuid
            # (e.g. "") must mean "reset that single (unknown) track" -> no-op,
            # NOT "reset every buffer".
            targets = [uuid] if uuid is not None else list(self._buffers)
            for u in targets:
                if u in self._buffers:
                    self._buffers[u].clear()

    def forget(self, uuid):
        """Remove a uuid's identity, sample_rate, and buffer entirely.
        Also unlinks any conn ids still pointing at it. Idempotent."""
        with self._lock:
            self._identity.pop(uuid, None)
            self._sr.pop(uuid, None)
            self._buffers.pop(uuid, None)
            for cid in [c for c, u in self._by_conn.items() if u == uuid]:
                self._by_conn.pop(cid, None)

    def drop_conn(self, conn_id):
        """A connection dropped -> the device is gone, so evict its track
        (identity + sample_rate + buffer) and the conn mapping. Work is inlined
        (not a call to forget()) to avoid re-acquiring the non-reentrant lock."""
        with self._lock:
            uuid = self._by_conn.pop(conn_id, None)
            if uuid is None:
                return
            self._identity.pop(uuid, None)
            self._sr.pop(uuid, None)
            self._buffers.pop(uuid, None)
            # drop any other conn ids that mapped to the same uuid
            for cid in [c for c, u in self._by_conn.items() if u == uuid]:
                self._by_conn.pop(cid, None)


class TapRegistry:
    """Background TCP server: accepts tap-device client connections, parses
    newline-delimited JSON frames, feeds TapState. feed() is the testable seam.
    port=0 means do NOT bind (used by unit tests that drive feed() directly)."""
    def __init__(self, port=9878, host="127.0.0.1", buffer_max=36000):
        self.port = port
        self.host = host
        self.state = TapState(buffer_max=buffer_max)
        self._recv_buf = {}       # conn_id -> str
        self._sockets = {}        # conn_id -> socket (only when a real server runs)
        self._srv = None
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def feed(self, conn_id, chunk):
        """Ingest a raw text chunk for a connection (the testable core)."""
        with self._lock:
            buf = self._recv_buf.get(conn_id, "") + chunk
            frames, rest = parse_frames(buf)
            self._recv_buf[conn_id] = rest
            for f in frames:
                self.state.handle_frame(conn_id, f)

    def send_command(self, conn_id, command):
        """Best-effort registry->device command (reset/ping). No-op if no socket."""
        sock = self._sockets.get(conn_id)
        if sock:
            try:
                sock.sendall((json.dumps({"command": command}) + "\n").encode())
            except OSError:
                pass

    def start(self):
        if self.port == 0:
            return
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind((self.host, self.port))
        self._srv.listen(16)
        self._srv.settimeout(0.5)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        cid = 0
        while not self._stop.is_set():
            try:
                conn, _ = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            cid += 1
            conn_id = str(cid)
            self._sockets[conn_id] = conn
            threading.Thread(target=self._handle, args=(conn_id, conn), daemon=True).start()

    def _handle(self, conn_id, conn):
        conn.settimeout(1.0)
        try:
            while not self._stop.is_set():
                try:
                    chunk = conn.recv(65536)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                self.feed(conn_id, chunk.decode("utf-8", "replace"))
        finally:
            self.state.drop_conn(conn_id)
            self._sockets.pop(conn_id, None)
            with self._lock:
                self._recv_buf.pop(conn_id, None)
            try:
                conn.close()
            except OSError:
                pass

    def stop(self):
        # Relies on daemon threads plus the accept/recv timeouts to wind down;
        # it does NOT join the serve/handler threads. Repeated start/stop on the
        # same instance is not supported.
        self._stop.set()
        if self._srv:
            try:
                self._srv.close()
            except OSError:
                pass
