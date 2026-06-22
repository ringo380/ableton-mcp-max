"""Pure helpers to write Arrangement-timeline automation into a Live `.als`
set file (gzipped XML).

The LOM cannot create arrangement automation (clip.automation_envelope returns
None for arrangement clips), so we patch the saved set: arrangement automation
for a parameter is one <AutomationEnvelope> in the owning track's
<AutomationEnvelopes><Envelopes> list, whose <EnvelopeTarget><PointeeId> equals
that parameter's <AutomationTarget Id>. See
docs/superpowers/specs/2026-06-21-arrangement-automation-design.md.

No Live dependency (server.py imports this; the Remote Script cannot). The
server resolves the target parameter via the LOM (name/value), then this module
locates the matching <AutomationTarget Id> in the XML, value-verified, and
injects the envelope.

v1 targets RACK MACROS (MacroControls.<n>, robust + value-verified) and
top-level native device parameters by element tag (value-verified). Parameters
of devices NESTED inside a rack are a documented follow-up (their elements
interleave with the rack's own macros in document order).
"""

import gzip
import re

# Live's "value before the first breakpoint" sentinel time (a large negative).
SENTINEL_TIME = -63072000


# --------------------------------------------------------------------------- #
# gzip core
# --------------------------------------------------------------------------- #
def read_als(path):
    """Gunzip a .als and return its XML as a unicode string."""
    with gzip.open(path, "rb") as f:
        return f.read().decode("utf-8")


def write_als(path, xml):
    """Gzip-write XML (unicode) back to a .als path."""
    with gzip.open(path, "wb") as f:
        f.write(xml.encode("utf-8"))


# --------------------------------------------------------------------------- #
# value / event formatting
# --------------------------------------------------------------------------- #
def _fmt(v):
    """Format a float the way Live does: plain decimal, no scientific notation,
    integers without a trailing .0."""
    f = float(v)
    if f == int(f) and abs(f) < 1e15:
        return str(int(f))
    return ("%.10g" % f)


def _clamp(v, lo, hi):
    if lo is not None and v < lo:
        return lo
    if hi is not None and v > hi:
        return hi
    return v


def points_to_events(points, value_min=None, value_max=None):
    """Normalize [{"time", "value"}] into a sorted event list with a leading
    (SENTINEL_TIME, first_value) entry. Stable-sorts by time so duplicate times
    (vertical steps) are preserved in input order. Values clamped to
    [value_min, value_max] when given. Raises ValueError on empty input."""
    if not points:
        raise ValueError("points must be a non-empty list of {time, value}")
    norm = []
    for p in points:
        t = float(p["time"])
        v = _clamp(float(p["value"]), value_min, value_max)
        norm.append((t, v))
    norm.sort(key=lambda tv: tv[0])
    first_value = norm[0][1]
    return [(SENTINEL_TIME, first_value)] + norm


def build_envelope_xml(pointee_id, points, env_id, value_min=None, value_max=None):
    """Render one <AutomationEnvelope> block for the given target param Id.
    points: [{"time", "value"}]; times in beats, values native units."""
    events = points_to_events(points, value_min, value_max)
    ev_lines = "".join(
        '\n\t\t\t\t\t\t\t\t\t<FloatEvent Time="%s" Value="%s" />'
        % (_fmt(t), _fmt(v))
        for t, v in events
    )
    return (
        '<AutomationEnvelope Id="%d">\n'
        '\t\t\t\t\t\t\t<EnvelopeTarget>\n'
        '\t\t\t\t\t\t\t\t<PointeeId Value="%s" />\n'
        '\t\t\t\t\t\t\t</EnvelopeTarget>\n'
        '\t\t\t\t\t\t\t<Automation>\n'
        '\t\t\t\t\t\t\t\t<Events>%s\n'
        '\t\t\t\t\t\t\t\t</Events>\n'
        '\t\t\t\t\t\t\t\t<AutomationTransformViewState>\n'
        '\t\t\t\t\t\t\t\t\t<IsTransformPending Value="false" />\n'
        '\t\t\t\t\t\t\t\t\t<TimeAndValueTransforms />\n'
        '\t\t\t\t\t\t\t\t</AutomationTransformViewState>\n'
        '\t\t\t\t\t\t\t</Automation>\n'
        '\t\t\t\t\t\t</AutomationEnvelope>'
        % (int(env_id), str(pointee_id), ev_lines)
    )


# --------------------------------------------------------------------------- #
# navigation: track span -> device span -> AutomationTarget Id
# --------------------------------------------------------------------------- #
_TRACK_OPEN = re.compile(r'<(MidiTrack|AudioTrack|GroupTrack|ReturnTrack) Id="\d+">')


def find_track_span(xml, track_index):
    """Char span (start, end) of the track_index-th REGULAR track (Midi/Audio,
    document order, excluding Group/Return). Tracks are flat siblings under
    <Tracks>, so the matching close is the next close-tag of the same type."""
    regular = 0
    for m in _TRACK_OPEN.finditer(xml):
        kind = m.group(1)
        if kind in ("MidiTrack", "AudioTrack"):
            if regular == track_index:
                close = "</%s>" % kind
                end = xml.find(close, m.end())
                if end == -1:
                    raise ValueError("unterminated %s for track %d" % (kind, track_index))
                return (m.start(), end + len(close))
            regular += 1
    raise ValueError("regular track index %d not found" % track_index)


def _direct_device_spans(track_xml):
    """Spans of the direct child device elements of the track's TOP-LEVEL
    <Devices> container (depth-aware: skips devices nested in rack chains)."""
    dstart = track_xml.find("<Devices>")
    if dstart == -1:
        return []
    i = dstart + len("<Devices>")
    end = _matching_close(track_xml, "Devices", dstart)
    spans = []
    # Walk direct children: each child is one element <Tag ...> ... </Tag>.
    tag_re = re.compile(r'<([A-Za-z][\w.]*)(\s[^>]*?)?(/?)>')
    while i < end:
        m = tag_re.search(track_xml, i, end)
        if not m:
            break
        tag, _attrs, selfclose = m.group(1), m.group(2), m.group(3)
        if selfclose == "/":
            i = m.end()
            continue
        cstart = m.start()
        cend = _matching_close(track_xml, tag, cstart)
        spans.append((cstart, cend))
        i = cend
    return spans


def _matching_close(xml, tag, open_index):
    """Index just past the close tag matching the element opening at open_index,
    accounting for nested same-name elements and self-closing tags."""
    open_re = re.compile(r'<%s(\s[^>]*?)?(/?)>' % re.escape(tag))
    close = "</%s>" % tag
    m = open_re.match(xml, open_index)
    if not m:
        # not an opening of `tag` at this index; fall back to next close
        c = xml.find(close, open_index)
        return c + len(close) if c != -1 else len(xml)
    if m.group(2) == "/":
        return m.end()
    depth = 1
    pos = m.end()
    nxt = re.compile(r'<%s(\s[^>]*?)?(/?)>|</%s>' % (re.escape(tag), re.escape(tag)))
    while depth > 0:
        mm = nxt.search(xml, pos)
        if not mm:
            return len(xml)
        if mm.group(0).startswith("</"):
            depth -= 1
        elif mm.group(2) != "/":
            depth += 1
        pos = mm.end()
    return pos


def _device_span(xml, track_index, device_index):
    tstart, tend = find_track_span(xml, track_index)
    track_xml = xml[tstart:tend]
    spans = _direct_device_spans(track_xml)
    if device_index >= len(spans):
        raise ValueError(
            "device index %d out of range (track has %d top-level devices)"
            % (device_index, len(spans)))
    s, e = spans[device_index]
    return (tstart + s, tstart + e)


def _read_target(block):
    """From a parameter element's inner XML, read (AutomationTarget Id, manual,
    min, max). Returns None if it has no AutomationTarget."""
    aid = re.search(r'<AutomationTarget Id="(\d+)"', block)
    if not aid:
        return None
    man = re.search(r'<Manual Value="([^"]+)" />', block)
    rng = re.search(
        r'<MidiControllerRange>\s*<Min Value="([^"]+)" />\s*<Max Value="([^"]+)" />',
        block, re.S)
    def _f(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None
    return {
        "pointee_id": aid.group(1),
        "manual": _f(man.group(1)) if man else None,
        "value_min": _f(rng.group(1)) if rng else None,
        "value_max": _f(rng.group(2)) if rng else None,
    }


def resolve_macro_target(xml, track_index, device_index, macro_index,
                         expected_value=None, value_tol=0.5):
    """Resolve a rack macro (MacroControls.<macro_index>) to its target Id.
    Verifies the macro's Manual against expected_value when given."""
    ds, de = _device_span(xml, track_index, device_index)
    dev = xml[ds:de]
    tag = "MacroControls.%d" % int(macro_index)
    i = dev.find("<%s>" % tag)
    if i == -1:
        raise ValueError("macro %d not found on device %d (not a rack, or fewer macros)"
                         % (macro_index, device_index))
    j = _matching_close(dev, tag, i)
    info = _read_target(dev[i:j])
    if not info:
        raise ValueError("macro %d has no AutomationTarget" % macro_index)
    info["param_name"] = tag
    info["verified"] = _verify(info["manual"], expected_value, value_tol)
    return info


def resolve_named_param_target(xml, track_index, device_index, element_tag,
                               expected_value=None, value_tol=0.5):
    """Resolve a top-level native device parameter by its XML element tag (e.g.
    'Filter_Frequency'), value-verified. For devices DIRECTLY on the track (not
    nested in a rack chain)."""
    ds, de = _device_span(xml, track_index, device_index)
    dev = xml[ds:de]
    i = dev.find("<%s>" % element_tag)
    if i == -1:
        raise ValueError("param element <%s> not found on device %d"
                         % (element_tag, device_index))
    j = _matching_close(dev, element_tag, i)
    info = _read_target(dev[i:j])
    if not info:
        raise ValueError("<%s> has no AutomationTarget" % element_tag)
    info["param_name"] = element_tag
    info["verified"] = _verify(info["manual"], expected_value, value_tol)
    return info


def _verify(manual, expected, tol):
    if expected is None or manual is None:
        return None
    return abs(float(manual) - float(expected)) <= tol


# --------------------------------------------------------------------------- #
# envelope injection into the track's Envelopes list
# --------------------------------------------------------------------------- #
def next_envelope_id(track_xml):
    """max existing AutomationEnvelope Id in the track + 1 (else 0)."""
    ids = [int(m) for m in re.findall(r'<AutomationEnvelope Id="(\d+)">', track_xml)]
    return (max(ids) + 1) if ids else 0


def inject_envelope(xml, track_index, pointee_id, envelope_builder, replace=True):
    """Insert an <AutomationEnvelope> into the track's <Envelopes> list.

    envelope_builder(env_id) -> str  builds the block once the Id is known.
    With replace=True, an existing envelope for the same PointeeId is removed
    first (idempotent rewrites). Returns the new XML."""
    tstart, tend = find_track_span(xml, track_index)
    track_xml = xml[tstart:tend]

    aenv = track_xml.find("<AutomationEnvelopes>")
    if aenv == -1:
        raise ValueError("track %d has no <AutomationEnvelopes>" % track_index)
    aenv_end = _matching_close(track_xml, "AutomationEnvelopes", aenv)
    container = track_xml[aenv:aenv_end]

    # Normalize a self-closing <Envelopes /> to an open/close pair.
    if "<Envelopes />" in container:
        container = container.replace("<Envelopes />",
                                      "<Envelopes>\n\t\t\t\t\t\t</Envelopes>", 1)

    # Optionally drop an existing envelope with the same PointeeId.
    if replace:
        container = _remove_envelope_for_pointee(container, pointee_id)

    env_id = next_envelope_id(container)
    block = envelope_builder(env_id)

    close = "</Envelopes>"
    ci = container.rfind(close)
    container = (container[:ci] + "\t\t\t\t\t\t" + block + "\n"
                 + container[ci:])

    new_track = track_xml[:aenv] + container + track_xml[aenv_end:]
    return xml[:tstart] + new_track + xml[tend:]


def _remove_envelope_for_pointee(container, pointee_id):
    """Remove any <AutomationEnvelope> whose EnvelopeTarget PointeeId matches."""
    out = container
    while True:
        m = re.search(r'<AutomationEnvelope Id="\d+">', out)
        found = None
        for m in re.finditer(r'<AutomationEnvelope Id="\d+">', out):
            end = _matching_close(out, "AutomationEnvelope", m.start())
            block = out[m.start():end]
            pid = re.search(r'<PointeeId Value="([^"]+)" />', block)
            if pid and pid.group(1) == str(pointee_id):
                found = (m.start(), end)
                break
        if not found:
            return out
        s, e = found
        # also swallow surrounding whitespace/indent on the line
        line_start = out.rfind("\n", 0, s)
        if line_start == -1:
            line_start = s
        out = out[:line_start] + out[e:]
