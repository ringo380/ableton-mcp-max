"""Pure helpers to write Arrangement-timeline automation into a Live `.als`
set file (gzipped XML).

The LOM cannot create arrangement automation (clip.automation_envelope returns
None for arrangement clips, session-clip envelopes don't survive
duplicate_clip_to_arrangement, and there is no track-level breakpoint API), so
we patch the saved set: arrangement automation for a parameter is one
<AutomationEnvelope> in the owning track's <AutomationEnvelopes><Envelopes>
list, whose <EnvelopeTarget><PointeeId> equals that parameter's
<AutomationTarget Id>. See
docs/superpowers/specs/2026-06-21-arrangement-automation-design.md.

No Live dependency (server.py imports this; the Remote Script cannot).

**Targeting via value probe.** Ordinal/name correlation between the LOM
parameter list and the XML param elements is NOT reliable (the LOM injects
Device-On + quantized params and reorders), so we don't navigate to the param
by name. Instead the server sets the target param to a globally-unique sentinel
value through the LOM, reads back the value Live actually stored, saves the set,
and `find_target_after_manual` locates the single `<Manual Value=...>` equal to
that value -> the next `<AutomationTarget Id>` is the PointeeId. This works
uniformly for macros, native params, nested-in-rack params, and AU/VST plugins
(all store their value as `<Manual>` immediately before `<AutomationTarget>`).
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


def build_envelope_xml(pointee_id, points, env_id, first_event_id,
                       value_min=None, value_max=None):
    """Render one <AutomationEnvelope> block for the given target param Id.
    points: [{"time", "value"}]; times in beats, values native units.

    Each <FloatEvent> is given a unique Id starting at first_event_id (Live 12
    REJECTS the set as corrupt - "Not all list members have Ids" - if any
    FloatEvent lacks an Id). Ids come from the document's <NextPointeeId> pool;
    the caller must reserve len(points)+1 ids per envelope and bump the counter
    (see next_pointee_id / set_next_pointee_id)."""
    events = points_to_events(points, value_min, value_max)
    ev_lines = "".join(
        '\n\t\t\t\t\t\t\t\t\t<FloatEvent Id="%d" Time="%s" Value="%s" />'
        % (int(first_event_id) + i, _fmt(t), _fmt(v))
        for i, (t, v) in enumerate(events)
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
# global Id pool (<NextPointeeId>) - FloatEvent / target Ids draw from here
# --------------------------------------------------------------------------- #
_NEXT_POINTEE_RE = re.compile(r'(<NextPointeeId Value=")(\d+)("\s*/>)')


def next_pointee_id(xml):
    """Live's global next-id counter (<NextPointeeId>), the pool FloatEvent and
    AutomationTarget Ids come from. Falls back to max document Id + 1 if the
    header element is absent."""
    m = _NEXT_POINTEE_RE.search(xml)
    if m:
        return int(m.group(2))
    ids = [int(x) for x in re.findall(r'Id="(\d+)"', xml)]
    return (max(ids) + 1) if ids else 1


def set_next_pointee_id(xml, value):
    """Write back the global next-id counter so Live won't later reuse an Id we
    allocated. No-op (returns xml unchanged) if the element is absent."""
    return _NEXT_POINTEE_RE.sub(
        lambda m: "%s%d%s" % (m.group(1), int(value), m.group(3)), xml, count=1)


# --------------------------------------------------------------------------- #
# targeting: locate a param's AutomationTarget Id by its probed value
# --------------------------------------------------------------------------- #
_MANUAL_RE = re.compile(r'<Manual Value="([^"]+)" />')


def _value_match(a, b, tol):
    if tol is not None:
        return abs(a - b) <= tol
    # Live's XML keeps ~10 significant figures; the LOM read-back is the same
    # double, so they agree to well within a tight relative tolerance.
    return abs(a - b) <= max(1e-6, 1e-6 * abs(b))


def find_target_after_manual(xml, value, tol=None):
    """Locate the parameter whose <Manual Value> equals `value` (a probe sentinel
    set on exactly one param) and return its AutomationTarget Id (the envelope's
    PointeeId).

    `value` is the float Live actually stored (read back via the LOM after the
    probe set), which equals the XML <Manual> modulo string formatting, so the
    match is by float closeness. Returns {"pointee_id": str, "manual_literal":
    str}. Raises ValueError unless EXACTLY ONE <Manual> matches (a non-unique
    sentinel can't be disambiguated -> pick a more distinctive value)."""
    matches = []
    for m in _MANUAL_RE.finditer(xml):
        try:
            mv = float(m.group(1))
        except ValueError:
            continue  # booleans ('true'/'false') etc.
        if _value_match(mv, float(value), tol):
            am = re.search(r'<AutomationTarget Id="(\d+)"', xml[m.end():])
            if am:
                matches.append((m.group(0), am.group(1)))
    if len(matches) != 1:
        raise ValueError(
            "probe value %r matched %d <Manual> params (need exactly 1); choose "
            "a more distinctive sentinel" % (value, len(matches)))
    literal, pointee = matches[0]
    return {"pointee_id": pointee, "manual_literal": literal}


def patch_manual(xml, manual_literal, new_value, value_min=None, value_max=None):
    """Replace a UNIQUE <Manual ...> literal (as returned by
    find_target_after_manual) with one holding `new_value`, so the probed knob is
    left at the envelope's first point on disk instead of the sentinel. Raises
    ValueError if the literal is not present exactly once."""
    if xml.count(manual_literal) != 1:
        raise ValueError("manual literal not unique for patch-back (%d found)"
                         % xml.count(manual_literal))
    v = _clamp(float(new_value), value_min, value_max)
    return xml.replace(manual_literal, '<Manual Value="%s" />' % _fmt(v), 1)


# --------------------------------------------------------------------------- #
# track span navigation (for envelope injection into the OWNING track)
# --------------------------------------------------------------------------- #
# Real track opens carry extra attrs (e.g. <MidiTrack Id="12" SelectedToolPanel
# ="2" ...>), so the open pattern must allow them.
_TRACK_OPEN = re.compile(r'<(MidiTrack|AudioTrack|GroupTrack|ReturnTrack) Id="\d+"[^>]*>')


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


def find_master_track_span(xml):
    """Char span (start, end) of the master track element.

    Live 11 names it <MasterTrack>; Live 12 renamed it to <MainTrack>, and the
    open tag may carry attributes (e.g. <MainTrack SelectedToolPanel="7" ...>).
    Accept either name, with or without attributes, so master-targeting .als
    patches work on both versions.
    """
    for name in ("MasterTrack", "MainTrack"):
        m = re.search(r"<%s(?:\s[^>]*)?>" % name, xml)
        if not m:
            continue
        close = "</%s>" % name
        e = xml.find(close, m.end())
        if e == -1:
            raise ValueError("unterminated <%s>" % name)
        return (m.start(), e + len(close))
    raise ValueError("no <MasterTrack> or <MainTrack> in document")


def find_return_track_span(xml, return_index):
    """Char span (start, end) of the return_index-th <ReturnTrack> (doc order).

    Real Live 11/12 sets emit return tracks with attributes
    (e.g. <ReturnTrack Id="2" SelectedToolPanel="7" ...>), so match the open
    tag by regex rather than a bare literal. The `(?:\\s[^>]*)?>` bound also
    excludes sibling tags that merely share the prefix (<ReturnTracksListWrapper>).
    """
    close = "</ReturnTrack>"
    open_re = re.compile(r"<ReturnTrack(?:\s[^>]*)?>")
    idx = 0
    for m in open_re.finditer(xml):
        if idx == return_index:
            e = xml.find(close, m.end())
            if e == -1:
                raise ValueError("unterminated <ReturnTrack> %d" % return_index)
            return (m.start(), e + len(close))
        idx += 1
    raise ValueError("return track index %d not found" % return_index)


def _matching_close(xml, tag, open_index):
    """Index just past the close tag matching the element opening at open_index,
    accounting for nested same-name elements and self-closing tags."""
    open_re = re.compile(r'<%s(\s[^>]*?)?(/?)>' % re.escape(tag))
    close = "</%s>" % tag
    m = open_re.match(xml, open_index)
    if not m:
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
        # also swallow the surrounding whitespace/indent on the line
        line_start = out.rfind("\n", 0, s)
        if line_start == -1:
            line_start = s
        out = out[:line_start] + out[e:]
