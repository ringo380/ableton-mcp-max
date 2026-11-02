"""midi_role_utils: features, texture, role resolution, candidate scoring."""
from ableton_mcp_max import midi_role_utils as mru

RM = mru.load_role_map()


def _n(pitch, start, dur=0.5, vel=100):
    return {"pitch": pitch, "start_time": start, "duration": dur, "velocity": vel}


def _mono_line(pitches, dur=0.5, step=0.5, bars=8):
    out, t, i = [], 0.0, 0
    while t < bars * 4:
        out.append(_n(pitches[i % len(pitches)], t, dur))
        t += step
        i += 1
    return out


def _chords(roots, dur, step, bars=8, voices=(0, 4, 7)):
    out, t, i = [], 0.0, 0
    while t < bars * 4:
        r = roots[i % len(roots)]
        out.extend(_n(r + v, t, dur) for v in voices)
        t += step
        i += 1
    return out


def _kit(bars=8):
    out = []
    for bar in range(bars):
        b = bar * 4
        out += [_n(36, b, 0.01, 110), _n(36, b + 2.5, 0.01, 100),
                _n(38, b + 1, 0.01, 105), _n(38, b + 3, 0.01, 105)]
        out += [_n(42, b + q * 0.5, 0.01, 80) for q in range(8)]
    return out


def test_features_measure_polyphony_and_density():
    f = mru.note_features(_chords([48], 2.0, 2.0, bars=2))
    assert f["count"] == 12 and f["max_polyphony"] == 3
    assert f["chord_onset_ratio"] == 1.0 and f["onsets"] == 4
    assert f["median_duration"] == 2.0 and f["coverage"] == 1.0


def test_features_ignore_muted_and_handle_empty():
    assert mru.note_features([]) == {"count": 0}
    muted = [dict(_n(60, 0), mute=True)]
    assert mru.note_features(muted) == {"count": 0}


def test_kit_reads_as_drums():
    t, conf, ev = mru.classify_texture(mru.note_features(_kit()))
    assert t == "drums" and conf >= 0.8


def test_low_mono_line_reads_as_bass_even_with_octave_dyads():
    notes = _mono_line([36, 36, 43, 41], dur=0.5, step=0.5)
    notes += [_n(n["pitch"] + 12, n["start_time"], 0.5) for n in notes[::8]]
    t, _c, _e = mru.classify_texture(mru.note_features(notes))
    assert t == "bass"


def test_sustained_triads_read_as_pad_and_comped_as_keys_and_short_as_stabs():
    assert mru.classify_texture(mru.note_features(_chords([60, 65], 4.0, 4.0)))[0] == "pad"
    assert mru.classify_texture(mru.note_features(_chords([60, 65], 0.75, 1.0)))[0] == "keys"
    assert mru.classify_texture(mru.note_features(_chords([60, 65], 0.25, 0.5)))[0] == "stabs"


def test_fast_short_mono_reads_as_arp_and_slow_as_lead():
    assert mru.classify_texture(mru.note_features(
        _mono_line([60, 64, 67, 72], dur=0.2, step=0.25)))[0] == "arp"
    assert mru.classify_texture(mru.note_features(
        _mono_line([67, 69, 71, 74, 72], dur=0.5, step=1.0)))[0] == "lead"
    assert mru.classify_texture(mru.note_features(
        _mono_line([67, 69], dur=3.5, step=4.0)))[0] == "sustained_line"


def test_a_handful_of_hits_is_sparse():
    t, _c, _e = mru.classify_texture(mru.note_features([_n(60, 0), _n(63, 1)]))
    assert t == "sparse"


def test_name_hints():
    assert mru.name_role("Keyboard MIDI", RM) == "keys"
    assert mru.name_role("Lead Vocals", RM) == "vocal"
    assert mru.name_role("Drums MIDI (melodic ch1)", RM) == "drums"
    assert mru.name_role("Woodwinds", RM) == "winds"
    assert mru.name_role("Strings", RM) == "strings"
    assert mru.name_role("Track 7", RM) is None


def test_resolve_role_hint_refines_within_family_and_content_wins_otherwise():
    assert mru.resolve_role("pad", "strings") == ("strings", None)
    assert mru.resolve_role("lead", "vocal") == ("vocal", None)
    assert mru.resolve_role("arp", "winds") == ("winds", None)
    role, conflict = mru.resolve_role("arp", "drums", count=800)
    assert role == "arp" and "name says drums" in conflict
    role, conflict = mru.resolve_role("bass", "fx", count=400)
    assert role == "bass" and conflict
    assert mru.resolve_role("keys", None) == ("keys", None)


def test_small_part_defers_to_its_name():
    assert mru.resolve_role("arp", "brass", count=12) == ("brass", None)


def test_describe_part_end_to_end():
    d = mru.describe_part(_chords([60, 65], 0.75, 1.0), "Keyboard MIDI", RM)
    assert d["role"] == "keys" and d["texture"] == "keys" and d["conflict"] is None
    assert d["key_guess"]["key"] in ("C major", "F major")
    d = mru.describe_part(_kit(), "Woodwinds", RM)
    assert d["role"] == "drums" and "name says winds" in d["conflict"]
    assert d["confidence"] < 0.8


def test_guess_key_minor():
    hist = [0.0] * 12
    for pc, w in ((8, 5), (11, 3), (1, 2), (3, 3), (4, 1), (6, 2), (8, 1)):
        hist[pc] += w
    assert mru.guess_key(hist)["key"] == "G# minor"
    assert mru.guess_key([0.0] * 12) is None


def _rows():
    return [
        {"name": "E-Piano Rhodish", "uri": "u:1", "folder": "Drift/Piano & Keys", "tags": "Drift Piano Keys"},
        {"name": "E-Piano Rhodish", "uri": "u:1r", "folder": "Instrument Rack/Piano & Keys", "tags": ""},
        {"name": "E-Piano Basic", "uri": "u:2", "folder": "Electric/Piano & Keys", "tags": "Electric Piano Keys"},
        {"name": "Dense Lead", "uri": "u:3", "folder": "Drift/Synth Lead", "tags": ""},
        {"name": "Glassy Keys", "uri": "u:4", "folder": "Wavetable/Synth Keys", "tags": ""},
        {"name": "Big Sub", "uri": "u:5", "folder": "Drift/Bass", "tags": ""},
    ]


def test_score_candidates_prefers_role_folder_dedupes_and_penalizes_used():
    out = mru.score_candidates(_rows(), "keys", RM, intent="warm rhodes",
                               used_names=["E-Piano Rhodish"], limit=5)
    names = [c["name"] for c in out]
    assert "Dense Lead" not in names and "Big Sub" not in names
    assert names.count("E-Piano Rhodish") == 1
    assert names[0] == "E-Piano Basic"           # Electric bonus + primary folder
    assert "Glassy Keys" in names                # secondary folder still offered
    assert all("why" in c and c["score"] > 0 for c in out)
    rhod = next(c for c in out if c["name"] == "E-Piano Rhodish")
    assert "already used" in rhod["why"]
    assert rhod["uri"] in ("u:1", "u:1r")        # one copy, the higher-scored one
    fresh = mru.score_candidates(_rows(), "keys", RM, intent="warm rhodes")
    assert fresh[0]["name"] == "E-Piano Basic"
    assert [c["name"] for c in fresh].index("E-Piano Rhodish") < \
        [c["name"] for c in fresh].index("Glassy Keys")   # unused: ahead of related


def test_score_candidates_intent_terms_lift_a_match():
    out = mru.score_candidates(_rows(), "keys", RM, intent="basic")
    assert out[0]["name"] == "E-Piano Basic" and "intent basic" in out[0]["why"]


def test_intent_hit_in_the_preset_name_beats_one_in_its_folder():
    rows = [{"name": "Basic Flange Harp", "uri": "u:h", "folder": "Tension/Guitar & Plucked", "tags": ""},
            {"name": "Nylon Concerto Guitar", "uri": "u:g", "folder": "Tension/Guitar & Plucked", "tags": ""}]
    out = mru.score_candidates(rows, "pluck", RM, intent="guitar")
    assert out[0]["name"] == "Nylon Concerto Guitar"


def test_score_kits_and_plugins():
    items = [{"name": "Boom Bap Kit.adg", "uri": "k:1", "is_loadable": True},
             {"name": "909 Core Kit.adg", "uri": "k:2", "is_loadable": True},
             {"name": "Drum Rack", "uri": "d", "is_loadable": True, "is_device": True},
             {"name": "Drum Hits", "uri": "f", "is_folder": True}]
    kits = mru.score_kits(items, intent="boom bap", used_names=["909 Core Kit"])
    assert [k["name"] for k in kits] == ["Boom Bap Kit", "909 Core Kit"]
    assert kits[0]["uri"] == "k:1"
    plugs = mru.plugin_candidates("strings", RM, {"Kontakt 8": "p:k", "Serum 2": "p:s"})
    assert [p["name"] for p in plugs] == ["Kontakt 8"]
    assert plugs[0]["patch_selection"] == "manual"
    assert mru.plugin_candidates("strings", RM, {}) == []


def test_feature_terms_steer_bass_by_how_it_moves():
    rows = [
        {"name": "Basic Sub Boom", "uri": "u:s", "folder": "Instrument Rack/Bass", "tags": ""},
        {"name": "Analog Finger Bass", "uri": "u:a", "folder": "Drift/Bass", "tags": ""},
    ]
    moving = {"onsets_per_beat": 1.6, "pitch_low": 23, "pitch_high": 70}
    out = mru.score_candidates(rows, "bass", RM, features=moving)
    assert out[0]["name"] == "Analog Finger Bass" and "moving line" in out[0]["why"]
    assert "but sub/boom" in out[1]["why"]
    static = {"onsets_per_beat": 0.4, "pitch_low": 36, "pitch_high": 43}
    out = mru.score_candidates(rows, "bass", RM, features=static)
    assert out[0]["name"] == "Basic Sub Boom"
    assert mru.active_feature_terms("bass", RM, None) == []


def test_current_instrument_wins_a_tie_but_not_a_better_match():
    rows = [
        {"name": "Clay Flute", "uri": "u:c", "folder": "Instrument Rack/Winds", "tags": ""},
        {"name": "Indian Flute", "uri": "u:i", "folder": "Instrument Rack/Winds", "tags": ""},
    ]
    out = mru.score_candidates(rows, "winds", RM, current_names=["Indian Flute"])
    assert out[0]["name"] == "Indian Flute" and "current instrument" in out[0]["why"]
    out = mru.score_candidates(rows, "winds", RM, intent="clay",
                               current_names=["Indian Flute"])
    assert out[0]["name"] == "Clay Flute"
    kits = [{"name": "A Kit.adg", "uri": "k:a", "is_loadable": True},
            {"name": "Boom Bap Kit.adg", "uri": "k:b", "is_loadable": True}]
    assert mru.score_kits(kits, current_names=["Boom Bap Kit"])[0]["name"] == "Boom Bap Kit"


def test_name_terms_drop_generic_words():
    assert mru.name_terms("Guitar MIDI") == ["guitar"]
    assert mru.name_terms("Drums MIDI (melodic ch1)") == ["drums", "ch1"]
    assert mru.name_terms("7 Lead Vocals") == ["lead", "vocals"]


def test_intent_for_mentions_role_texture_and_context():
    d = {"role": "strings", "texture": "pad", "key_guess": {"key": "G# minor"}}
    s = mru.intent_for(d, {"genre": "hip-hop", "tempo": 90})
    assert s == "strings pad hip-hop 90 bpm G# minor"
