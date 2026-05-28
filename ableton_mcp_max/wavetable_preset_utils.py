"""Pure helpers for generating Wavetable .adv presets. No Live dependencies.

Like the other *_utils modules, these run server-side only. They patch the
factory-default Wavetable preset XML to set the controls that Live's
`device.parameters` API does NOT expose:
  - oscillator wavetable selection  (SpriteName1 / SpriteName2)
  - unison mode                     (Voice_Unison_Mode)
  - unison voice count              (Voice_Unison_VoiceCount)

Factory wavetables are referenced purely by NAME, with an empty <UserSprite>
block, so a string swap is sufficient (no embedded wavetable payload needed).
The automatable extras (unison amount, osc on, wave position) are patched via
the parameter's <Manual> value.

`build_wavetable_adv` takes the decompressed default XML as input so it stays
pure/testable; the caller is responsible for reading + gzip-decompressing the
factory default and gzip-compressing the result.
"""
from ableton_mcp_max.preset_patch import (
    set_attr as _set_attr,
    set_manual as _set_manual,
    get_attr,
    validate_unit as _clamp_unit,
    validate_int_range,
    validate_choice,
)

# Live 11 Wavetable unison-mode dropdown order (index = stored int value).
_UNISON_ORDER = [
    "none", "classic", "shimmer", "noise",
    "phase sync", "position spread", "random note",
]
UNISON_MODES = {name: i for i, name in enumerate(_UNISON_ORDER)}

MIN_VOICES = 2
MAX_VOICES = 8


def resolve_unison_mode(mode):
    """Resolve a unison mode (name or int 0..6) to its stored int value."""
    return validate_choice(mode, _UNISON_ORDER, "unison mode")


def unison_mode_name(value):
    """Inverse of resolve_unison_mode: int -> canonical name (for readback)."""
    i = int(value)
    return _UNISON_ORDER[i] if 0 <= i < len(_UNISON_ORDER) else str(value)


def validate_voices(voices):
    """Coerce/validate a unison voice count to an int in MIN..MAX_VOICES."""
    return validate_int_range(voices, MIN_VOICES, MAX_VOICES, "voices")


def _validate_table(name, label):
    name = str(name).strip()
    if not name:
        raise ValueError("%s must be a non-empty wavetable name." % label)
    if '"' in name:
        raise ValueError("%s must not contain a double-quote." % label)
    return name


def build_wavetable_adv(default_xml, table1, table2=None, unison_mode="classic",
                        voices=7, amount=0.85, osc1_pos=None, osc2_pos=None,
                        osc2_on=True, name="MCP Wavetable"):
    """Patch the factory-default Wavetable XML into a configured preset.

    Parameters
    - default_xml: decompressed factory Wavetable.adv XML (str).
    - table1/table2: factory wavetable name(s) for Osc 1 / Osc 2 (e.g.
      "Basic Shapes", "Quad Saw"). table2 defaults to table1.
    - unison_mode: name or int (see UNISON_MODES); default "classic" (supersaw).
    - voices: unison voice count 2..8.
    - amount: unison amount 0.0..1.0.
    - osc1_pos/osc2_pos: optional wave position 0.0..1.0 (left as-is when None).
    - osc2_on: enable Osc 2 (default True).
    - name: preset display name written to <UserName>.

    Returns the patched XML string. Raises ValueError on invalid input.
    """
    t1 = _validate_table(table1, "table1")
    t2 = _validate_table(table2 if table2 is not None else table1, "table2")
    mode_int = resolve_unison_mode(unison_mode)
    n_voices = validate_voices(voices)
    amt = _clamp_unit(amount, "amount")
    disp = _validate_table(name, "name")

    xml = default_xml
    xml = _set_attr(xml, "SpriteName1", t1)
    xml = _set_attr(xml, "SpriteName2", t2)
    xml = _set_attr(xml, "Voice_Unison_Mode", mode_int)
    xml = _set_attr(xml, "Voice_Unison_VoiceCount", n_voices)
    xml = _set_manual(xml, "Voice_Unison_Amount", amt)
    xml = _set_manual(xml, "Voice_Oscillator2_On", "true" if osc2_on else "false")
    if osc1_pos is not None:
        xml = _set_manual(xml, "Voice_Oscillator1_Wavetables_WavePosition",
                          _clamp_unit(osc1_pos, "osc1_pos"))
    if osc2_pos is not None:
        xml = _set_manual(xml, "Voice_Oscillator2_Wavetables_WavePosition",
                          _clamp_unit(osc2_pos, "osc2_pos"))
    xml = _set_attr(xml, "UserName", disp)
    return xml


def summarize_wavetable_adv(xml):
    """Read back the key fields from a (decompressed) Wavetable preset.

    Returns a dict with table1/table2, unison_mode (int) + unison_mode_name,
    voices, and name. Used to verify a generated preset. Missing fields are
    reported as None rather than raising.
    """
    def attr(tag):
        return get_attr(xml, tag)

    mode = attr("Voice_Unison_Mode")
    mode_int = int(mode) if mode is not None and mode.lstrip("-").isdigit() else None
    voices = attr("Voice_Unison_VoiceCount")
    return {
        "name": attr("UserName"),
        "table1": attr("SpriteName1"),
        "table2": attr("SpriteName2"),
        "unison_mode": mode_int,
        "unison_mode_name": unison_mode_name(mode_int) if mode_int is not None else None,
        "voices": int(voices) if voices is not None and voices.isdigit() else None,
    }
