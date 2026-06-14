import json
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

    def handle_frame(self, conn_id, frame):
        t = frame.get("type")
        if t == "hello":
            ident = dict(frame.get("track") or {})
            uuid = ident.get("uuid")
            if not uuid:
                return
            self._by_conn[conn_id] = uuid
            self._identity[uuid] = ident
            self._sr[uuid] = frame.get("sample_rate", 48000)
            self._buffers.setdefault(uuid, deque(maxlen=self.buffer_max))
        elif t == "block":
            uuid = self._by_conn.get(conn_id)
            if uuid is None:
                return
            self._buffers[uuid].append(frame.get("data") or {})

    def tracks(self):
        return [dict(self._identity[u], sample_rate=self._sr.get(u, 48000),
                     block_count=len(self._buffers.get(u, ())))
                for u in self._identity]

    def buffer(self, uuid):
        return list(self._buffers.get(uuid, ()))

    def reset(self, uuid=None):
        targets = [uuid] if uuid else list(self._buffers)
        for u in targets:
            if u in self._buffers:
                self._buffers[u].clear()

    def drop_conn(self, conn_id):
        self._by_conn.pop(conn_id, None)
