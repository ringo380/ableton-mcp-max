"""Device-agnostic helpers for patching Ableton preset XML. No Live deps.

The Live LOM only exposes a device's *automatable* parameters. Choosers, file
references, structural state, and macro mappings live only in the preset XML
(`.adv`/`.adg`, which are gzipped). These helpers patch a known-good factory
preset by tag, so each device tool stays thin and is unit-testable offline.

Two element shapes recur in Live presets:
  - self-closing attribute:   <SpriteName1 Value="Basic Shapes" />
  - a parameter block:        <Foo><Manual Value="0.5" /> ...automation... </Foo>

`set_attr` handles the first; `set_manual` the second. `scope` narrows a patch
to one nested block when a tag name repeats (e.g. EQ Eight's per-band <Mode>).
All functions are pure: they take an XML string and return a new one.
"""
import re


def set_attr(xml, tag, value, required=True):
    """Set Value="..." on a self-closing <tag Value="..." /> element.

    Raises ValueError if the tag is absent (when required) or appears more than
    once (ambiguous). Returns the patched XML.
    """
    pattern = r'(<%s Value=")[^"]*("\s*/>)' % re.escape(tag)
    new, n = re.subn(pattern, lambda m: m.group(1) + str(value) + m.group(2), xml)
    if n == 0:
        if required:
            raise ValueError("expected <%s Value=.../> not found in preset." % tag)
        return xml
    if n > 1:
        raise ValueError(
            "tag <%s> appears %d times; use scope() to disambiguate." % (tag, n)
        )
    return new


def set_manual(xml, container_tag, value, occurrence=0):
    """Set <Manual Value="..."> inside the Nth <container_tag>...</container_tag>.

    `occurrence` is 0-based among same-named containers. Raises ValueError if the
    container or its <Manual> is missing.
    """
    blocks = list(re.finditer(
        r'<%s>.*?</%s>' % (re.escape(container_tag), re.escape(container_tag)),
        xml, re.S,
    ))
    if not blocks:
        raise ValueError("param container <%s> not found in preset." % container_tag)
    if occurrence >= len(blocks):
        raise ValueError(
            "container <%s> occurrence %d out of range (have %d)."
            % (container_tag, occurrence, len(blocks))
        )
    m = blocks[occurrence]
    block, n = re.subn(
        r'(<Manual Value=")[^"]*(")',
        lambda mm: mm.group(1) + str(value) + mm.group(2),
        m.group(0), count=1,
    )
    if n == 0:
        raise ValueError("no <Manual Value=...> inside <%s>." % container_tag)
    return xml[:m.start()] + block + xml[m.end():]


def scope(xml, outer_tag, fn, occurrence=0):
    """Apply `fn(inner_xml)->inner_xml` within the Nth <outer_tag> block.

    Lets you target a repeated tag (e.g. <Mode> inside a specific EQ Eight
    <Bands.0>) by first narrowing to the outer block. Raises ValueError if the
    outer block is missing.
    """
    blocks = list(re.finditer(
        r'<%s>.*?</%s>' % (re.escape(outer_tag), re.escape(outer_tag)),
        xml, re.S,
    ))
    if not blocks:
        raise ValueError("scope tag <%s> not found in preset." % outer_tag)
    if occurrence >= len(blocks):
        raise ValueError(
            "scope <%s> occurrence %d out of range (have %d)."
            % (outer_tag, occurrence, len(blocks))
        )
    m = blocks[occurrence]
    patched = fn(m.group(0))
    return xml[:m.start()] + patched + xml[m.end():]


def get_attr(xml, tag):
    """Return the Value of a self-closing <tag Value="..." />, or None."""
    m = re.search(r'<%s Value="([^"]*)" />' % re.escape(tag), xml)
    return m.group(1) if m else None


# --- validators ---------------------------------------------------------

def validate_preset_name(name):
    """Validate a user-supplied preset name (becomes '<name>.adv'/'.adg')."""
    safe = str(name).strip()
    if not safe or "/" in safe or "\\" in safe or safe.startswith("."):
        raise ValueError(
            "invalid preset name %r: use a plain name without slashes or a "
            "leading dot." % (name,)
        )
    if '"' in safe:
        raise ValueError("preset name must not contain a double-quote.")
    return safe


def validate_unit(value, label):
    """Validate a 0.0..1.0 float parameter value."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise ValueError("%s must be a number 0.0..1.0." % label)
    if not (0.0 <= f <= 1.0):
        raise ValueError("%s %s out of range 0.0..1.0." % (label, f))
    return f


def validate_int_range(value, lo, hi, label):
    """Validate/coerce an int within [lo, hi]."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValueError("%s must be an integer %d..%d." % (label, lo, hi))
    if not (lo <= n <= hi):
        raise ValueError("%s %d out of range %d..%d." % (label, n, lo, hi))
    return n


def validate_choice(value, choices, label):
    """Resolve a value (name or int) against an ordered list of choice names.

    Accepts a case-insensitive name or an int index. Returns the int index.
    `choices` is the ordered list where index == stored int value.
    """
    if isinstance(value, bool):
        raise ValueError("%s must be a name or int, not a bool." % label)
    options = ", ".join("%s=%d" % (c, i) for i, c in enumerate(choices))
    if isinstance(value, int):
        if 0 <= value < len(choices):
            return value
        raise ValueError("%s int %d out of range. Valid: %s" % (label, value, options))
    key = str(value).strip().lower()
    for i, c in enumerate(choices):
        if c.lower() == key:
            return i
    raise ValueError("unknown %s %r. Valid: %s" % (label, value, options))
