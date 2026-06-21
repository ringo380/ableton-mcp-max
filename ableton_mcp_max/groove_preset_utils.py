"""Pure helpers for the groove-pool .alc clip-embed backdoor (issue #36).

Server-only (Live's embedded Python cannot import this). A factory .agr is
plain XML <Ableton><Groove><Name><Clip><Value><MidiClip>; this transforms its
<Groove> into a project GroovePool <Groove Id="N"> entry and injects it into a
factory .alc wrapper. See docs/.../2026-06-21-groove-pool-loading-design.md.
"""
import re
import os

# Live-11 .agr MidiClips carry these cosmetic nodes; a Live-12 LiveSet groove
# schema REJECTS them ("corrupt ... Unexpected value for int node: Major").
# They are presentation-only (not groove-defining), so stripping is safe on
# both versions.
_COSMETIC_TAGS = (
    "ScaleInformation", "IsInKey", "NoteSpellingPreference",
    "PreferFlatRootNote", "NoteEditorFoldOutZoom", "NoteEditorFoldOutScroll",
    "NoteEditorFoldScaleZoom", "NoteEditorFoldScaleScroll",
)


def _xml_unescape(s):
    return (s.replace("&lt;", "<").replace("&gt;", ">")
             .replace("&quot;", '"').replace("&apos;", "'")
             .replace("&amp;", "&"))


def groove_pool_name(agr_xml):
    """The groove's internal <Name> (the pool's display name), unescaped."""
    m = re.search(r'<Groove>.*?<Name Value="([^"]*)"', agr_xml, re.S)
    if not m:
        raise ValueError("no <Groove><Name> in .agr XML")
    return _xml_unescape(m.group(1))


def _strip_cosmetic(xml):
    for tag in _COSMETIC_TAGS:
        xml = re.sub(r'\s*<%s[ >].*?</%s>' % (tag, tag), "", xml, flags=re.S)
        xml = re.sub(r'\s*<%s[^>]*/>' % tag, "", xml)
    return xml


def agr_to_pool_groove(agr_xml, groove_id=0):
    """Convert a factory .agr <Groove> into a GroovePool <Groove Id="N"> entry."""
    m = re.search(r'<Groove>(.*?)</Groove>', agr_xml, re.S)
    if not m:
        raise ValueError("no <Groove> element in .agr XML")
    inner = m.group(1)
    # Drop the Groove-level LomId (first one, before <Clip>).
    inner = re.sub(r'\s*<LomId Value="[^"]*" />', "", inner, count=1)
    inner = _strip_cosmetic(inner)
    # Drop the source-provenance <OriginalFileRef> block: ~8 factory grooves
    # carry a Live-11 <RelativePath><RelativePathElement Dir=.. Id=..> whose
    # schema a Live-12 LiveSet rejects ("Required attribute 'Value' missing").
    # It is provenance only (where the .agr came from), not groove data, so
    # removing it is safe. (OriginalFileRef is never self-nested.)
    inner = re.sub(r'\s*<OriginalFileRef>.*?</OriginalFileRef>', "", inner,
                   flags=re.S)
    return '<Groove Id="%d">%s</Groove>' % (groove_id, inner)


def build_carrier_alc(wrapper_xml, groove_entry, groove_id=0):
    """Inject `groove_entry` into a factory .alc LiveSet so loading it merges
    the groove into the project Groove Pool. Returns decompressed XML (caller
    gzips).

    The wrapper's device chain is left INTACT: emptying nested `<Devices>`
    blocks with a flat regex corrupts the XML (an instrument rack nests its own
    `<Devices>`, so a lazy match closes at the wrong tag). Loading the carrier
    appends a throwaway track (it carries the wrapper's instrument); the caller
    deletes exactly the appended track(s) right after, so nothing the wrapper
    carries persists in the user's set."""
    out = wrapper_xml
    # 1. Replace the (empty) pool's <Grooves .../> with our groove.
    new_grooves = "<Grooves>\n%s\n</Grooves>" % groove_entry
    out, n = re.subn(r'<Grooves\s*/>', lambda _: new_grooves, out, count=1)
    if not n:
        out = re.sub(r'<Grooves>.*?</Grooves>', lambda _: new_grooves, out, count=1,
                     flags=re.S)
    # 2. Point DefaultGrooveId + every clip GrooveSettings at the groove.
    out = re.sub(r'<DefaultGrooveId Value="-?\d+" />',
                 '<DefaultGrooveId Value="%d" />' % groove_id, out, count=1)
    out = re.sub(r'(<GrooveSettings>\s*<GrooveId Value=")-?\d+("\s*/>)',
                 r'\g<1>%d\g<2>' % groove_id, out, flags=re.S)
    return out


def is_xml_agr(path):
    """True if the .agr is plain-XML (loadable via the backdoor). About half of
    Ableton's factory grooves are instead a proprietary BINARY format (magic
    `ab 1e 56 78`) this XML pipeline cannot transform - those return False."""
    try:
        with open(path, "rb") as f:
            head = f.read(8).lstrip()
        return head[:1] == b"<"
    except OSError:
        return False


def read_groove_xml(path):
    """Read a plain-XML .agr to text, or raise ValueError for the binary format.
    Centralizes the format guard so load_groove_to_pool gives a clear message
    instead of a UnicodeDecodeError on a binary groove."""
    if not is_xml_agr(path):
        raise ValueError(
            "groove %r is in Ableton's binary .agr format, which this tool "
            "cannot load - drag it into the Groove Pool by hand, or pick a "
            "loadable groove (search_grooves marks each one's `loadable`)."
            % os.path.basename(path))
    with open(path, encoding="utf-8") as f:
        return f.read()


def _walk_agr(roots):
    """Yield (path, name, category, source) for every .agr under each root."""
    for root, source in roots:
        if not root or not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                if fn.lower().endswith(".agr"):
                    path = os.path.join(dirpath, fn)
                    yield (path, os.path.splitext(fn)[0],
                           os.path.basename(dirpath), source)


def list_grooves(roots, query="", limit=50):
    terms = [t for t in query.lower().split() if t]
    rows = []
    for path, name, category, source in _walk_agr(roots):
        hay = (name + " " + category).lower()
        if terms and not any(t in hay for t in terms):
            continue
        rows.append({"name": name, "file": os.path.basename(path),
                     "category": category, "path": path, "source": source,
                     "loadable": is_xml_agr(path)})
    rows.sort(key=lambda r: r["name"].lower())
    return rows[:limit]


def pool_has_name(pool_grooves, name):
    """Index of the groove named `name` in a get_groove_pool 'grooves' list,
    or None. Used to skip duplicate adds (pool removal is infeasible)."""
    for g in pool_grooves:
        if g.get("name") == name:
            return g.get("index")
    return None


def resolve_groove_source(name_or_path, roots):
    if name_or_path.lower().endswith(".agr") and os.path.isfile(name_or_path):
        return name_or_path
    want = name_or_path.lower().strip()
    matches = [(p, n) for (p, n, _c, _s) in _walk_agr(roots) if n.lower() == want]
    if len(matches) == 1:
        return matches[0][0]
    if len(matches) > 1:
        raise ValueError("multiple grooves named %r: %s - pass a full .agr path"
                         % (name_or_path, sorted({n for _p, n in matches})))
    near = sorted({n for (_p, n, _c, _s) in _walk_agr(roots)
                   if want in n.lower() or n.lower() in want})[:8]
    raise ValueError("no groove matching %r%s" % (
        name_or_path, (" - did you mean: %s" % near) if near else ""))
