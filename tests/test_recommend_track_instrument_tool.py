"""recommend_track_instrument / recommend_set_instruments / apply_instrument_plan
against a fake Live and a temp catalog."""
import importlib
import json


def _chords(roots, dur, step, bars=8, voices=(0, 4, 7)):
    out, t, i = [], 0.0, 0
    while t < bars * 4:
        r = roots[i % len(roots)]
        out.extend({"pitch": r + v, "start_time": t, "duration": dur,
                    "velocity": 100} for v in voices)
        t += step
        i += 1
    return out


def _bassline(bars=8):
    out, t = [], 0.0
    while t < bars * 4:
        out.append({"pitch": 36 if int(t) % 2 == 0 else 43, "start_time": t,
                    "duration": 0.5, "velocity": 100})
        t += 0.5
    return out


def _kit(bars=8):
    out = []
    for bar in range(bars):
        b = bar * 4
        out += [{"pitch": 36, "start_time": b, "duration": 0.01, "velocity": 110},
                {"pitch": 38, "start_time": b + 1, "duration": 0.01, "velocity": 105},
                {"pitch": 36, "start_time": b + 2.5, "duration": 0.01, "velocity": 100},
                {"pitch": 38, "start_time": b + 3, "duration": 0.01, "velocity": 105}]
        out += [{"pitch": 42, "start_time": b + q * 0.5, "duration": 0.01,
                 "velocity": 80} for q in range(8)]
    return out


class FakeLive:
    """Tracks: list of dicts {name, is_midi, devices, notes (session slot 0),
    arr_notes}. Records every load."""

    def __init__(self, tracks, plugins=None, kits=None, append_on_load=False):
        self.tracks = tracks
        self.plugins = plugins or {}
        self.kits = kits or []
        self.loads = []
        self.append_on_load = append_on_load

    def send_command(self, cmd, params=None, **kw):
        p = params or {}
        if cmd == "get_session_info":
            return {"track_count": len(self.tracks), "tempo": 90.0}
        if cmd == "get_track_info":
            t = self.tracks[p["track_index"]]
            return {"index": p["track_index"], "name": t["name"],
                    "is_midi_track": t["is_midi"],
                    "devices": [{"name": d} for d in t["devices"]],
                    "clip_slots": [{"index": 0, "has_clip": bool(t.get("notes"))}]}
        if cmd == "get_clip_notes":
            t = self.tracks[p["track_index"]]
            if p.get("clip_location") == "arrangement":
                if "arr_notes" not in t:
                    raise IndexError("Arrangement clip index out of range")
                return {"notes": t["arr_notes"]}
            if not t.get("notes"):
                raise Exception("No clip in slot")
            return {"notes": t["notes"]}
        if cmd == "get_browser_items_at_path":
            path = p["path"]
            if path == "plugins":
                return {"items": [{"name": v, "is_folder": True} for v in self.plugins]}
            if path.startswith("plugins/"):
                vendor = path.split("/", 1)[1]
                return {"items": [{"name": n, "is_loadable": True, "uri": "plug:" + n}
                                  for n in self.plugins.get(vendor, [])]}
            if path == "drums":
                return {"items": [{"name": k + ".adg", "is_loadable": True,
                                   "uri": "kit:" + k} for k in self.kits]}
            return {"items": []}
        if cmd == "load_browser_item":
            self.loads.append((p["track_index"], p["item_uri"]))
            t = self.tracks[p["track_index"]]
            name = p["item_uri"].split(":", 1)[1]
            t["devices"] = (t["devices"] + [name]) if self.append_on_load else [name]
            return {"loaded": True, "new_devices": [name]}
        raise AssertionError("unexpected command %s" % cmd)


ROWS = [
    ("E-Piano Rhodish", "pre:E-Piano Rhodish", "Drift/Piano & Keys", "Drift Piano Keys"),
    ("E-Piano Basic", "pre:E-Piano Basic", "Electric/Piano & Keys", "Electric Piano Keys"),
    ("Analog Bass", "pre:Analog Bass", "Drift/Bass", "Drift Bass"),
    ("Big Sub", "pre:Big Sub", "Wavetable/Bass", "Wavetable Bass"),
    ("Dense Lead", "pre:Dense Lead", "Drift/Synth Lead", ""),
    ("Evangelis Strings", "pre:Evangelis Strings", "Drift/Strings", ""),
    ("Shaker Box", "pre:Shaker Box", "Drift/Percussive", ""),
]


def _server(tmp_path, monkeypatch, live):
    monkeypatch.setenv("ABLETON_MCP_CATALOG_DB", str(tmp_path / "c.db"))
    import ableton_mcp_max.server as server
    importlib.reload(server)
    server._catalog_db_conn = None
    server._catalog_device_indexed = True      # rows inserted by hand below
    server._installed_plugins_cache = None
    monkeypatch.setattr(server, "get_ableton_connection", lambda: live)
    conn = server._catalog_conn()
    for name, uri, folder, tags in ROWS:
        conn.execute(
            "INSERT INTO items(domain,name,path,uri,source,folder,loadable,tags,"
            "indexed_at) VALUES('device_preset',?,NULL,?,'factory',?,1,?,1.0)",
            (name, uri, folder, tags))
    conn.commit()
    return server


def _live():
    return FakeLive(
        [{"name": "Keys", "is_midi": False, "devices": []},
         {"name": "Keys MIDI", "is_midi": True, "devices": ["Dense Lead"],
          "notes": _chords([60, 65], 0.75, 1.0)},
         {"name": "Bass MIDI", "is_midi": True, "devices": ["Analog Bass"],
          "notes": _bassline()},
         {"name": "Drums MIDI", "is_midi": True, "devices": ["909 Core Kit"],
          "notes": _kit()},
         {"name": "Empty MIDI", "is_midi": True, "devices": []}],
        plugins={"Native Instruments": ["Kontakt 8"], "Xfer Records": ["Serum 2"]},
        kits=["Boom Bap Kit", "909 Core Kit"])


def test_recommend_track_instrument_reads_notes_and_ranks_presets(tmp_path, monkeypatch):
    live = _live()
    server = _server(tmp_path, monkeypatch, live)
    out = json.loads(server.recommend_track_instrument(None, 1, intent="warm"))
    assert out["ok"] is True, out
    d = out["data"]
    assert d["analysis"]["role"] == "keys" and d["analysis"]["conflict"] is None
    assert d["clip"] == {"index": 0, "location": "session", "note_count": 96}
    assert d["doubles_audio_track"] == "Keys"
    assert d["current_devices"] == ["Dense Lead"]
    names = [c["name"] for c in d["candidates"]]
    assert names and set(names) <= {"E-Piano Rhodish", "E-Piano Basic"}
    assert [p["name"] for p in d["plugins"]] == ["Kontakt 8"]
    assert d["plugins"][0]["patch_selection"] == "manual"
    assert "90 bpm" in d["intent"] and d["intent"].startswith("warm keys")
    assert live.loads == []                      # propose only


def test_recommend_track_instrument_ranks_used_sounds_down(tmp_path, monkeypatch):
    live = _live()
    live.tracks[0] = {"name": "Other", "is_midi": True, "devices": ["Analog Bass"],
                      "notes": _bassline()}
    live.tracks[2]["devices"] = ["Dense Lead"]
    server = _server(tmp_path, monkeypatch, live)
    d = json.loads(server.recommend_track_instrument(None, 2))["data"]
    assert d["analysis"]["role"] == "bass"
    assert d["candidates"][0]["name"] == "Big Sub"
    used = next(c for c in d["candidates"] if c["name"] == "Analog Bass")
    assert "already used" in used["why"]
    # the track's own current sound is not "used elsewhere": it wins ties instead
    live.tracks[2]["devices"] = ["Analog Bass"]
    d = json.loads(server.recommend_track_instrument(None, 2))["data"]
    cur = next(c for c in d["candidates"] if c["name"] == "Analog Bass")
    assert "current instrument" in cur["why"]


def test_recommend_track_instrument_drums_use_kits_and_arrangement_fallback(tmp_path, monkeypatch):
    live = _live()
    live.tracks[3]["notes"] = []
    live.tracks[3]["arr_notes"] = _kit()
    server = _server(tmp_path, monkeypatch, live)
    d = json.loads(server.recommend_track_instrument(None, 3, intent="boom bap"))["data"]
    assert d["clip"]["location"] == "arrangement"
    assert d["analysis"]["role"] == "drums"
    assert [c["name"] for c in d["candidates"]] == ["Boom Bap Kit", "909 Core Kit"]
    assert d["candidates"][0]["uri"] == "kit:Boom Bap Kit"


def test_recommend_track_instrument_rejects_audio_and_missing_tracks(tmp_path, monkeypatch):
    server = _server(tmp_path, monkeypatch, _live())
    assert json.loads(server.recommend_track_instrument(None, 0))["ok"] is False
    assert json.loads(server.recommend_track_instrument(None, 9))["ok"] is False
    out = json.loads(server.recommend_track_instrument(None, 4))
    assert out["ok"] is False and "no MIDI clip" in out["error"]


def test_recommend_set_instruments_builds_a_plan(tmp_path, monkeypatch):
    live = _live()
    server = _server(tmp_path, monkeypatch, live)
    out = json.loads(server.recommend_set_instruments(None))
    assert out["ok"] is True, out
    d = out["data"]
    assert d["tempo"] == 90.0 and d["key_guess"]["key"]
    assert [p["track_index"] for p in d["parts"]] == [1, 2, 3]
    assert [s["track_index"] for s in d["skipped"]] == [4]
    # Keys gets a swap; Bass and Drums already hold their top match -> keep
    assert [p["track_index"] for p in d["plan"]] == [1]
    assert [k["track_index"] for k in d["keep"]] == [2, 3]
    assert all(p["uri"] and p["candidate"] for p in d["plan"])
    assert "pitch_class_histogram" not in d["parts"][0]
    assert live.loads == []


def test_recommend_set_instruments_key_is_a_vote_of_confident_parts(tmp_path, monkeypatch):
    server = _server(tmp_path, monkeypatch, _live())
    parts = [
        {"analysis": {"texture": "keys", "key_guess": {"key": "G# minor", "correlation": 0.9}},
         "pitch_class_histogram": [1, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 1]},
        {"analysis": {"texture": "bass", "key_guess": {"key": "G# minor", "correlation": 0.8}},
         "pitch_class_histogram": [0, 0, 0, 0, 0, 0, 0, 0, 3, 0, 0, 0]},
        {"analysis": {"texture": "drums", "key_guess": {"key": "F# major", "correlation": 0.95}},
         "pitch_class_histogram": [0] * 12},
        {"analysis": {"texture": "lead", "key_guess": {"key": "C major", "correlation": 0.5}},
         "pitch_class_histogram": [5] + [0] * 11},
    ]
    k = server._set_key_guess(parts)
    assert k["key"] == "G# minor" and k["votes"] == {"G# minor": 2}
    assert "histogram_key" in k
    only_drums = [parts[2]]
    assert server._set_key_guess(only_drums) is None or "key" in server._set_key_guess(only_drums)


def test_recommend_track_instrument_uses_the_track_name_as_intent(tmp_path, monkeypatch):
    live = _live()
    live.tracks[1]["name"] = "Wurli MIDI"
    server = _server(tmp_path, monkeypatch, live)
    conn = server._catalog_conn()
    conn.execute(
        "INSERT INTO items(domain,name,path,uri,source,folder,loadable,tags,"
        "indexed_at) VALUES('device_preset','E-Piano Wurli',NULL,'pre:E-Piano Wurli',"
        "'factory','Electric/Piano & Keys',1,'',1.0)")
    conn.commit()
    d = json.loads(server.recommend_track_instrument(None, 1))["data"]
    assert d["candidates"][0]["name"] == "E-Piano Wurli"
    assert "intent wurli" in d["candidates"][0]["why"]


def test_recommend_set_instruments_does_not_hand_two_parts_the_same_sound(tmp_path, monkeypatch):
    live = _live()
    live.tracks.append({"name": "Sub MIDI", "is_midi": True, "devices": [],
                        "notes": _bassline()})
    server = _server(tmp_path, monkeypatch, live)
    d = json.loads(server.recommend_set_instruments(None))["data"]
    # Bass MIDI keeps Analog Bass; Sub MIDI must not be handed the same sound
    assert [k["name"] for k in d["keep"] if k["name"] == "Bass MIDI"]
    sub = next(p for p in d["plan"] if p["name"] == "Sub MIDI")
    assert sub["candidate"] == "Big Sub"
    sub_part = next(p for p in d["parts"] if p["name"] == "Sub MIDI")
    used = next(c for c in sub_part["candidates"] if c["name"] == "Analog Bass")
    assert "already used" in used["why"]


def test_recommend_set_instruments_honours_track_indices(tmp_path, monkeypatch):
    server = _server(tmp_path, monkeypatch, _live())
    d = json.loads(server.recommend_set_instruments(None, track_indices=[0, 2]))["data"]
    assert [p["track_index"] for p in d["parts"]] == [2]
    assert d["skipped"][0]["reason"] == "not a MIDI track"


def test_apply_instrument_plan_dry_run_then_loads_and_verifies(tmp_path, monkeypatch):
    live = _live()
    server = _server(tmp_path, monkeypatch, live)
    plan = [{"track_index": 1, "uri": "pre:E-Piano Basic", "candidate": "E-Piano Basic"}]
    dry = json.loads(server.apply_instrument_plan(None, plan))
    assert dry["ok"] is True and dry["data"]["dry_run"] is True and live.loads == []
    out = json.loads(server.apply_instrument_plan(None, plan, confirm=True))
    assert out["ok"] is True, out
    assert live.loads == [(1, "pre:E-Piano Basic")]
    a = out["data"]["applied"][0]
    assert a["verified"] is True and a["devices_after"] == ["E-Piano Basic"]


def test_apply_instrument_plan_catches_an_append_instead_of_a_swap(tmp_path, monkeypatch):
    live = _live()
    live.append_on_load = True
    server = _server(tmp_path, monkeypatch, live)
    plan = [{"track_index": 1, "uri": "pre:E-Piano Basic", "candidate": "E-Piano Basic"}]
    out = json.loads(server.apply_instrument_plan(None, plan, confirm=True))
    assert out["ok"] is False
    row = out["data"]["failed"][0]
    assert row["verified"] is False and "Dense Lead" in row["why"]
    assert row["devices_before"] == ["Dense Lead"]
    assert row["devices_after"] == ["Dense Lead", "E-Piano Basic"]


def test_recommend_set_instruments_keeps_a_fitting_current_sound(tmp_path, monkeypatch):
    live = _live()
    live.tracks[3]["devices"] = ["Boom Bap Kit"]
    live.tracks.append({"name": "Brass MIDI", "is_midi": True, "devices": ["Soft Brass"],
                        "notes": [{"pitch": 60, "start_time": 0, "duration": 0.25, "velocity": 90},
                                  {"pitch": 63, "start_time": 0.5, "duration": 0.25, "velocity": 90}]})
    server = _server(tmp_path, monkeypatch, live)
    d = json.loads(server.recommend_set_instruments(None))["data"]
    kept = {k["name"]: k["reason"] for k in d["keep"]}
    assert "already the top match" in kept["Drums MIDI"]
    assert "too few notes" in kept["Brass MIDI"]
    assert [p["name"] for p in d["plan"]] == ["Keys MIDI"]
    assert "Bass MIDI" in kept
    assert d["plan"][0]["replaces"] == ["Dense Lead"] and d["plan"][0]["conflict"] is None


def test_apply_instrument_plan_reports_a_device_that_did_not_land(tmp_path, monkeypatch):
    live = _live()
    server = _server(tmp_path, monkeypatch, live)
    plan = [{"track_index": 2, "uri": "pre:Big Sub", "candidate": "Something Else"}]
    out = json.loads(server.apply_instrument_plan(None, plan, confirm=True))
    assert out["ok"] is False and out["data"]["failed"][0]["verified"] is False
    assert json.loads(server.apply_instrument_plan(None, []))["ok"] is False
    assert json.loads(server.apply_instrument_plan(None, [{"uri": "x"}]))["ok"] is False
