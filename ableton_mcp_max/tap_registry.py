import json


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
