import gzip
import os
import re

import pytest

from ableton_mcp_max.simpler_preset_utils import (
    build_multisample_part,
    build_simpler_adv,
)

FACTORY_DEFAULT = (
    "/Applications/Ableton Live 11 Suite.app/Contents/App-Resources/"
    "Core Library/Defaults/Instruments/Simpler.adv"
)

# Minimal stand-in carrying the empty SampleParts slot + UserName, so tests run
# without Live installed.
SYNTH_DEFAULT = (
    '<Ableton><UltraSimpler><UserName Value="Simpler" />'
    '<Player><MultiSampleMap><SampleParts />'
    '<LoadInRam Value="false" /></MultiSampleMap></Player>'
    '</UltraSimpler></Ableton>'
)


def _default_xml():
    if os.path.exists(FACTORY_DEFAULT):
        with gzip.open(FACTORY_DEFAULT, "rt") as f:
            return f.read()
    return SYNTH_DEFAULT


# build_multisample_part ------------------------------------------------

def test_part_has_sample_ref_and_ranges():
    part = build_multisample_part(
        "/tmp/kick.wav", file_size=1000, frames=44100, sample_rate=44100,
        display_name="kick", root_key=60)
    assert '<Path Value="/tmp/kick.wav" />' in part
    assert '<OriginalFileSize Value="1000" />' in part
    assert '<OriginalCrc Value="0" />' in part
    assert '<SampleEnd Value="44100" />' in part
    assert '<DefaultSampleRate Value="44100" />' in part
    assert '<RootKey Value="60" />' in part


def test_part_escapes_xml_in_path_and_name():
    part = build_multisample_part(
        '/tmp/a&b<c>.wav', file_size=10, frames=10, sample_rate=44100,
        display_name='A & B "x"', root_key=60)
    assert "&amp;" in part and "&lt;" in part and "&gt;" in part
    assert "&quot;" in part
    # raw specials must not survive in the Path attr
    assert '/tmp/a&b<c>.wav' not in part


def test_part_zero_frames_yields_zero_end():
    part = build_multisample_part(
        "/tmp/x.wav", file_size=10, frames=0, sample_rate=0,
        display_name="x", root_key=60)
    assert '<SampleEnd Value="0" />' in part
    assert '<DefaultSampleRate Value="44100" />' in part  # falls back to 44100


# build_simpler_adv -----------------------------------------------------

def test_build_injects_into_empty_sampleparts():
    out = build_simpler_adv(
        _default_xml(), sample_path="/tmp/snare.wav", file_size=2048,
        frames=22050, sample_rate=44100, name="My Snare", root_key=48)
    assert "<SampleParts />" not in out
    assert "<MultiSamplePart" in out
    assert '<Path Value="/tmp/snare.wav" />' in out
    assert '<RootKey Value="48" />' in out
    # UserName renamed to the preset name
    assert re.search(r'<UserName Value="My Snare" />', out)


def test_build_rejects_missing_sampleparts_slot():
    with pytest.raises(ValueError):
        build_simpler_adv("<Ableton></Ableton>", sample_path="/tmp/x.wav",
                          file_size=10, frames=10, sample_rate=44100, name="x")


def test_build_rejects_bad_size():
    with pytest.raises(ValueError):
        build_simpler_adv(_default_xml(), sample_path="/tmp/x.wav",
                          file_size=0, frames=10, sample_rate=44100, name="x")


def test_build_rejects_bad_name():
    with pytest.raises(ValueError):
        build_simpler_adv(_default_xml(), sample_path="/tmp/x.wav",
                          file_size=10, frames=10, sample_rate=44100, name="a/b")


def test_build_rejects_empty_path():
    with pytest.raises(ValueError):
        build_simpler_adv(_default_xml(), sample_path="  ", file_size=10,
                          frames=10, sample_rate=44100, name="x")


def test_build_does_not_mutate_default():
    src = _default_xml()
    before = src
    build_simpler_adv(src, sample_path="/tmp/x.wav", file_size=10, frames=10,
                      sample_rate=44100, name="x")
    assert src == before
