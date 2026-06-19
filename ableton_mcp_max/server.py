# ableton_mcp_server.py
from mcp.server.fastmcp import FastMCP, Context
import socket
import json
import logging
import os
import re
import gzip
import glob
import math
import time
import subprocess
from dataclasses import dataclass
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any, List, Optional, Union

from ableton_mcp_max.param_utils import resolve_parameter_index
from ableton_mcp_max.track_utils import coerce_create_index, coerce_track_index
from ableton_mcp_max.mixer_utils import normalize_property, validate_property
from ableton_mcp_max.routing_utils import (
    normalize_routing_property,
    validate_routing_property,
)
from ableton_mcp_max.clip_utils import (
    normalize_clip_property,
    validate_clip_property,
    coerce_clip_value,
    resolve_quantize_grid,
    normalize_note,
    NOTE_MOD_FIELDS,
)
from ableton_mcp_max.device_utils import (
    resolve_macro,
    normalize_chain_property,
    validate_chain_property,
    coerce_chain_value,
    coerce_on_value,
)
from ableton_mcp_max.scene_utils import (
    normalize_scene_property,
    coerce_scene_value,
)
from ableton_mcp_max.transport_utils import (
    resolve_cue_direction,
    coerce_song_time,
    coerce_jump_beats,
    coerce_loop_fields,
    coerce_punch_fields,
    coerce_unit_float,
    resolve_clip_trigger_quantization,
    resolve_midi_recording_quantization,
    normalize_nudge_direction,
    resolve_capture_destination,
    resolve_capture_mode,
    coerce_record_length,
)
from ableton_mcp_max.view_utils import (
    normalize_track_type,
    coerce_index as coerce_view_index,
)
from ableton_mcp_max.automation_utils import (
    normalize_clip_location,
    normalize_target_type,
    normalize_mixer_target,
    coerce_resolution,
    normalize_breakpoints,
)
from ableton_mcp_max.listener_utils import (
    build_descriptor,
    coerce_max_events,
    needs_device_resolution,
)
from ableton_mcp_max.preset_utils import (
    match_recursive_preset,
    split_preset_path,
)
from ableton_mcp_max.preset_patch import validate_preset_name
from ableton_mcp_max.wavetable_preset_utils import (
    build_wavetable_adv,
    summarize_wavetable_adv,
)
from ableton_mcp_max.simpler_preset_utils import build_simpler_adv
from ableton_mcp_max.rack_preset_utils import (
    summarize_rack_adg, detect_rack_type, RACK_TYPES,
    patch_macros, patch_chain_zone, patch_macro_mappings,
)
from ableton_mcp_max.arrangement_utils import (
    coerce_time,
    coerce_index,
)
from ableton_mcp_max.arrangement_structure_utils import (
    bars_to_beats,
    compute_section_starts,
    sections_from_cues,
    infer_sections,
    section_facts,
    normalize_energy,
    validate_section_map,
    tiling_plan,
)
from ableton_mcp_max.batch_utils import validate_batch, coerce_stop_on_error
from ableton_mcp_max.analysis_utils import normalize_snapshot, evaluate_rules, live_volume_to_db
from ableton_mcp_max.remediation_utils import (
    db_to_live_volume,
    generate_actions,
    build_correction_plan,
    compute_balance_deltas,
)
from ableton_mcp_max.ruleset_utils import load_rulesets
from ableton_mcp_max.loudness_utils import compute_metrics
from ableton_mcp_max.spectrum_utils import integrate_bands, stereo_metrics
from ableton_mcp_max.masking_utils import (
    masking_score,
    loudness_balance,
    headroom_flags,
    stereo_flags,
    build_mix_findings,
    enrich_names,
)
from ableton_mcp_max.tap_connection import AudioTapConnection
from ableton_mcp_max.tap_registry import TapRegistry
from ableton_mcp_max import composition_utils as comp

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AbletonMCPServer")


def _ok(data):
    """Wrap a successful tool result in the uniform {ok, data} envelope."""
    return json.dumps({"ok": True, "data": data}, indent=2)


def _err(message):
    """Wrap a tool failure in the uniform {ok, error} envelope."""
    return json.dumps({"ok": False, "error": str(message)}, indent=2)


def _song_scale():
    """Best-effort read of the set's key/scale via the Remote Script. Returns a
    dict {scale_name, root_note, scale_intervals} or None on any failure."""
    try:
        ableton = get_ableton_connection()
        return ableton.send_command("get_song_scale", {})
    except Exception as e:
        logger.warning("get_song_scale failed: %s", e)
        return None


def _resolve_scale(key, scale):
    """Resolve (root, intervals): explicit key/scale params win; if both are
    None, read the set's key/scale. Falls back to C natural minor on failure."""
    song_scale = None
    if key is None and scale is None:
        song_scale = _song_scale()
    return comp.resolve_key_scale(key=key, scale=scale, song_scale=song_scale)


def _emit_to_slot(track_index, clip_index, notes, bars, replace):
    """Create the MIDI clip if the slot is empty, else require replace=True;
    then write `notes`. Returns the number of notes written. Raises ValueError
    on an occupied slot when replace is False."""
    ableton = get_ableton_connection()
    try:
        ableton.send_command(
            "get_clip_info",
            {"track_index": track_index, "clip_index": clip_index})
        has_clip = True
    except Exception:
        # Treat any failure as "slot is empty"; a real connection/index error
        # then surfaces from the subsequent create_clip call.
        has_clip = False
    norm = [normalize_note(n) for n in notes]
    if has_clip:
        if not replace:
            raise ValueError("slot occupied; pass replace=true to overwrite")
        ableton.send_command("replace_clip_notes", {
            "track_index": track_index, "clip_index": clip_index,
            "notes": norm})
    else:
        ableton.send_command("create_clip", {
            "track_index": track_index, "clip_index": clip_index,
            "length": float(bars) * 4.0})
        ableton.send_command("add_notes_to_clip", {
            "track_index": track_index, "clip_index": clip_index,
            "notes": norm})
    return len(norm)


def _transform_clip(track_index, clip_index, fn):
    """Read the clip's notes, apply fn(notes)->notes, write them back. Raises if
    the clip is empty or absent (get_clip_notes raises on a non-MIDI/missing
    clip; an existing-but-empty MIDI clip yields no notes)."""
    ableton = get_ableton_connection()
    result = ableton.send_command("get_clip_notes", {
        "track_index": track_index, "clip_index": clip_index,
        "from_time": 0.0, "time_span": -1.0, "from_pitch": 0, "pitch_span": 128})
    notes = result.get("notes") if isinstance(result, dict) else result
    if not notes:
        raise ValueError("no notes in clip (empty or absent)")
    new_notes = fn([dict(n) for n in notes])
    ableton.send_command("replace_clip_notes", {
        "track_index": track_index, "clip_index": clip_index,
        "notes": [normalize_note(n) for n in new_notes]})
    return len(new_notes)


def _resolve_index(primary, alias, *, default=None, label="index"):
    """Resolve a descriptive index parameter that also accepts the legacy
    `index` alias. Pass the canonical name OR `index` (not both); with a
    `default`, either may be omitted."""
    if primary is not None and alias is not None and primary != alias:
        raise ValueError("Pass only one of `%s` or `index`, not both" % label)
    value = primary if primary is not None else alias
    if value is None:
        if default is not None:
            return default
        raise ValueError("`%s` is required" % label)
    return value

# Single source of truth for the command types that MUTATE Live's state. These
# are the wire command types the Remote Script schedules on Live's main thread
# (remote_script/AbletonMCP/__init__.py mutation dispatch list). The server uses
# this set to decide (a) whether to apply a settle delay after the write and
# (b) the read timeout. Keep IN SYNC with the Remote Script list. Note: the
# server's load_instrument_or_effect/load_drum_kit tools send "load_browser_item"
# over the wire, so only "load_browser_item" appears here.
MUTATING_COMMANDS = frozenset({
    "create_midi_track", "set_track_name", "create_clip", "add_notes_to_clip",
    "set_clip_name", "set_tempo", "fire_clip", "stop_clip", "start_playback",
    "stop_playback", "load_browser_item", "set_device_parameter",
    "set_mixer_property", "set_routing", "replace_clip_notes",
    "remove_clip_notes", "set_clip_property", "set_clip_loop", "quantize_clip",
    "duplicate_clip", "delete_clip", "modify_clip_notes", "delete_device",
    "set_device_on", "set_rack_macro", "set_chain_property", "fire_scene",
    "create_scene", "delete_scene", "duplicate_scene", "set_scene_name",
    "set_scene_property", "continue_playback", "set_metronome",
    "set_arrangement_record", "set_session_record", "set_punch",
    "set_song_position", "jump_by", "set_arrangement_loop", "jump_to_cue",
    "back_to_arrangement", "re_enable_automation", "set_automation",
    "clear_automation", "create_automation_envelope", "clear_all_automation",
    "register_listener", "unregister_listener", "create_cue_at_playhead",
    "delete_cue_at_playhead", "duplicate_clip_to_arrangement",
    "delete_arrangement_clip", "create_audio_track", "create_return_track",
    "delete_track", "delete_return_track", "duplicate_track", "undo", "redo",
    "set_groove_amount", "set_swing_amount", "set_clip_trigger_quantization",
    "set_midi_recording_quantization", "set_nudge", "set_selected_track",
    "set_selected_scene", "set_detail_clip", "set_highlighted_clip_slot",
    "set_track_fold", "capture_midi", "capture_and_insert_scene",
    "trigger_session_record", "stop_all_clips", "tap_tempo",
})

# Subset of MUTATING_COMMANDS whose Live write settles ASYNCHRONOUSLY, so a
# follow-up read can see the pre-write value without a brief pause (see the
# write-lag findings in PROGRESS.md: song/transport-level props and structural
# track/scene changes). Only these keep a post-write settle delay; every other
# mutation is applied synchronously within the scheduled task and is already
# settled by the time the response returns, so it pays no delay. (Even for these,
# a separate follow-up read remains the reliable confirmation.)
_SLOW_SETTLE_COMMANDS = frozenset({
    "set_song_position", "jump_by", "set_arrangement_record",
    "set_session_record", "trigger_session_record", "set_punch",
    "set_arrangement_loop", "back_to_arrangement", "jump_to_cue",
    "undo", "redo", "create_midi_track", "create_audio_track",
    "create_return_track", "delete_track", "delete_return_track",
    "duplicate_track", "create_scene", "delete_scene", "duplicate_scene",
    "capture_and_insert_scene",
})

# Client read timeouts. The mutation timeout MUST stay strictly greater than the
# Remote Script's main_thread_task timeout (10s, see __init__.py) so a slow Live
# op surfaces the Remote Script's clean "Timeout waiting for operation to
# complete" rather than a bare client-side socket timeout.
_REMOTE_TASK_TIMEOUT = 10.0
_READ_TIMEOUT = _REMOTE_TASK_TIMEOUT      # read-only commands
_MUTATE_TIMEOUT = _REMOTE_TASK_TIMEOUT + 5.0  # mutating commands (> remote task)
_SETTLE_DELAY = 0.1  # seconds; applied around mutating writes (see Phase C)


class _SendPhaseError(Exception):
    """Socket failure while SENDING a command (it never reached Live, so a
    retry cannot double-apply a mutation)."""


class _RecvPhaseError(Exception):
    """Socket failure while RECEIVING a response (the command MAY have executed
    in Live, so only idempotent commands are safe to retry)."""


@dataclass
class AbletonConnection:
    host: str
    port: int
    sock: socket.socket = None
    
    def connect(self) -> bool:
        """Connect to the Ableton Remote Script socket server"""
        if self.sock:
            return True
            
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            logger.info(f"Connected to Ableton at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Ableton: {str(e)}")
            self.sock = None
            return False
    
    def disconnect(self):
        """Disconnect from the Ableton Remote Script"""
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logger.error(f"Error disconnecting from Ableton: {str(e)}")
            finally:
                self.sock = None

    def receive_full_response(self, sock, buffer_size=8192):
        """Receive the complete response, potentially in multiple chunks"""
        chunks = []
        sock.settimeout(15.0)  # Increased timeout for operations that might take longer
        
        try:
            while True:
                try:
                    chunk = sock.recv(buffer_size)
                    if not chunk:
                        if not chunks:
                            raise Exception("Connection closed before receiving any data")
                        break
                    
                    chunks.append(chunk)
                    
                    # Check if we've received a complete JSON object
                    try:
                        data = b''.join(chunks)
                        json.loads(data.decode('utf-8'))
                        logger.info(f"Received complete response ({len(data)} bytes)")
                        return data
                    except json.JSONDecodeError:
                        # Incomplete JSON, continue receiving
                        continue
                except socket.timeout:
                    logger.warning("Socket timeout during chunked receive")
                    break
                except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
                    logger.error(f"Socket connection error during receive: {str(e)}")
                    raise
        except Exception as e:
            logger.error(f"Error during receive: {str(e)}")
            raise
            
        # If we get here, we either timed out or broke out of the loop
        if chunks:
            data = b''.join(chunks)
            logger.info(f"Returning data after receive completion ({len(data)} bytes)")
            try:
                json.loads(data.decode('utf-8'))
                return data
            except json.JSONDecodeError:
                raise Exception("Incomplete JSON response received")
        else:
            raise Exception("No data received")

    def _reset_socket(self):
        """Drop the current socket so the next attempt reconnects cleanly."""
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = None

    def _attempt(self, command, is_modifying, timeout=None, slow_settle=False):
        """One send→receive round-trip on the current socket.

        Raises _SendPhaseError if the failure happened before the command
        reached Live (safe to retry, even mutations), or _RecvPhaseError if it
        happened while awaiting the response (the command MAY have executed, so
        only idempotent commands are safe to retry). Application-level errors
        (status == "error") propagate as a plain Exception (connection is fine).

        No pre-send delay: the receive blocks until Live responds anyway. A
        post-receive settle is applied only when slow_settle is set (the
        async-settling ops in _SLOW_SETTLE_COMMANDS), so the common mutation
        pays no artificial latency.
        """
        # SEND phase: a failure here means Live never saw the command.
        try:
            self.sock.sendall(json.dumps(command).encode('utf-8'))
        except Exception as e:
            raise _SendPhaseError(e)

        if timeout is None:
            timeout = _MUTATE_TIMEOUT if is_modifying else _READ_TIMEOUT
        self.sock.settimeout(timeout)

        # RECEIVE phase: a failure here means the command may have run.
        try:
            response_data = self.receive_full_response(self.sock)
            response = json.loads(response_data.decode('utf-8'))
        except Exception as e:
            raise _RecvPhaseError(e)

        if response.get("status") == "error":
            logger.error(f"Ableton error: {response.get('message')}")
            raise Exception(response.get("message", "Unknown error from Ableton"))

        if slow_settle:
            time.sleep(_SETTLE_DELAY)
        return response.get("result", {})

    def send_command(self, command_type: str, params: Dict[str, Any] = None,
                     idempotent: bool = None) -> Dict[str, Any]:
        """Send a command to Ableton and return the result.

        Transparently recovers from a stale/dropped socket: a send-phase failure
        is always retried once (the command never reached Live), and a
        receive-phase failure is retried once only when the command is
        idempotent. `idempotent` defaults to True for read-only commands and
        False for mutations (MUTATING_COMMANDS); pass it explicitly to override.
        """
        if not self.sock and not self.connect():
            raise ConnectionError("Not connected to Ableton")

        command = {"type": command_type, "params": params or {}}
        is_modifying = command_type in MUTATING_COMMANDS
        slow = command_type in _SLOW_SETTLE_COMMANDS
        if idempotent is None:
            idempotent = not is_modifying

        logger.info(f"Sending command: {command_type} with params: {params}")
        try:
            return self._attempt(command, is_modifying, slow_settle=slow)
        except _SendPhaseError as e:
            # Command never reached Live → safe to reconnect and retry once.
            logger.warning(f"Send-phase failure for {command_type} ({e}); "
                           f"reconnecting and retrying once")
            self._reset_socket()
            if not self.connect():
                raise Exception("Connection to Ableton lost; reconnect failed")
            try:
                return self._attempt(command, is_modifying, slow_settle=slow)
            except (_SendPhaseError, _RecvPhaseError) as e2:
                self._reset_socket()
                raise Exception(f"Communication error with Ableton: {e2}")
        except _RecvPhaseError as e:
            self._reset_socket()
            if idempotent:
                logger.warning(f"Recv-phase failure for {command_type} ({e}); "
                               f"idempotent retry")
                if self.connect():
                    try:
                        return self._attempt(command, is_modifying,
                                             slow_settle=slow)
                    except (_SendPhaseError, _RecvPhaseError) as e2:
                        self._reset_socket()
                        raise Exception(
                            f"Communication error with Ableton: {e2}")
            # Non-idempotent: socket is reset for the next call, but we do NOT
            # retry: the mutation may already have applied in Live.
            raise Exception(f"Communication error with Ableton: {e}")

    def send_batch(self, commands, stop_on_error=True):
        """Run several mutating commands in ONE Remote Script task / one socket
        round-trip. `commands` is a list of {"type", "params"} members (already
        validated). Returns the batch result dict
        {count, completed, failed_index, results}.

        The batch is treated as a single mutation: only send-phase failures are
        retried (the whole batch never reached Live), never recv-phase (members
        may have applied). The read timeout scales with the member count and is
        kept above the Remote Script's batch task timeout (10 + 2*N s).
        """
        if not self.sock and not self.connect():
            raise ConnectionError("Not connected to Ableton")
        command = {"type": "batch",
                   "params": {"commands": commands,
                              "stop_on_error": stop_on_error}}
        timeout = _REMOTE_TASK_TIMEOUT + 2.0 * max(1, len(commands)) + 5.0
        logger.info(f"Sending batch of {len(commands)} commands "
                    f"(stop_on_error={stop_on_error})")
        try:
            return self._attempt(command, True, timeout=timeout, slow_settle=True)
        except _SendPhaseError as e:
            logger.warning(f"Batch send-phase failure ({e}); "
                           f"reconnecting and retrying once")
            self._reset_socket()
            if not self.connect():
                raise Exception("Connection to Ableton lost; reconnect failed")
            try:
                return self._attempt(command, True, timeout=timeout, slow_settle=True)
            except (_SendPhaseError, _RecvPhaseError) as e2:
                self._reset_socket()
                raise Exception(f"Communication error with Ableton: {e2}")
        except _RecvPhaseError as e:
            self._reset_socket()
            raise Exception(f"Communication error with Ableton: {e}")

@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """Manage server startup and shutdown lifecycle"""
    try:
        logger.info("AbletonMCP server starting up")
        
        try:
            ableton = get_ableton_connection()
            logger.info("Successfully connected to Ableton on startup")
        except Exception as e:
            logger.warning(f"Could not connect to Ableton on startup: {str(e)}")
            logger.warning("Make sure the Ableton Remote Script is running")
        
        yield {}
    finally:
        global _ableton_connection
        if _ableton_connection:
            logger.info("Disconnecting from Ableton on shutdown")
            _ableton_connection.disconnect()
            _ableton_connection = None
        logger.info("AbletonMCP server shut down")

# Create the MCP server with lifespan support
mcp = FastMCP(
    "AbletonMCPMax",
    lifespan=server_lifespan
)

# Global connection for resources
_ableton_connection = None

def get_ableton_connection():
    """Get or create a persistent Ableton connection"""
    global _ableton_connection

    # Reuse the existing connection object. We do NOT pre-probe liveness here
    # (a zero-byte send can't detect a half-open socket). Instead, send_command
    # transparently reconnects on a send-phase failure, so a stale socket is
    # recovered on first use without a useless extra round-trip.
    if _ableton_connection is not None:
        return _ableton_connection

    # Connection doesn't exist, create a new one
    if _ableton_connection is None:
        # Try to connect up to 3 times with a short delay between attempts
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(f"Connecting to Ableton (attempt {attempt}/{max_attempts})...")
                _ableton_connection = AbletonConnection(host="localhost", port=9877)
                if _ableton_connection.connect():
                    logger.info("Created new persistent connection to Ableton")
                    
                    # Validate connection with a simple command
                    try:
                        # Get session info as a test
                        _ableton_connection.send_command("get_session_info")
                        logger.info("Connection validated successfully")
                        return _ableton_connection
                    except Exception as e:
                        logger.error(f"Connection validation failed: {str(e)}")
                        _ableton_connection.disconnect()
                        _ableton_connection = None
                        # Continue to next attempt
                else:
                    _ableton_connection = None
            except Exception as e:
                logger.error(f"Connection attempt {attempt} failed: {str(e)}")
                if _ableton_connection:
                    _ableton_connection.disconnect()
                    _ableton_connection = None
            
            # Wait before trying again, but only if we have more attempts left
            if attempt < max_attempts:
                import time
                time.sleep(1.0)
        
        # If we get here, all connection attempts failed
        if _ableton_connection is None:
            logger.error("Failed to connect to Ableton after multiple attempts")
            raise Exception("Could not connect to Ableton. Make sure the Remote Script is running.")
    
    return _ableton_connection


_audio_tap_connection = None


def get_audio_tap_connection():
    """Return the lazily-created AudioTapConnection (M4L relay on 9878)."""
    global _audio_tap_connection
    if _audio_tap_connection is None:
        _audio_tap_connection = AudioTapConnection()
    return _audio_tap_connection


# Per-track tap registry: a background TCP server on 9878 that M4L tap devices
# connect into and stream JSON stat blocks. Started once at import; if the port
# is busy (stale server / double-load) the tools degrade to "disconnected".
_tap_registry = TapRegistry(port=9878)
try:
    _tap_registry.start()
except OSError as e:
    logger.warning("tap registry could not bind 9878: %s", e)


def _uuid_for_index(track_index):
    """Return the uuid of the connected tap matching track_index, or None.

    Master is track_index == -1 -> identity kind=="master" (or index==-1);
    other indices match the identity's index. Identities come from the
    registry's connected taps. (A track's live index can drift on reorder; a
    later task may re-resolve via the LOM - for now match the reported index.)
    """
    for t in _tap_registry.state.tracks():
        if track_index == -1:
            if t.get("kind") == "master" or t.get("index") == -1:
                return t.get("uuid")
        elif t.get("index") == track_index:
            return t.get("uuid")
    return None


def _track_name_map():
    """Best-effort {track_index: name} (+ -1 -> 'Master') from the live set.

    The tap device reports a blank name, so cross-track findings backfill
    readable names from the LOM track index. Read-only; tolerates failure
    (returns just the master entry if the snapshot read fails).
    """
    out = {-1: "Master"}
    try:
        raw = get_ableton_connection().send_command("get_analysis_snapshot")
        for t in raw.get("tracks", []):
            idx = t.get("index")
            if idx is not None:
                out[idx] = t.get("name")
    except Exception as e:
        logger.info("track name map unavailable: %s", e)
    return out


def _measure_pass(window_s, region=None, name_by_index=None):
    """Reset every tap, play the set for window_s, integrate each tap's buffered
    blocks into a per-track signal. Returns (tracks_out, sigs).

    Shared by measure_mix and analyze_set(measure=True). Resets the Python-side
    ring buffers FIRST so integration sees ONLY this window (not accumulated
    history), then plays via the _run_measure_playback seam (stubbable in tests).
    name_by_index backfills the device's blank name from the LOM track index.

    Note: we do NOT send the device a reset command. The tap is a dumb relay
    that streams continuously and holds no integration state (all math is
    server-side), and the patch's inbound-reset path halts block emission - so a
    device reset both gains nothing and silently kills the stream. Clearing the
    server-side ring buffer is sufficient; the background registry thread refills
    it with this window's blocks while _run_measure_playback runs.
    """
    name_by_index = name_by_index or {}
    _tap_registry.state.reset()
    try:
        _run_measure_playback(window_s, region)
    except Exception as e:
        logger.info("measure pass playback seam failed: %s", e)
    tracks_out, sigs = [], []
    for t in _tap_registry.state.tracks():
        uuid = t.get("uuid")
        if uuid is None:
            continue
        sample_rate = t.get("sample_rate", 48000)
        buf = _tap_registry.state.buffer(uuid)
        signal = _integrate_buffer(buf, sample_rate)
        index = t.get("index")
        signal["name"] = t.get("name") or ""
        signal["index"] = index
        sigs.append(signal)
        tracks_out.append({"name": signal["name"], "index": index,
                           "kind": t.get("kind"), "signal": signal})
    enrich_names(sigs, name_by_index)
    for tr in tracks_out:           # mirror enriched name onto the top-level entry
        tr["name"] = tr["signal"]["name"]
    return tracks_out, sigs


# Core Tool endpoints

@mcp.tool()
def get_session_info(ctx: Context) -> str:
    """Get detailed information about the current Ableton session"""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_session_info")
        return _ok(result)
    except Exception as e:
        logger.error(f"Error getting session info from Ableton: {str(e)}")
        return _err(f"Error getting session info: {str(e)}")


@mcp.tool()
def analyze_set(ctx: Context, focus: str = "all", measure: bool = False,
                measure_window_s: float = 15.0) -> str:
    """Analyze the open Live set against curated best-practice rulesets.

    focus: one of "all" (default), "mixing", "mastering", "sound_design",
    "health" - selects which rule domains run.

    measure: when True AND per-track MCP Tap devices are connected, run a brief
    measure pass (plays the set for measure_window_s seconds, then stops/restores)
    to capture audio and add a signal-backed "mix_signal" section (see below).
    Default False keeps analyze_set read-only - the signal-backed mixing rules
    stay deferred. measure_window_s: capture length when measure=True (default 15).

    Reads the whole set in one round-trip, runs the deterministic ("auto") rules,
    and returns JSON {ok, data} where data = {snapshot, findings, manual_rules,
    deferred_rules, summary, [mix_signal]}:
    - snapshot: normalized per-track/return/master state (mixer, devices, clips,
      routing); master.signal carries audio-tap metering (LUFS/dBTP) when the
      MCP Audio Tap device is loaded, else null.
    - findings: auto-rule results {id, domain, status (pass|fail|warn|info),
      severity, evidence, remediation, [entity]}.
    - manual_rules: rules needing human/Claude judgment (id, domain, title, rationale).
    - deferred_rules: signal-required rules still needing metering (no audio tap
      connected / measure not run); the four mixing.* signal rules promote out of
      here into mix_signal when a measure pass runs.
    - summary: counts by status + manual/deferred.
    - mix_signal (only when measure=True with taps): {window_s, tracks:[{name,
      index,kind,signal}], findings:[{id,domain,status,severity,items,evidence,
      remediation}]} - cross-track spectral masking / loudness balance / per-track
      headroom / stereo correlation computed from the simultaneous per-track taps.

    With measure=False this is read-only; it never mutates the set. The
    /ableton:analyze skill layers the report and per-track judgment on top.
    """
    try:
        rules = load_rulesets(focus)
    except ValueError as e:
        return _err(str(e))
    try:
        ableton = get_ableton_connection()
        raw = ableton.send_command("get_analysis_snapshot")
        snapshot = normalize_snapshot(raw)
        try:
            tap = get_audio_tap_connection()
            if tap.is_connected():
                snapshot["master"]["signal"] = compute_metrics(tap.send("read"))
        except Exception as e:
            logger.info("audio tap unavailable for analysis: %s", e)
        result = evaluate_rules(rules, snapshot)
        result["snapshot"] = snapshot
        if measure and _tap_registry.state.tracks():
            try:
                name_by_index = {t["index"]: t["name"] for t in snapshot["tracks"]
                                 if t.get("index") is not None}
                name_by_index[-1] = "Master"
                tracks_out, sigs = _measure_pass(
                    measure_window_s, name_by_index=name_by_index)
                mix_findings = build_mix_findings(sigs, rules)
                result["mix_signal"] = {"window_s": measure_window_s,
                                        "tracks": tracks_out,
                                        "findings": mix_findings}
                built = {f["id"] for f in mix_findings}
                result["deferred_rules"] = [d for d in result["deferred_rules"]
                                            if d["id"] not in built]
                # keep the summary tally in step with the promoted-out rules
                result["summary"]["deferred"] = len(result["deferred_rules"])
            except Exception as e:
                logger.info("measure pass for analyze_set failed: %s", e)
        return _ok(result)
    except Exception as e:
        logger.error(f"Error analyzing set: {str(e)}")
        return _err(f"Error analyzing set: {str(e)}")


@mcp.tool()
def get_audio_tap_status(ctx: Context) -> str:
    """Report per-track tap registry connectivity.

    Returns JSON {ok, data:{connected, tracks}}. connected is True when at least
    one 'MCP Audio Tap' device is streaming into the registry on 9878; tracks is
    the list of connected tap identities (uuid/name/index/kind + sample_rate +
    block_count). Empty/False until a tap device is loaded onto a track.
    """
    tracks = _tap_registry.state.tracks()
    return _ok({"connected": len(tracks) > 0, "tracks": tracks})


@mcp.tool()
def list_taps(ctx: Context) -> str:
    """List the connected per-track taps.

    Returns JSON {ok, data:{count, tracks}} where tracks is the list of tap
    identities (uuid/name/index/kind + sample_rate + block_count) currently
    streaming into the registry.
    """
    tracks = _tap_registry.state.tracks()
    return _ok({"count": len(tracks), "tracks": tracks})


@mcp.tool()
def reset_meter(ctx: Context, track_index: int = None) -> str:
    """Reset tap accumulators (clears buffered blocks).

    track_index: omit to reset every connected tap; pass -1 for the master tap
    or a track index to reset just that one. Returns JSON {ok, data:{reset:true}}.
    Call before playing material you want measured.
    """
    uuid = _uuid_for_index(track_index) if track_index is not None else None
    _tap_registry.state.reset(uuid)
    return _ok({"reset": True})


def _integrate_buffer(buf, sample_rate):
    """Turn a tap's buffered 100 ms blocks into a per-track signal summary.

    Each block is {ms_k_l, ms_k_r, peak, rms, ...}. The K-weighted mean-squares
    feed loudness_utils EXACTLY as compute_metrics does (we build the same
    read_payload shape and reuse it), with the per-block linear `peak` mapped to
    `tp` so true_peak_dbtp is computed from it. peak/rms here are the linear
    domain values: peak = max block peak, rms = the most recent block's rms
    (representative of the current signal); crest = peak/rms in dB.
    """
    payload = {
        "sample_rate": sample_rate,
        "block_count": len(buf),
        "blocks": [{"ms_k_l": b.get("ms_k_l"), "ms_k_r": b.get("ms_k_r"),
                    "tp": b.get("peak")} for b in buf],
        "peak": max((b.get("peak") or 0.0 for b in buf), default=0.0) if buf else None,
        "rms": buf[-1].get("rms") if buf else None,
    }
    metrics = compute_metrics(payload)
    peak = payload["peak"]
    rms = payload["rms"]
    crest = None
    if peak and rms and rms > 0:
        crest = round(20.0 * math.log10(peak / rms), 1)
    stereo = stereo_metrics(buf)
    return {
        "integrated_lufs": metrics["integrated_lufs"],
        "momentary_lufs": metrics["momentary_lufs"],
        "short_term_lufs": metrics["short_term_lufs"],
        "true_peak_dbtp": metrics["true_peak_dbtp"],
        "peak": peak,
        "rms": rms,
        "crest": crest,
        "bands": integrate_bands(buf),
        "width": stereo["width"],
        "correlation": stereo["correlation"],
        "block_count": len(buf),
        "sample_rate": sample_rate,
    }


@mcp.tool()
def read_track_meter(ctx: Context, track_index: int = -1) -> str:
    """Integrate a track's buffered tap blocks into a signal summary.

    track_index: -1 for the master tap (default), or a track index whose 'MCP
    Audio Tap' device is streaming. Returns JSON {ok, data:{integrated_lufs,
    momentary_lufs, short_term_lufs, true_peak_dbtp, peak, rms, crest,
    block_count, sample_rate}}. LUFS/dBTP are computed via BS.1770 gating over
    the buffered 100 ms K-weighted blocks (loudness fields are null until enough
    blocks exist - momentary needs 0.4 s, short-term 3 s). peak/rms are linear;
    crest is peak-to-rms in dB. An empty buffer returns ok with block_count 0 and
    null metrics. {ok:false,error} if no tap is connected for that track.
    """
    uuid = _uuid_for_index(track_index)
    if uuid is None:
        return _err("No tap connected for track %s" % track_index)
    sample_rate = 48000
    for t in _tap_registry.state.tracks():
        if t.get("uuid") == uuid:
            sample_rate = t.get("sample_rate", 48000)
            break
    buf = _tap_registry.state.buffer(uuid)
    return _ok(_integrate_buffer(buf, sample_rate))


@mcp.tool()
def read_meter(ctx: Context) -> str:
    """Master tap signal summary (compat shim for read_track_meter(-1)).

    Delegates to read_track_meter for the master tap. Returns JSON {ok, data}
    with the integrated/momentary/short-term LUFS, true-peak dBTP, linear
    peak/rms, crest, block_count and sample_rate. {ok:false,error} if no master
    tap is connected.
    """
    return read_track_meter(ctx, track_index=-1)


def _run_measure_playback(seconds, region=None):
    """Playback seam for measure_loudness: start the transport, wait, stop.

    Isolated so tests can monkeypatch it (no Live needed). Returns True if the
    transport advanced (so a bogus reading isn't mistaken for real), else False.
    region is reserved for a future arrangement-window capture.
    """
    ableton = get_ableton_connection()
    try:
        start_t = ableton.send_command("get_transport").get("current_song_time", 0.0)
    except Exception:
        start_t = 0.0
    ableton.send_command("start_playback")
    time.sleep(seconds if seconds else 10.0)
    ableton.send_command("stop_playback")
    try:
        end_t = ableton.send_command("get_transport").get("current_song_time", start_t)
    except Exception:
        end_t = start_t
    return end_t > start_t


@mcp.tool()
def measure_loudness(ctx: Context, seconds: float = None) -> str:
    """Reset the master meter, play the set, wait, and read back loudness.

    seconds: how long to capture (default 10.0). For an integrated-loudness pass
    over a whole song, pass its length. Returns the same signal-summary payload
    as read_meter plus data.played (False if the transport did not advance - e.g.
    nothing to play - so a bogus reading is not mistaken for real).
    {ok:false,error} if no master tap is connected.
    """
    uuid = _uuid_for_index(-1)
    if uuid is None:
        return _err("No master tap connected")
    sample_rate = 48000
    for t in _tap_registry.state.tracks():
        if t.get("uuid") == uuid:
            sample_rate = t.get("sample_rate", 48000)
            break
    _tap_registry.state.reset(uuid)
    played = _run_measure_playback(seconds)
    buf = _tap_registry.state.buffer(uuid)
    metrics = _integrate_buffer(buf, sample_rate)
    metrics["played"] = played
    return _ok(metrics)


@mcp.tool()
def measure_mix(ctx: Context, window_s: float = 15.0, region: str = None) -> str:
    """Timed multi-track measure pass -> per-track signals + cross-track findings.

    Resets every connected tap, plays the set for window_s seconds (via the same
    transport seam as measure_loudness), then integrates each tap's buffered
    blocks into a per-track signal (LUFS/dBTP/peak/rms/crest plus the 8-band
    spectrum and stereo width/correlation). region is reserved for a future
    arrangement-window capture.

    Returns JSON {ok, data:{window_s, tracks, findings}}:
    - tracks: [{name, index, kind, signal:{...}}] one per connected tap.
    - findings: cross-track analysis from masking_utils -
      masking (pairwise spectral overlap), balance (tracks sitting too far below
      the loudest), headroom (near-clip / over-compressed), stereo (mono-compat
      risk). Each is a (possibly empty) list.

    With no taps connected this still returns ok with empty tracks + empty
    findings (not an error). Track names blank-reported by the device are
    backfilled from the LOM track index.
    """
    name_by_index = _track_name_map()
    tracks_out, sigs = _measure_pass(window_s, region, name_by_index)
    findings = {
        "masking": masking_score(sigs),
        "balance": loudness_balance(sigs),
        "headroom": headroom_flags(sigs),
        "stereo": stereo_flags(sigs),
    }
    return _ok({"window_s": window_s, "tracks": tracks_out, "findings": findings})


# Name the tap device carries when loaded in Live (the .amxd is "MCP Tap.amxd").
TAP_DEVICE_NAME = "MCP Tap"
# Browser folder under which the MCP Tap device is indexed once added to the
# User Library. A user .amxd must be dragged into Live's browser (which copies
# it AND registers it in Live's content DB); a manual file-copy alone is not
# indexed. Confirmed by spike 0.1: the device resolves under the User Library
# "Max Audio Effect" presets folder, not the max_for_live category (that lists
# only the stock blank template). deploy_taps degrades to a manual-drag hint if
# the load path can't resolve it.
TAP_BROWSER_PATH = "user_library/Presets/Audio Effects/Max Audio Effect"


def _audio_instrument_track_indices():
    """Regular tracks worth tapping: audio tracks + instrument-bearing MIDI
    tracks. Reads the analysis snapshot and returns their indices."""
    raw = get_ableton_connection().send_command("get_analysis_snapshot")
    out = []
    for t in raw.get("tracks", []):
        idx = t.get("index")
        if idx is None:
            continue
        if t.get("type") == "audio" or t.get("has_instrument"):
            out.append(idx)
    return out


def _load_tap_on_track(track_index):
    """Browser-load the User-Library MCP Tap device onto a track.

    Resolves the device in the browser via get_browser_presets +
    match_recursive_preset, then load_browser_item. Raises on any failure so
    deploy_taps can record it (and fall back to a manual-drag hint).
    """
    ableton = get_ableton_connection()
    presets_result = ableton.send_command("get_browser_presets",
                                           {"path": TAP_BROWSER_PATH})
    if "error" in presets_result:
        raise RuntimeError(presets_result.get("error"))
    chosen = match_recursive_preset(presets_result.get("presets", []), TAP_DEVICE_NAME)
    uri = chosen.get("uri")
    if not uri:
        raise RuntimeError("MCP Tap device has no loadable URI")
    res = ableton.send_command("load_browser_item",
                               {"track_index": track_index, "item_uri": uri})
    if not res.get("loaded", False):
        raise RuntimeError("load_browser_item did not confirm")
    return chosen.get("relative_path") or chosen.get("name") or TAP_DEVICE_NAME


def _find_taps():
    """Return [(track_index, device_index)] for every loaded MCP Tap device."""
    raw = get_ableton_connection().send_command("get_analysis_snapshot")
    out = []
    for t in raw.get("tracks", []):
        ti = t.get("index")
        if ti is None:
            continue
        for d in t.get("devices", []):
            if d.get("name") == TAP_DEVICE_NAME and d.get("index") is not None:
                out.append((ti, d.get("index")))
    return out


def _delete_device_raw(track_index, device_index):
    """Delete one device (regular track) over the wire. Raises on failure."""
    get_ableton_connection().send_command(
        "delete_device",
        {"track_index": track_index, "device_index": device_index,
         "track_type": "regular"})


# A slow Max-for-Live / Node-for-Max boot (notably Live 12 / Max 8.6) can outlast
# the socket read timeout, so load_browser_item's reply is lost even though the
# device DID load and connect. deploy_taps then confirms the load actually
# landed by watching the tap registry rather than trusting the lost reply.
TAP_CONFIRM_ATTEMPTS = 6
TAP_CONFIRM_DELAY = 0.5


def _is_load_timeout(err):
    """True when err is the lost-reply signature (recv timed out), not a clean
    'device not in the browser' failure (which should fail fast, not poll)."""
    text = str(err)
    return "No data received" in text or "Communication error" in text


def _confirm_tap_via_registry(track_index, before_uuids, sleep=time.sleep):
    """Poll the tap registry for a NEWLY-connected tap at track_index after a
    load whose socket reply was lost. before_uuids = the uuids connected just
    before the load, so a pre-existing tap on that index never counts as a false
    confirm. Returns the new uuid, or None if none appears within the window."""
    for attempt in range(TAP_CONFIRM_ATTEMPTS):
        for t in _tap_registry.state.tracks():
            uuid = t.get("uuid")
            if uuid in before_uuids:
                continue
            idx = t.get("index")
            if (track_index == -1 and (t.get("kind") == "master" or idx == -1)) \
                    or idx == track_index:
                return uuid
        if attempt < TAP_CONFIRM_ATTEMPTS - 1:
            sleep(TAP_CONFIRM_DELAY)
    return None


@mcp.tool()
def deploy_taps(ctx: Context, track_indices: List[int] = None) -> str:
    """Load the MCP Tap metering device onto tracks for per-track analysis.

    track_indices: omit to auto-target every regular audio track + every MIDI
    track holding an instrument; or pass explicit track indices. The device must
    be present in the User Library (copy m4l/'MCP Tap.amxd' there once); see
    m4l/README.md.

    Returns JSON {ok, data:{targets, deployed:[{track_index,device}],
    failed:[{track_index,error}]}}. If EVERY load fails (e.g. the device isn't in
    the browser), data.manual is true with a drag-it-yourself message listing the
    target tracks - the registry still works once the device is dragged on by
    hand. After deploying, run measure_mix or analyze_set(measure=True).

    A slow Max-for-Live / Node-for-Max boot (notably Live 12 / Max 8.6) can
    outlast the socket read timeout, so the load reply is lost even though the
    device loaded + connected. When a load times out, deploy_taps polls the tap
    registry and, if a tap connects on that track, records it as deployed with
    "confirmed_via": "registry" instead of failing.
    """
    try:
        targets = (_audio_instrument_track_indices() if track_indices is None
                   else list(track_indices))
        deployed, failed = [], []
        for i in targets:
            before = {t.get("uuid") for t in _tap_registry.state.tracks()}
            try:
                label = _load_tap_on_track(i)
                deployed.append({"track_index": i, "device": label})
            except Exception as e:
                # A slow M4L/Node boot (e.g. Live 12 / Max 8.6) can drop the
                # load reply even though the device loaded + connected; confirm
                # via the registry before declaring failure.
                uuid = (_confirm_tap_via_registry(i, before)
                        if _is_load_timeout(e) else None)
                if uuid:
                    deployed.append({"track_index": i, "device": TAP_DEVICE_NAME,
                                     "confirmed_via": "registry"})
                else:
                    failed.append({"track_index": i, "error": str(e)})
        data = {"targets": targets, "deployed": deployed, "failed": failed}
        if targets and not deployed:
            data["manual"] = True
            data["message"] = (
                "Could not auto-load the tap (is 'MCP Tap.amxd' in your User "
                "Library?). Drag 'MCP Tap' from the browser onto these tracks: %s"
                % targets)
        return _ok(data)
    except Exception as e:
        logger.error("Error deploying taps: %s", e)
        return _err("Error deploying taps: %s" % e)


@mcp.tool()
def remove_taps(ctx: Context) -> str:
    """Remove every loaded MCP Tap device from the set (delete by name match).

    Scans all regular tracks for devices named 'MCP Tap' and deletes them
    (per-track, highest device index first so re-indexing is safe). Returns JSON
    {ok, data:{removed_count, removed:[{track_index,device_index}], errors:[...]}}.
    No-op (removed_count 0) when none are loaded.
    """
    try:
        found = _find_taps()
        # delete highest device_index first within each track so re-indexing
        # never shifts a still-pending target on the same track.
        ordered = sorted(found, key=lambda p: (p[0], -p[1]))
        removed, errors = [], []
        for ti, di in ordered:
            try:
                _delete_device_raw(ti, di)
                removed.append({"track_index": ti, "device_index": di})
            except Exception as e:
                errors.append({"track_index": ti, "device_index": di, "error": str(e)})
        return _ok({"removed_count": len(removed), "removed": removed, "errors": errors})
    except Exception as e:
        logger.error("Error removing taps: %s", e)
        return _err("Error removing taps: %s" % e)


@mcp.tool()
def adjust_track_gain(
    ctx: Context,
    track_index: int,
    delta_db: float,
    track_type: str = "regular",
) -> str:
    """Shift a track's fader by a signed dB amount without playback.

    Reads the current volume knob value, converts using Live's 40x log taper
    (unity = 0.85), applies delta_db, clamps to [-70, +6] dB, and writes the
    new value back via set_mixer_property. No tap or playback required.

    Parameters:
    - track_index: index of the track (ignored for master; pass 0)
    - delta_db: signed dB shift; positive = louder, negative = quieter
    - track_type: "regular" (default), "return", or "master"

    Returns JSON {ok, data:{track_index, delta_db, volume_before, volume_after,
    db_before, db_after}}.
    """
    try:
        ableton = get_ableton_connection()
        mixer = ableton.send_command(
            "get_mixer", {"track_index": track_index, "track_type": track_type}
        )
        current_vol = mixer.get("volume")
        if current_vol is None:
            return _err("Volume not available for track %s (%s)" % (track_index, track_type))
        current_db = live_volume_to_db(current_vol)
        new_db = max(-70.0, min(6.0, current_db + delta_db))
        new_vol = db_to_live_volume(new_db)
        ableton.send_command(
            "set_mixer_property",
            {"track_index": track_index, "track_type": track_type,
             "property": "volume", "value": new_vol, "send_index": -1},
        )
        return _ok({
            "track_index": track_index,
            "track_type": track_type,
            "delta_db": delta_db,
            "volume_before": current_vol,
            "volume_after": new_vol,
            "db_before": current_db,
            "db_after": round(new_db, 1),
        })
    except Exception as e:
        logger.error("Error adjusting track gain: %s", e)
        return _err("Error adjusting track gain: %s" % e)


# --- Graceful Live quit / restart -----------------------------------------
# kill -TERM is a crash from Live's POV (recovery modal on relaunch), so we quit
# through the Apple 'quit' event and answer the unsaved-changes dialog by
# keystroke. The LOM exposes no save-state or save API, so "dirty" is detected by
# Live still being alive shortly after the quit (a clean quit is fast), and
# "save" is the dialog's Return — an Untitled set has no path, so it then pops a
# Save-As dialog we can't fill (reported back, not guessed). The OS calls below
# are seams so the orchestration is unit-testable without touching real apps.
LIVE_PORT = 9877


def _osa(script):
    """Run an AppleScript and wait. Keystroke/System-Events scripts return
    immediately; used for the dialog answers. Seam for tests."""
    subprocess.run(["/usr/bin/osascript", "-e", script],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)


def _osa_async(script):
    """Fire an AppleScript without waiting — for the 'quit' event, which BLOCKS
    until the save dialog (if any) is answered. Seam for tests."""
    subprocess.Popen(["/usr/bin/osascript", "-e", script],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _live_app_and_pid(port=LIVE_PORT):
    """(.app path, pid int) of the Live process listening on `port`, or
    (None, None). This is authoritatively the Live the MCP talks to."""
    try:
        out = subprocess.check_output(
            ["/usr/sbin/lsof", "-nP", "-iTCP:%d" % port, "-sTCP:LISTEN", "-t"],
            stderr=subprocess.DEVNULL).split()
        pid = int(out[0])
        comm = subprocess.check_output(
            ["/bin/ps", "-p", str(pid), "-o", "comm="],
            stderr=subprocess.DEVNULL).decode().strip()
        if ".app/" in comm:
            return comm.split(".app/")[0] + ".app", pid
    except Exception:
        pass
    return None, None


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _open_app(app):
    subprocess.run(["/usr/bin/open", "-a", app], check=False)


def _port_listening(port=LIVE_PORT):
    try:
        out = subprocess.check_output(
            ["/usr/sbin/lsof", "-nP", "-iTCP:%d" % port, "-sTCP:LISTEN", "-t"],
            stderr=subprocess.DEVNULL)
        return bool(out.strip())
    except Exception:
        return False


def _app_name(app_path):
    """'Ableton Live 12 Suite' from a .app path, for AppleScript 'tell app'."""
    base = os.path.basename(app_path)
    return base[:-4] if base.endswith(".app") else base


def _wait_until(predicate, timeout, interval=1.0, sleep=time.sleep):
    """Poll predicate() until truthy or timeout; return the final value."""
    waited = 0.0
    while waited < timeout and not predicate():
        sleep(interval)
        waited += interval
    return predicate()


def _restart_live_impl(save="discard", relaunch=True, wait_timeout=90.0,
                       dirty_after=5.0, sleep=time.sleep):
    """Gracefully quit (and optionally relaunch) the running Live. Returns a
    status dict; raises ValueError on a bad save policy / RuntimeError if no
    Live is found."""
    if save not in ("discard", "save"):
        raise ValueError("save must be 'discard' or 'save' (got %r)." % save)
    app, pid = _live_app_and_pid()
    if not app:
        raise RuntimeError("No running Ableton Live found on port %d." % LIVE_PORT)
    name = _app_name(app)
    result = {"app": app, "pid": pid, "save": save}

    # 1. Ask Live to quit (Apple 'quit' event); it blocks if a save dialog
    #    appears, so fire it without waiting.
    _osa_async('tell application "%s" to quit' % name)

    # 2. A clean quit is fast; still alive after dirty_after => a save dialog is
    #    blocking => the set has unsaved changes.
    sleep(dirty_after)
    result["was_dirty"] = _pid_alive(pid)

    if result["was_dirty"]:
        # Bring Live's dialog frontmost first — System Events keystrokes go to
        # the frontmost app, so without this they'd miss the dialog entirely.
        _osa('tell application "%s" to activate' % name)
        sleep(0.4)
        if save == "save":
            # Return = Save (overwrites a set that already has a file; an
            # Untitled set then pops a Save-As path dialog we can't fill).
            _osa('tell application "System Events" to keystroke return')
        else:
            # Cmd+D = Don't Save in Ableton's save dialog (NOT Cmd+Delete —
            # Live's dialog is a custom AXDialog that ignores Cmd+Delete).
            _osa('tell application "System Events" to keystroke "d" using {command down}')
        result["dialog_answered"] = save

    # 3. Wait for the process to actually exit.
    if _pid_alive(pid) and not _wait_until(lambda: not _pid_alive(pid),
                                           timeout=20.0, sleep=sleep):
        result["quit"] = False
        result["error"] = (
            "Live did not quit. With save='save' on an Untitled set the Save-As "
            "dialog needs a file path (save the set manually first), or System "
            "Events lacks Accessibility permission to answer the dialog.")
        return result
    result["quit"] = True

    # 4. Relaunch and wait for the control surface to bind the port again.
    if relaunch:
        _open_app(app)
        result["relaunched"] = True
        result["surface_up"] = _wait_until(_port_listening, timeout=wait_timeout,
                                           sleep=sleep)
    return result


@mcp.tool()
def restart_live(ctx: Context, save: str = "discard", relaunch: bool = True,
                 wait_timeout: float = 90.0) -> str:
    """Gracefully quit and relaunch the running Ableton Live (no crash-recovery
    prompt). Use this for an automated Live bounce after a Remote Script change.

    save: how to handle UNSAVED changes if Live prompts on quit —
      'discard' (default; lose unsaved edits) or 'save' (overwrite; only works
      for a set that already has a file — an Untitled set has no path and the
      quit is reported as failed so you can save it by hand first).
    relaunch: reopen Live after it quits (default True), then wait up to
      wait_timeout seconds for the control surface to rebind port 9877.

    Returns JSON {ok, data:{app, was_dirty, quit, relaunched, surface_up, ...}}.
    NOTE: this only restarts ABLETON. A server.py change still needs a Claude
    Code restart (the MCP server can't restart its own process); a Remote-Script
    change is fully covered by reinstalling the script + this bounce. Discarding
    unsaved work is irreversible — prefer the /ableton:restart command, which
    asks before discarding.
    """
    try:
        save = (save or "discard").lower()
        data = _restart_live_impl(save=save, relaunch=relaunch,
                                  wait_timeout=wait_timeout)
        return _ok(data)
    except (ValueError, RuntimeError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("restart_live error: %s", e)
        return _err("restart_live error: %s" % e)


@mcp.tool()
def batch(ctx: Context, commands: List[Dict[str, Any]],
          stop_on_error: bool = True) -> str:
    """Run several state-mutating commands in ONE Live task / one socket round-trip.

    Collapses N writes into a single scheduled main-thread task, removing the
    per-command settle/latency overhead and making the sequence atomic under
    stop_on_error. Use this whenever you would otherwise fire several mutations
    back-to-back (e.g. create a track, name it, load an instrument, create a
    clip, add notes).

    Each member is {"type": <command>, "params": {...}} where <command> is the
    WIRE name of a mutating op and params are exactly what that op's remote
    handler expects. Examples of <command>: "create_midi_track" (params {index}),
    "set_track_name" ({track_index, name}), "create_clip" ({track_index,
    clip_index, length}), "add_notes_to_clip" ({track_index, clip_index, notes}),
    "set_device_parameter" ({track_index, device_index, parameter_index, value}),
    "set_mixer_property" ({track_index, property, value, track_type, send_index}).
    Note: to load an instrument/effect by URI use type "load_browser_item" with
    params {track_index, item_uri} (the same call load_instrument_or_effect makes).
    Members run SYNCHRONOUSLY in the given order.

    IMPORTANT constraints:
    - Only MUTATIONS are batchable. Read commands (get_*) are rejected; call those
      separately. Name/index resolution that needs a read first (e.g. resolving a
      device parameter by name) must be done before building the batch.
    - Do NOT batch operations that depend on a previous write SETTLING
      asynchronously before the next one reads it (e.g. set_song_position then a
      cue toggle). Those must stay separate calls; members here share one Live
      task with no settle between them.

    Parameters:
    - commands: list of {type, params} mutation members (1..64).
    - stop_on_error: if true (default), stop at the first failing member and
      return partial results; if false, attempt every member.

    Returns JSON {count, completed, failed_index,
    results:[{status, result|message}]} where failed_index is -1 when all ran.
    """
    try:
        members = validate_batch(commands, MUTATING_COMMANDS)
        flag = coerce_stop_on_error(stop_on_error)
        ableton = get_ableton_connection()
        result = ableton.send_batch(members, flag)
        return _ok(result)
    except Exception as e:
        logger.error(f"Error running batch: {str(e)}")
        return _err(f"Error running batch: {str(e)}")
@mcp.tool()
def get_track_info(ctx: Context, track_index: int) -> str:
    """
    Get detailed information about a specific track in Ableton.
    
    Parameters:
    - track_index: The index of the track to get information about
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_track_info", {"track_index": track_index})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error getting track info from Ableton: {str(e)}")
        return _err(f"Error getting track info: {str(e)}")
@mcp.tool()
def get_view_selection(ctx: Context) -> str:
    """Read the current Live view selection: selected track (index/name/type),
    selected scene (index), whether a detail clip is shown, and the highlighted
    Session clip slot (track + scene coordinates)."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_view_selection")
        return _ok(result)
    except Exception as e:
        logger.error(f"Error getting view selection: {str(e)}")
        return _err(f"Error getting view selection: {str(e)}")
@mcp.tool()
def set_selected_track(
    ctx: Context, track_index: int, track_type: str = "regular"
) -> str:
    """
    Select a track in the Session/Arrangement view.

    Parameters:
    - track_index: index within its collection (0-based)
    - track_type: "regular" (default), "return", or "master" (master ignores index)
    """
    try:
        ttype = normalize_track_type(track_type)
        idx = coerce_view_index(track_index) if ttype != "master" else 0
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "set_selected_track", {"track_index": idx, "track_type": ttype}
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error setting selected track: {str(e)}")
        return _err(f"Error setting selected track: {str(e)}")
@mcp.tool()
def set_selected_scene(ctx: Context, scene_index: int) -> str:
    """
    Select a scene in the Session view.

    Parameters:
    - scene_index: index of the scene (0-based)
    """
    try:
        idx = coerce_view_index(scene_index)
        ableton = get_ableton_connection()
        result = ableton.send_command("set_selected_scene", {"scene_index": idx})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error setting selected scene: {str(e)}")
        return _err(f"Error setting selected scene: {str(e)}")
@mcp.tool()
def set_detail_clip(ctx: Context, track_index: int, clip_slot_index: int) -> str:
    """
    Show a Session clip in Live's Detail (clip) view.

    Parameters:
    - track_index: index of the (regular) track
    - clip_slot_index: index of the clip slot; the slot must contain a clip
    """
    try:
        t = coerce_view_index(track_index)
        s = coerce_view_index(clip_slot_index)
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "set_detail_clip", {"track_index": t, "clip_slot_index": s}
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error setting detail clip: {str(e)}")
        return _err(f"Error setting detail clip: {str(e)}")
@mcp.tool()
def set_highlighted_clip_slot(
    ctx: Context, track_index: int, scene_index: int
) -> str:
    """
    Highlight a Session clip slot (defined by a regular track + scene).

    Parameters:
    - track_index: index of the (regular) track
    - scene_index: index of the scene (the clip slot row)
    """
    try:
        t = coerce_view_index(track_index)
        s = coerce_view_index(scene_index)
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "set_highlighted_clip_slot", {"track_index": t, "scene_index": s}
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error setting highlighted clip slot: {str(e)}")
        return _err(f"Error setting highlighted clip slot: {str(e)}")
@mcp.tool()
def set_track_fold(
    ctx: Context, track_index: int, folded: Union[bool, int, str]
) -> str:
    """
    Fold or unfold a group track (collapse/expand its contained tracks).

    Parameters:
    - track_index: index of the (regular) track; must be a group track (foldable)
    - folded: true to fold (collapse), false to unfold (true/false, on/off, 1/0)

    Rejected cleanly if the track is not a group track.
    """
    try:
        idx = coerce_view_index(track_index)
        value = coerce_on_value(folded)
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "set_track_fold", {"track_index": idx, "folded": value}
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error setting track fold: {str(e)}")
        return _err(f"Error setting track fold: {str(e)}")
@mcp.tool()
def get_device_parameters(
    ctx: Context, track_index: int, device_index: int, track_type: str = "regular"
) -> str:
    """
    List all automatable parameters of a device on a track, with current
    value, min, max, whether it's quantized, and (for quantized params) the
    list of selectable value items.

    Parameters:
    - track_index: index of the track (ignored for master)
    - device_index: index of the device on that track (0 = first device)
    - track_type: 'regular' (default), 'return', or 'master'

    Returns JSON with the device name and a parameters list (each: index, name,
    value, min, max, is_quantized, value_items).
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "get_device_parameters",
            {
                "track_index": track_index,
                "device_index": device_index,
                "track_type": track_type,
            },
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error getting device parameters: {str(e)}")
        return _err(f"Error getting device parameters: {str(e)}")
@mcp.tool()
def set_device_parameter(
    ctx: Context,
    track_index: int,
    device_index: int,
    parameter: Union[int, str],
    value: float,
    track_type: str = "regular",
) -> str:
    """
    Set a single device/instrument parameter.

    Parameters:
    - track_index: index of the track (ignored for master)
    - device_index: index of the device on that track
    - parameter: parameter index (int) OR parameter name (str, case-insensitive)
    - value: target value (clamped to the parameter's min/max). For quantized
      parameters, pass the integer index of the desired value item.
    - track_type: 'regular' (default), 'return', or 'master'
    """
    try:
        ableton = get_ableton_connection()
        # Fetch the parameter list to resolve name->index and validate.
        info = ableton.send_command(
            "get_device_parameters",
            {
                "track_index": track_index,
                "device_index": device_index,
                "track_type": track_type,
            },
        )
        params = info.get("parameters", [])
        idx = resolve_parameter_index(params, parameter)
        result = ableton.send_command(
            "set_device_parameter",
            {
                "track_index": track_index,
                "device_index": device_index,
                "parameter_index": idx,
                "value": value,
                "track_type": track_type,
            },
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error setting device parameter: {str(e)}")
        return _err(f"Error setting device parameter: {str(e)}")
@mcp.tool()
def get_device_info(
    ctx: Context, track_index: int, device_index: int, track_type: str = "regular"
) -> str:
    """
    Get detailed info about a device: class, type, on/off state, whether it is
    a rack (can_have_chains) or drum rack (can_have_drum_pads), and a summary of
    its macros and chains when it is a rack.

    Parameters:
    - track_index: index of the track
    - device_index: index of the device on that track (0 = first device)
    - track_type: 'regular' (default), 'return', or 'master'
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "get_device_info",
            {
                "track_index": track_index,
                "device_index": device_index,
                "track_type": track_type,
            },
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error getting device info: {str(e)}")
        return _err(f"Error getting device info: {str(e)}")
@mcp.tool()
def delete_device(
    ctx: Context, track_index: int, device_index: int, track_type: str = "regular"
) -> str:
    """
    Delete a device from a track. Remaining devices re-index downward.

    Parameters:
    - track_index: index of the track
    - device_index: index of the device to delete
    - track_type: 'regular' (default), 'return', or 'master'
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "delete_device",
            {
                "track_index": track_index,
                "device_index": device_index,
                "track_type": track_type,
            },
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error deleting device: {str(e)}")
        return _err(f"Error deleting device: {str(e)}")
@mcp.tool()
def set_device_on(
    ctx: Context,
    track_index: int,
    device_index: int,
    on: Union[bool, int, str],
    track_type: str = "regular",
) -> str:
    """
    Enable or disable a device (writes its 'Device On' parameter).

    Parameters:
    - track_index: index of the track
    - device_index: index of the device
    - on: true/false (also accepts on/off, 1/0, yes/no)
    - track_type: 'regular' (default), 'return', or 'master'
    """
    try:
        on_bool = coerce_on_value(on)
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "set_device_on",
            {
                "track_index": track_index,
                "device_index": device_index,
                "on": on_bool,
                "track_type": track_type,
            },
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error setting device on/off: {str(e)}")
        return _err(f"Error setting device on/off: {str(e)}")
@mcp.tool()
def get_rack_macros(
    ctx: Context, track_index: int, device_index: int, track_type: str = "regular"
) -> str:
    """
    List the macro controls of a rack device, each with its name, current value,
    min, max, and the underlying device-parameter index.

    Parameters:
    - track_index: index of the track
    - device_index: index of the rack device
    - track_type: 'regular' (default), 'return', or 'master'
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "get_rack_macros",
            {
                "track_index": track_index,
                "device_index": device_index,
                "track_type": track_type,
            },
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error getting rack macros: {str(e)}")
        return _err(f"Error getting rack macros: {str(e)}")
@mcp.tool()
def set_rack_macro(
    ctx: Context,
    track_index: int,
    device_index: int,
    macro: Union[int, str],
    value: float,
    track_type: str = "regular",
) -> str:
    """
    Set a rack macro control value.

    Parameters:
    - track_index: index of the track
    - device_index: index of the rack device
    - macro: macro number (1-based int, e.g. 3) OR macro name (e.g. 'Macro 3')
    - value: target value (clamped to the macro's min/max, typically 0..127)
    - track_type: 'regular' (default), 'return', or 'master'
    """
    try:
        ableton = get_ableton_connection()
        # Fetch macro list to resolve macro->device-parameter index.
        info = ableton.send_command(
            "get_rack_macros",
            {
                "track_index": track_index,
                "device_index": device_index,
                "track_type": track_type,
            },
        )
        macros = info.get("macros", [])
        param_index = resolve_macro(macros, macro)
        result = ableton.send_command(
            "set_rack_macro",
            {
                "track_index": track_index,
                "device_index": device_index,
                "parameter_index": param_index,
                "value": value,
                "track_type": track_type,
            },
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error setting rack macro: {str(e)}")
        return _err(f"Error setting rack macro: {str(e)}")
@mcp.tool()
def get_rack_chains(
    ctx: Context, track_index: int, device_index: int, track_type: str = "regular"
) -> str:
    """
    List the chains of a rack device, each with its name, mute/solo state, and
    the devices it contains.

    Parameters:
    - track_index: index of the track
    - device_index: index of the rack device
    - track_type: 'regular' (default), 'return', or 'master'
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "get_rack_chains",
            {
                "track_index": track_index,
                "device_index": device_index,
                "track_type": track_type,
            },
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error getting rack chains: {str(e)}")
        return _err(f"Error getting rack chains: {str(e)}")
@mcp.tool()
def set_chain_property(
    ctx: Context,
    track_index: int,
    device_index: int,
    chain_index: int,
    property: str,
    value: Union[bool, int, float, str],
    track_type: str = "regular",
) -> str:
    """
    Set a property on one chain of a rack device.

    Parameters:
    - track_index: index of the track
    - device_index: index of the rack device
    - chain_index: index of the chain within the rack (0 = first)
    - property: 'mute' or 'solo' (bool) or 'volume' / 'panning' (float, clamped)
    - value: bool for mute/solo; float for volume/panning
    - track_type: 'regular' (default), 'return', or 'master'
    """
    try:
        canonical = validate_chain_property(normalize_chain_property(property))
        coerced = coerce_chain_value(canonical, value)
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "set_chain_property",
            {
                "track_index": track_index,
                "device_index": device_index,
                "chain_index": chain_index,
                "property": canonical,
                "value": coerced,
                "track_type": track_type,
            },
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error setting chain property: {str(e)}")
        return _err(f"Error setting chain property: {str(e)}")
@mcp.tool()
def get_mixer(ctx: Context, track_index: int, track_type: str = "regular") -> str:
    """
    Read mixer state (volume, pan, mute, solo, arm, sends, crossfade assign)
    for a track. Fields are present only where the track type supports them.

    Parameters:
    - track_index: index of the track (ignored for master; pass 0)
    - track_type: "regular" (default), "return", or "master"
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "get_mixer",
            {"track_index": track_index, "track_type": track_type},
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error getting mixer state: {str(e)}")
        return _err(f"Error getting mixer state: {str(e)}")
@mcp.tool()
def set_mixer_property(
    ctx: Context,
    track_index: int,
    property: str,
    value: float,
    track_type: str = "regular",
    send_index: int = -1,
) -> str:
    """
    Set a single mixer property on a track.

    Parameters:
    - track_index: index of the track (ignored for master; pass 0)
    - property: one of volume, pan, mute, solo, arm, send, crossfade_assign
      (aliases accepted: panning, vol, xfade, ...)
    - value: continuous params (volume/pan/send) are clamped to range;
      mute/solo/arm take 0/1; crossfade_assign takes 0=A, 1=None, 2=B
    - track_type: "regular" (default), "return", or "master"
    - send_index: required when property="send" (index of the return-track send)
    """
    try:
        canonical = normalize_property(property)
        validate_property(track_type, canonical)
        if canonical == "send" and send_index < 0:
            return _err("Error: property 'send' requires send_index >= 0")
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "set_mixer_property",
            {
                "track_index": track_index,
                "track_type": track_type,
                "property": canonical,
                "value": value,
                "send_index": send_index,
            },
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error setting mixer property: {str(e)}")
        return _err(f"Error setting mixer property: {str(e)}")
@mcp.tool()
def get_routing(ctx: Context, track_index: int, track_type: str = "regular") -> str:
    """
    Read input/output routing and input monitoring for a track. Each routing
    endpoint reports its current value and the list of available choices.
    Fields are present only where the track type supports them (return/master
    expose output routing only; no input or monitoring).

    Parameters:
    - track_index: index of the track (ignored for master; pass 0)
    - track_type: "regular" (default), "return", or "master"
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "get_routing",
            {"track_index": track_index, "track_type": track_type},
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error getting routing: {str(e)}")
        return _err(f"Error getting routing: {str(e)}")
@mcp.tool()
def set_routing(
    ctx: Context,
    track_index: int,
    property: str,
    value: Union[int, str],
    track_type: str = "regular",
) -> str:
    """
    Set an input/output routing endpoint or input monitoring on a track.

    Parameters:
    - track_index: index of the track (ignored for master; pass 0)
    - property: input_type, input_channel, output_type, output_channel, or monitor
    - value: for routing props, the target's display_name (str, case-insensitive)
      or integer identifier (see get_routing for available choices); for monitor,
      an int (0=In, 1=Auto, 2=Off)
    - track_type: "regular" (default), "return", or "master"
      (return/master support output_type/output_channel only)
    """
    try:
        canonical = normalize_routing_property(property)
        validate_routing_property(track_type, canonical)
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "set_routing",
            {
                "track_index": track_index,
                "track_type": track_type,
                "property": canonical,
                "value": value,
            },
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error setting routing: {str(e)}")
        return _err(f"Error setting routing: {str(e)}")
@mcp.tool()
def create_midi_track(ctx: Context, track_index: int = None, index: int = None) -> str:
    """
    Create a new MIDI track in the Ableton session.

    Parameters:
    - track_index: The index to insert the track at (-1 = end of list).
      (`index` is accepted as a legacy alias.)
    """
    try:
        idx = _resolve_index(track_index, index, default=-1, label="track_index")
        ableton = get_ableton_connection()
        result = ableton.send_command("create_midi_track", {"index": idx})
        return _ok(f"Created new MIDI track: {result.get('name', 'unknown')}")
    except Exception as e:
        logger.error(f"Error creating MIDI track: {str(e)}")
        return _err(f"Error creating MIDI track: {str(e)}")
@mcp.tool()
def set_track_name(ctx: Context, track_index: int, name: str) -> str:
    """
    Set the name of a track.
    
    Parameters:
    - track_index: The index of the track to rename
    - name: The new name for the track
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_name", {"track_index": track_index, "name": name})
        return _ok(f"Renamed track to: {result.get('name', name)}")
    except Exception as e:
        logger.error(f"Error setting track name: {str(e)}")
        return _err(f"Error setting track name: {str(e)}")
@mcp.tool()
def create_audio_track(ctx: Context, track_index: int = None, index: int = None) -> str:
    """
    Create a new audio track.

    Parameters:
    - track_index: Insert position (-1 = end of list). (`index` is accepted as a
      legacy alias.)
    """
    try:
        resolved = coerce_create_index(
            _resolve_index(track_index, index, default=-1, label="track_index"))
        ableton = get_ableton_connection()
        result = ableton.send_command("create_audio_track", {"index": resolved})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error creating audio track: {str(e)}")
        return _err(f"Error creating audio track: {str(e)}")
@mcp.tool()
def create_return_track(ctx: Context) -> str:
    """
    Create a new return track (added at the end of the return-track list).
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_return_track", {})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error creating return track: {str(e)}")
        return _err(f"Error creating return track: {str(e)}")
@mcp.tool()
def delete_track(ctx: Context, track_index: int = None, index: int = None) -> str:
    """
    Delete the regular (audio/MIDI) track at the given index. Remaining tracks
    re-index; re-read get_session_info afterward.

    Parameters:
    - track_index: The index of the track to delete. (`index` is accepted as a
      legacy alias.)
    """
    try:
        resolved = coerce_track_index(
            _resolve_index(track_index, index, label="track_index"))
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_track", {"index": resolved})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error deleting track: {str(e)}")
        return _err(f"Error deleting track: {str(e)}")
@mcp.tool()
def delete_return_track(ctx: Context, track_index: int = None, index: int = None) -> str:
    """
    Delete the return track at the given index. Remaining return tracks
    re-index; re-read get_session_info afterward.

    Parameters:
    - track_index: The index of the return track to delete. (`index` is accepted
      as a legacy alias.)
    """
    try:
        resolved = coerce_track_index(
            _resolve_index(track_index, index, label="track_index"))
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_return_track", {"index": resolved})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error deleting return track: {str(e)}")
        return _err(f"Error deleting return track: {str(e)}")
@mcp.tool()
def duplicate_track(ctx: Context, track_index: int = None, index: int = None) -> str:
    """
    Duplicate the regular track at the given index. Live inserts the copy and
    selects it; the returned new_index is the copy's position.

    Parameters:
    - track_index: The index of the track to duplicate. (`index` is accepted as
      a legacy alias.)
    """
    try:
        resolved = coerce_track_index(
            _resolve_index(track_index, index, label="track_index"))
        ableton = get_ableton_connection()
        result = ableton.send_command("duplicate_track", {"index": resolved})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error duplicating track: {str(e)}")
        return _err(f"Error duplicating track: {str(e)}")
@mcp.tool()
def undo(ctx: Context) -> str:
    """
    Undo the last action. WARNING: this walks Live's GLOBAL undo stack; it can
    undo actions the user performed by hand, not just MCP changes. No-op (clean
    result) if there is nothing to undo.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("undo", {})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error performing undo: {str(e)}")
        return _err(f"Error performing undo: {str(e)}")
@mcp.tool()
def redo(ctx: Context) -> str:
    """
    Redo the last undone action. Operates on Live's global undo stack. No-op
    (clean result) if there is nothing to redo.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("redo", {})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error performing redo: {str(e)}")
        return _err(f"Error performing redo: {str(e)}")
@mcp.tool()
def create_clip(ctx: Context, track_index: int, clip_index: int, length: float = 4.0) -> str:
    """
    Create a new MIDI clip in the specified track and clip slot.
    
    Parameters:
    - track_index: The index of the track to create the clip in
    - clip_index: The index of the clip slot to create the clip in
    - length: The length of the clip in beats (default: 4.0)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_clip", {
            "track_index": track_index, 
            "clip_index": clip_index, 
            "length": length
        })
        return _ok(f"Created new clip at track {track_index}, slot {clip_index} with length {length} beats")
    except Exception as e:
        logger.error(f"Error creating clip: {str(e)}")
        return _err(f"Error creating clip: {str(e)}")
@mcp.tool()
def add_notes_to_clip(
    ctx: Context, 
    track_index: int, 
    clip_index: int, 
    notes: List[Dict[str, Union[int, float, bool]]]
) -> str:
    """
    Add MIDI notes to a clip (MIDI clips only). Uses the Live 11+ extended note
    API (no editor dialog).

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - notes: List of note dictionaries. Required-ish fields: pitch, start_time,
      duration, velocity, mute. Optional Live 11+ fields (sensible defaults):
      probability (0.0-1.0), velocity_deviation, release_velocity (0-127).
    """
    try:
        notes = [normalize_note(n) for n in notes]
        ableton = get_ableton_connection()
        result = ableton.send_command("add_notes_to_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
            "notes": notes
        })
        return _ok(f"Added {len(notes)} notes to clip at track {track_index}, slot {clip_index}")
    except Exception as e:
        logger.error(f"Error adding notes to clip: {str(e)}")
        return _err(f"Error adding notes to clip: {str(e)}")

@mcp.tool()
def generate_chord_progression(
    ctx: Context, track_index: int, clip_index: int,
    progression: List[str], key: str = None, scale: str = None,
    bars: int = 4, octave: int = 3, durations: List[float] = None,
    replace: bool = False,
) -> str:
    """Generate a chord progression into a session clip slot. Creates the MIDI
    clip if the slot is empty (length = bars*4 beats), else requires replace=true.

    Parameters:
    - track_index / clip_index: where to write
    - progression: roman numerals ('I','vi','IV','V') and/or chord symbols
      ('Cmaj7','Am7'); romans resolve diatonically to key/scale
    - key/scale: optional; if both omitted, the set's key/scale is read
    - bars: clip length in 4/4 bars (default 4)
    - octave: Ableton octave label, C3=60 (default 3)
    - durations: optional per-chord beat lengths (default: evenly split)
    - replace: overwrite an occupied slot (default false)
    """
    try:
        root, intervals = _resolve_scale(key, scale)
        notes = comp.build_chord_progression(
            progression, root, intervals, bars=bars, octave=octave,
            durations=durations)
        count = _emit_to_slot(track_index, clip_index, notes, bars, replace)
        return _ok({"notes_added": count, "bars": bars,
                    "chords": len(progression)})
    except Exception as e:
        logger.error("Error generating chord progression: %s", e)
        return _err("Error generating chord progression: %s" % e)


@mcp.tool()
def generate_bassline(
    ctx: Context, track_index: int, clip_index: int,
    progression: List[str] = None, style: str = "root",
    key: str = None, scale: str = None, bars: int = 4, octave: int = 1,
    seed: int = None, replace: bool = False,
) -> str:
    """Generate a bassline into a session clip slot. With a progression the bass
    follows the chord roots; without one it lays one scale-root per bar.

    Parameters:
    - progression: optional chord list (roman/symbol) for harmonic context
    - style: root | octaves | arp | walking (walking needs a progression)
    - key/scale: optional; if both omitted, the set's key/scale is read
    - octave: Ableton octave label (default 1)
    - seed: optional int for reproducible randomness
    - replace: overwrite an occupied slot
    """
    try:
        root, intervals = _resolve_scale(key, scale)
        notes = comp.build_bassline(
            progression=progression, style=style, root=root, intervals=intervals,
            bars=bars, octave=octave, rng=comp.make_rng(seed))
        count = _emit_to_slot(track_index, clip_index, notes, bars, replace)
        return _ok({"notes_added": count, "bars": bars, "style": style})
    except Exception as e:
        logger.error("Error generating bassline: %s", e)
        return _err("Error generating bassline: %s" % e)


@mcp.tool()
def generate_melody(
    ctx: Context, track_index: int, clip_index: int,
    key: str = None, scale: str = None, bars: int = 4,
    contour: str = "arch", density: float = 0.5, octave: int = 4,
    seed: int = None, replace: bool = False,
) -> str:
    """Generate an in-scale monophonic melody into a session clip slot.

    Parameters:
    - key/scale: optional; if both omitted, the set's key/scale is read
    - contour: up | down | arch | valley | random
    - density: 0..1 probability each eighth-note slot sounds (default 0.5)
    - octave: Ableton octave label (default 4 = around middle C)
    - seed: optional int for reproducible randomness
    - replace: overwrite an occupied slot
    """
    try:
        root, intervals = _resolve_scale(key, scale)
        notes = comp.build_melody(
            root, intervals, bars=bars, contour=contour, density=density,
            octave=octave, rng=comp.make_rng(seed))
        count = _emit_to_slot(track_index, clip_index, notes, bars, replace)
        return _ok({"notes_added": count, "bars": bars, "contour": contour})
    except Exception as e:
        logger.error("Error generating melody: %s", e)
        return _err("Error generating melody: %s" % e)


@mcp.tool()
def generate_drum_pattern(
    ctx: Context, track_index: int, clip_index: int,
    style: str = "four_on_floor", bars: int = 4, fills: bool = False,
    seed: int = None, replace: bool = False,
) -> str:
    """Generate a drum pattern (GM drum map) into a session clip slot. Intended
    for a Drum Rack track (kick=36, snare=38, closed hat=42, ...).

    Parameters:
    - track_index / clip_index: where to write
    - style: four_on_floor | basic_rock | breakbeat | hihat_8ths | boom_bap
    - bars: clip length in 4/4 bars (default 4)
    - fills: add a seeded snare fill in the last bar
    - seed: optional int for reproducible randomness
    - replace: overwrite an occupied slot
    """
    try:
        notes = comp.build_drum_pattern(
            style=style, bars=bars, fills=fills, rng=comp.make_rng(seed))
        count = _emit_to_slot(track_index, clip_index, notes, bars, replace)
        return _ok({"notes_added": count, "bars": bars, "style": style})
    except Exception as e:
        logger.error("Error generating drum pattern: %s", e)
        return _err("Error generating drum pattern: %s" % e)


@mcp.tool()
def humanize_clip(
    ctx: Context, track_index: int, clip_index: int,
    timing: float = 0.02, velocity: float = 8.0, seed: int = None,
) -> str:
    """Humanize a clip: jitter note onsets (+/- timing beats) and velocities
    (+/- velocity). Rewrites the clip's notes in place.

    Parameters:
    - track_index / clip_index: locate the clip
    - timing: max onset jitter in beats (default 0.02)
    - velocity: max velocity jitter (default 8)
    - seed: optional int for reproducible jitter
    """
    try:
        rng = comp.make_rng(seed)
        count = _transform_clip(
            track_index, clip_index,
            lambda ns: comp.humanize(ns, timing=timing, velocity=velocity, rng=rng))
        return _ok({"notes": count})
    except Exception as e:
        logger.error("Error humanizing clip: %s", e)
        return _err("Error humanizing clip: %s" % e)


@mcp.tool()
def quantize_clip_to_scale(
    ctx: Context, track_index: int, clip_index: int,
    key: str = None, scale: str = None,
) -> str:
    """Snap every note in a clip to the nearest in-scale pitch.

    Parameters:
    - track_index / clip_index: locate the clip
    - key/scale: optional; if both omitted, the set's key/scale is read
    """
    try:
        root, intervals = _resolve_scale(key, scale)
        count = _transform_clip(
            track_index, clip_index,
            lambda ns: comp.quantize_to_scale(ns, root, intervals))
        return _ok({"notes": count})
    except Exception as e:
        logger.error("Error quantizing clip to scale: %s", e)
        return _err("Error quantizing clip to scale: %s" % e)


@mcp.tool()
def arpeggiate_clip(
    ctx: Context, track_index: int, clip_index: int,
    mode: str = "up", rate: float = 0.25, gate: float = 0.9, seed: int = None,
) -> str:
    """Arpeggiate a clip: expand simultaneous notes (chords) into sequential
    notes. Single (non-chord) notes pass through unchanged. Rewrites the clip.

    Parameters:
    - track_index / clip_index: locate the clip
    - mode: up | down | updown | random | strum
    - rate: step spacing in beats (default 0.25 = sixteenth)
    - gate: note length as a fraction of rate (default 0.9)
    - seed: optional int (only used by mode=random)
    """
    try:
        rng = comp.make_rng(seed)
        count = _transform_clip(
            track_index, clip_index,
            lambda ns: comp.arpeggiate(ns, mode=mode, rate=rate, gate=gate, rng=rng))
        return _ok({"notes": count, "mode": mode})
    except Exception as e:
        logger.error("Error arpeggiating clip: %s", e)
        return _err("Error arpeggiating clip: %s" % e)


@mcp.tool()
def harmonize_clip(
    ctx: Context, track_index: int, clip_index: int,
    intervals: List[int] = None, degrees: List[int] = None,
    key: str = None, scale: str = None,
) -> str:
    """Add a harmony voice to each note in a clip. Provide exactly ONE of
    intervals (fixed semitone offsets, snapped to scale) or degrees (scale-step
    offsets, kept diatonic).

    Parameters:
    - track_index / clip_index: locate the clip
    - intervals: e.g. [4,7] adds a third and fifth above, snapped to scale
    - degrees: e.g. [2] adds a note two scale-steps up (a diatonic third)
    - key/scale: optional; if both omitted, the set's key/scale is read
    """
    try:
        root, scale_intervals = _resolve_scale(key, scale)
        count = _transform_clip(
            track_index, clip_index,
            lambda ns: comp.harmonize(ns, root, scale_intervals,
                                      intervals=intervals, degrees=degrees))
        return _ok({"notes": count})
    except Exception as e:
        logger.error("Error harmonizing clip: %s", e)
        return _err("Error harmonizing clip: %s" % e)


@mcp.tool()
def set_clip_name(ctx: Context, track_index: int, clip_index: int, name: str) -> str:
    """
    Set the name of a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - name: The new name for the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_name", {
            "track_index": track_index,
            "clip_index": clip_index,
            "name": name
        })
        return _ok(f"Renamed clip at track {track_index}, slot {clip_index} to '{name}'")
    except Exception as e:
        logger.error(f"Error setting clip name: {str(e)}")
        return _err(f"Error setting clip name: {str(e)}")
# --- Phase 3: Clip & MIDI editing ---

@mcp.tool()
def get_clip_info(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Read properties of a clip. Audio-only fields (warping, warp_mode, gain,
    gain_display_string, pitch_coarse, pitch_fine) appear only on audio clips.

    Parameters:
    - track_index: index of the track containing the clip
    - clip_index: index of the clip slot containing the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "get_clip_info",
            {"track_index": track_index, "clip_index": clip_index},
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error getting clip info: {str(e)}")
        return _err(f"Error getting clip info: {str(e)}")
@mcp.tool()
def get_clip_notes(
    ctx: Context,
    track_index: int,
    clip_index: int,
    from_time: float = 0.0,
    time_span: float = -1.0,
    from_pitch: int = 0,
    pitch_span: int = 128,
) -> str:
    """
    Read MIDI notes from a clip (MIDI clips only). Uses the Live 11+ extended note
    API. Returns a list of note dicts {note_id, pitch, start_time, duration,
    velocity, mute, probability, velocity_deviation, release_velocity}. The
    note_id can be passed to modify_clip_notes to edit a note in place.

    Parameters:
    - track_index / clip_index: locate the clip
    - from_time: start of the time window in beats (default 0.0)
    - time_span: length of the window in beats; -1 (default) = whole clip length
    - from_pitch: lowest pitch to include (default 0)
    - pitch_span: number of pitches to include (default 128 = all)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "get_clip_notes",
            {
                "track_index": track_index,
                "clip_index": clip_index,
                "from_time": from_time,
                "time_span": time_span,
                "from_pitch": from_pitch,
                "pitch_span": pitch_span,
            },
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error getting clip notes: {str(e)}")
        return _err(f"Error getting clip notes: {str(e)}")
@mcp.tool()
def replace_clip_notes(
    ctx: Context,
    track_index: int,
    clip_index: int,
    notes: List[Dict[str, Union[int, float, bool]]],
) -> str:
    """
    Replace ALL notes in a MIDI clip with the given notes (clears existing notes
    first, then adds these). MIDI clips only. Uses the Live 11+ extended note API.

    Parameters:
    - track_index / clip_index: locate the clip
    - notes: list of note dicts with pitch, start_time, duration, velocity, mute,
      and optional probability / velocity_deviation / release_velocity.
    """
    try:
        notes = [normalize_note(n) for n in notes]
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "replace_clip_notes",
            {"track_index": track_index, "clip_index": clip_index, "notes": notes},
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error replacing clip notes: {str(e)}")
        return _err(f"Error replacing clip notes: {str(e)}")
@mcp.tool()
def remove_clip_notes(
    ctx: Context,
    track_index: int,
    clip_index: int,
    from_time: float = 0.0,
    time_span: float = -1.0,
    from_pitch: int = 0,
    pitch_span: int = 128,
) -> str:
    """
    Remove MIDI notes within a time/pitch window from a clip (MIDI clips only).
    Defaults remove every note in the clip.

    Parameters:
    - track_index / clip_index: locate the clip
    - from_time: start of the time window in beats (default 0.0)
    - time_span: length of the window in beats; -1 (default) = whole clip length
    - from_pitch: lowest pitch to include (default 0)
    - pitch_span: number of pitches to include (default 128 = all)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "remove_clip_notes",
            {
                "track_index": track_index,
                "clip_index": clip_index,
                "from_time": from_time,
                "time_span": time_span,
                "from_pitch": from_pitch,
                "pitch_span": pitch_span,
            },
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error removing clip notes: {str(e)}")
        return _err(f"Error removing clip notes: {str(e)}")
@mcp.tool()
def modify_clip_notes(
    ctx: Context,
    track_index: int,
    clip_index: int,
    notes: List[Dict[str, Union[int, float, bool]]],
) -> str:
    """
    Edit existing notes in a MIDI clip in place, by note_id (MIDI clips only).
    Notes not referenced are left untouched -- no remove-and-re-add. Uses Live
    11's apply_note_modifications.

    Parameters:
    - track_index / clip_index: locate the clip
    - notes: list of dicts, each REQUIRING a note_id (from get_clip_notes) plus
      any fields to change: pitch, start_time, duration, velocity, mute,
      probability, velocity_deviation, release_velocity. Omitted fields are
      left as-is on that note.
    """
    try:
        cleaned = []
        for n in notes:
            if "note_id" not in n:
                return _err("Error: every note must include a note_id (see get_clip_notes)")
            entry = {"note_id": int(n["note_id"])}
            for f in NOTE_MOD_FIELDS:
                if f in n:
                    entry[f] = n[f]
            cleaned.append(entry)
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "modify_clip_notes",
            {"track_index": track_index, "clip_index": clip_index, "notes": cleaned},
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error modifying clip notes: {str(e)}")
        return _err(f"Error modifying clip notes: {str(e)}")
@mcp.tool()
def set_clip_property(
    ctx: Context,
    track_index: int,
    clip_index: int,
    property: str,
    value: Union[int, float, str, bool],
) -> str:
    """
    Set a single clip property. Audio-only properties are rejected on MIDI clips.

    Parameters:
    - track_index / clip_index: locate the clip
    - property: one of looping, loop_start, loop_end, start_marker, end_marker,
      signature_numerator, signature_denominator, warping, warp_mode, gain,
      pitch_coarse, pitch_fine, and the launch settings launch_mode,
      launch_quantization, legato, velocity_amount (valid on MIDI and audio).
      Aliases accepted: loop, pitch, detune, warp, launchmode, launchquant, velamount, ...
    - value: bools take 0/1/true/false; gain is 0.0-1.0 (clamped); pitch_coarse
      is -48..48 semitones, pitch_fine -50..50 cents (clamped); launch_mode (int
      0=Trigger,1=Gate,2=Toggle,3=Repeat) and launch_quantization (int) are enum
      indices; legato is a bool; velocity_amount is a float; others are
      floats/ints. To edit the loop window safely use set_clip_loop instead.
    """
    try:
        canonical = normalize_clip_property(property)
        coerced = coerce_clip_value(canonical, value)
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "set_clip_property",
            {
                "track_index": track_index,
                "clip_index": clip_index,
                "property": canonical,
                "value": coerced,
            },
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error setting clip property: {str(e)}")
        return _err(f"Error setting clip property: {str(e)}")
@mcp.tool()
def set_clip_loop(
    ctx: Context,
    track_index: int,
    clip_index: int,
    loop_start: float,
    loop_end: float,
    looping: int = -1,
) -> str:
    """
    Set a clip's loop window (both edges written in the correct order to avoid an
    invalid intermediate state) and optionally toggle looping.

    Parameters:
    - track_index / clip_index: locate the clip
    - loop_start / loop_end: loop bounds in beats (loop_end must exceed loop_start)
    - looping: -1 (default) leaves looping unchanged; 0 disables, 1 enables
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "set_clip_loop",
            {
                "track_index": track_index,
                "clip_index": clip_index,
                "loop_start": loop_start,
                "loop_end": loop_end,
                "looping": looping,
            },
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error setting clip loop: {str(e)}")
        return _err(f"Error setting clip loop: {str(e)}")
@mcp.tool()
def quantize_clip(
    ctx: Context,
    track_index: int,
    clip_index: int,
    grid: str,
    amount: float = 1.0,
) -> str:
    """
    Quantize the notes of a MIDI clip to a grid (MIDI clips only).

    Parameters:
    - track_index / clip_index: locate the clip
    - grid: one of none, 1/4, 1/8, 1/8t, 1/8+1/8t, 1/16, 1/16t,
      1/16+1/16t, 1/32
    - amount: quantization strength 0.0-1.0 (default 1.0 = full snap)
    """
    try:
        grid_value = resolve_quantize_grid(grid)
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "quantize_clip",
            {
                "track_index": track_index,
                "clip_index": clip_index,
                "grid": grid_value,
                "amount": amount,
            },
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error quantizing clip: {str(e)}")
        return _err(f"Error quantizing clip: {str(e)}")
@mcp.tool()
def duplicate_clip(
    ctx: Context,
    track_index: int,
    clip_index: int,
    target_clip_index: int = -1,
) -> str:
    """
    Duplicate a clip into another clip slot on the same track (no scene inserted).

    Parameters:
    - track_index / clip_index: locate the source clip
    - target_clip_index: destination slot; -1 (default) = clip_index + 1. The
      target slot must be empty.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "duplicate_clip",
            {
                "track_index": track_index,
                "clip_index": clip_index,
                "target_clip_index": target_clip_index,
            },
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error duplicating clip: {str(e)}")
        return _err(f"Error duplicating clip: {str(e)}")
@mcp.tool()
def delete_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Delete the clip in a clip slot (the slot itself remains, now empty).

    Parameters:
    - track_index / clip_index: locate the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "delete_clip",
            {"track_index": track_index, "clip_index": clip_index},
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error deleting clip: {str(e)}")
        return _err(f"Error deleting clip: {str(e)}")
@mcp.tool()
def set_tempo(ctx: Context, tempo: float) -> str:
    """
    Set the tempo of the Ableton session.
    
    Parameters:
    - tempo: The new tempo in BPM
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_tempo", {"tempo": tempo})
        return _ok(f"Set tempo to {tempo} BPM")
    except Exception as e:
        logger.error(f"Error setting tempo: {str(e)}")
        return _err(f"Error setting tempo: {str(e)}")
@mcp.tool()
def load_instrument_or_effect(ctx: Context, track_index: int, uri: str, track_type: str = "regular") -> str:
    """
    Load an instrument or effect onto a track using its URI.

    Parameters:
    - track_index: The index of the track to load onto (ignored for master)
    - uri: The URI of the instrument or effect to load (e.g., 'query:Synths#Instrument%20Rack:Bass:FileId_5116')
    - track_type: 'regular' (default), 'return', or 'master'. Only audio effects are valid on return/master tracks.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": uri,
            "track_type": track_type,
        })
        
        # Check if the instrument was loaded successfully
        if result.get("loaded", False):
            new_devices = result.get("new_devices", [])
            if new_devices:
                return _ok(f"Loaded '{uri}' on {track_type} track {track_index}. New devices: {', '.join(new_devices)}")
            else:
                devices = result.get("devices_after", [])
                return _ok(f"Loaded '{uri}' on {track_type} track {track_index}. Devices on track: {', '.join(devices)}")
        else:
            return _err(f"Failed to load '{uri}' on {track_type} track {track_index}")
    except Exception as e:
        logger.error(f"Error loading instrument by URI: {str(e)}")
        return _err(f"Error loading instrument by URI: {str(e)}")
@mcp.tool()
def fire_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Start playing a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("fire_clip", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return _ok(f"Started playing clip at track {track_index}, slot {clip_index}")
    except Exception as e:
        logger.error(f"Error firing clip: {str(e)}")
        return _err(f"Error firing clip: {str(e)}")
@mcp.tool()
def stop_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Stop playing a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("stop_clip", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return _ok(f"Stopped clip at track {track_index}, slot {clip_index}")
    except Exception as e:
        logger.error(f"Error stopping clip: {str(e)}")
        return _err(f"Error stopping clip: {str(e)}")
@mcp.tool()
def start_playback(ctx: Context) -> str:
    """Start playing the Ableton session."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("start_playback")
        return _ok("Started playback")
    except Exception as e:
        logger.error(f"Error starting playback: {str(e)}")
        return _err(f"Error starting playback: {str(e)}")
@mcp.tool()
def stop_playback(ctx: Context) -> str:
    """Stop playing the Ableton session."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("stop_playback")
        return _ok("Stopped playback")
    except Exception as e:
        logger.error(f"Error stopping playback: {str(e)}")
        return _err(f"Error stopping playback: {str(e)}")
# === Scenes ===============================================================

@mcp.tool()
def get_scenes(ctx: Context) -> str:
    """List all scenes in the session (index, name, color, tempo, time signature,
    is_empty, is_triggered)."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_scenes")
        return _ok(result)
    except Exception as e:
        logger.error(f"Error getting scenes: {str(e)}")
        return _err(f"Error getting scenes: {str(e)}")
@mcp.tool()
def fire_scene(ctx: Context, scene_index: int) -> str:
    """
    Launch a scene (fires every clip in that session row).

    Parameters:
    - scene_index: The index of the scene to fire
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("fire_scene", {"scene_index": scene_index})
        return _ok(f"Fired scene {scene_index}")
    except Exception as e:
        logger.error(f"Error firing scene: {str(e)}")
        return _err(f"Error firing scene: {str(e)}")
@mcp.tool()
def create_scene(ctx: Context, scene_index: int = None, index: int = None) -> str:
    """
    Create a new scene.

    Parameters:
    - scene_index: Position to insert at; -1 (default) appends at the end.
      (`index` is accepted as a legacy alias.)
    """
    try:
        idx = _resolve_index(scene_index, index, default=-1, label="scene_index")
        ableton = get_ableton_connection()
        result = ableton.send_command("create_scene", {"index": idx})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error creating scene: {str(e)}")
        return _err(f"Error creating scene: {str(e)}")
@mcp.tool()
def delete_scene(ctx: Context, scene_index: int) -> str:
    """
    Delete a scene.

    Parameters:
    - scene_index: The index of the scene to delete
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_scene", {"scene_index": scene_index})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error deleting scene: {str(e)}")
        return _err(f"Error deleting scene: {str(e)}")
@mcp.tool()
def duplicate_scene(ctx: Context, scene_index: int) -> str:
    """
    Duplicate a scene (the copy is inserted directly after it).

    Parameters:
    - scene_index: The index of the scene to duplicate
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("duplicate_scene", {"scene_index": scene_index})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error duplicating scene: {str(e)}")
        return _err(f"Error duplicating scene: {str(e)}")
@mcp.tool()
def set_scene_name(ctx: Context, scene_index: int, name: str) -> str:
    """
    Rename a scene.

    Parameters:
    - scene_index: The index of the scene
    - name: The new name
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "set_scene_name", {"scene_index": scene_index, "name": name})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error setting scene name: {str(e)}")
        return _err(f"Error setting scene name: {str(e)}")
@mcp.tool()
def set_scene_property(
    ctx: Context,
    scene_index: int,
    property: str,
    value: Union[int, float, str],
) -> str:
    """
    Set a scene property.

    Parameters:
    - scene_index: The index of the scene
    - property: One of 'color', 'tempo', 'tempo_enabled', 'time_signature'
      (aliases accepted: colour, bpm, tempo_on, time_sig/signature)
    - value: color int; tempo BPM (clamped 20-999); tempo_enabled on/off;
      time_signature as 'num/den' (e.g. '6/8')
    """
    try:
        canonical = normalize_scene_property(property)
        coerced = coerce_scene_value(canonical, value)
        # JSON can't carry a tuple; send time signature as a list.
        if isinstance(coerced, tuple):
            coerced = list(coerced)
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "set_scene_property",
            {"scene_index": scene_index, "property": canonical, "value": coerced},
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error setting scene property: {str(e)}")
        return _err(f"Error setting scene property: {str(e)}")
# === Transport ============================================================

@mcp.tool()
def get_transport(ctx: Context) -> str:
    """Get transport / arrangement state: is_playing, current_song_time, tempo,
    time signature, metronome, arrangement loop (on/start/length), record_mode,
    session_record, punch_in/out, and (Phase 10) groove_amount, swing_amount,
    clip_trigger_quantization, midi_recording_quantization, count_in_duration
    (read-only), nudge_up, nudge_down, and (Phase 11) can_capture_midi,
    is_counting_in, session_record_status (all read-only)."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_transport")
        return _ok(result)
    except Exception as e:
        logger.error(f"Error getting transport: {str(e)}")
        return _err(f"Error getting transport: {str(e)}")
@mcp.tool()
def set_groove_amount(ctx: Context, amount: Union[float, int, str]) -> str:
    """
    Set the global groove amount (how strongly clip grooves are applied).

    Parameters:
    - amount: 0.0-1.0 (clamped). Live displays this as 0-100%.

    Note: the returned dict can be stale (song-property-write lag); confirm via
    get_transport.
    """
    try:
        value = coerce_unit_float(amount, "groove_amount")
        ableton = get_ableton_connection()
        result = ableton.send_command("set_groove_amount", {"value": value})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error setting groove amount: {str(e)}")
        return _err(f"Error setting groove amount: {str(e)}")
@mcp.tool()
def set_swing_amount(ctx: Context, amount: Union[float, int, str]) -> str:
    """
    Set the global swing amount applied when adding/quantizing notes.

    Parameters:
    - amount: 0.0-1.0 (clamped).

    Note: confirm via get_transport (song-property-write lag).
    """
    try:
        value = coerce_unit_float(amount, "swing_amount")
        ableton = get_ableton_connection()
        result = ableton.send_command("set_swing_amount", {"value": value})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error setting swing amount: {str(e)}")
        return _err(f"Error setting swing amount: {str(e)}")
@mcp.tool()
def set_clip_trigger_quantization(
    ctx: Context, value: Union[int, str]
) -> str:
    """
    Set the global Session clip-launch quantization.

    Parameters:
    - value: an int 0-13 (Live.Song.Quantization) or a name: none, 8_bars,
      4_bars, 2_bars, 1_bar, 1/2, 1/2t, 1/4, 1/4t, 1/8, 1/8t, 1/16, 1/16t, 1/32.

    Note: confirm via get_transport (song-property-write lag).
    """
    try:
        resolved = resolve_clip_trigger_quantization(value)
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "set_clip_trigger_quantization", {"value": resolved}
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error setting clip trigger quantization: {str(e)}")
        return _err(f"Error setting clip trigger quantization: {str(e)}")
@mcp.tool()
def set_midi_recording_quantization(
    ctx: Context, value: Union[int, str]
) -> str:
    """
    Set the global MIDI-recording quantization.

    Parameters:
    - value: an int (Live.Song.RecordingQuantization) or a name: none, 1/4, 1/8,
      1/8t, 1/8+1/8t, 1/16, 1/16t, 1/16+1/16t, 1/32.

    Note: confirm via get_transport (song-property-write lag).
    """
    try:
        resolved = resolve_midi_recording_quantization(value)
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "set_midi_recording_quantization", {"value": resolved}
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error setting MIDI recording quantization: {str(e)}")
        return _err(f"Error setting MIDI recording quantization: {str(e)}")
@mcp.tool()
def set_nudge(
    ctx: Context, direction: str, active: Union[bool, int, str]
) -> str:
    """
    Hold or release a tempo-nudge button (temporarily speeds up / slows down to
    re-align with an external source).

    Parameters:
    - direction: "up" or "down"
    - active: true to press/hold, false to release (true/false, on/off, 1/0)

    Note: confirm via get_transport (song-property-write lag).
    """
    try:
        canon = normalize_nudge_direction(direction)
        value = coerce_on_value(active)
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "set_nudge", {"direction": canon, "active": value}
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error setting nudge: {str(e)}")
        return _err(f"Error setting nudge: {str(e)}")
# === Capture & Recording (Phase 11) =======================================

@mcp.tool()
def capture_midi(ctx: Context, destination: str = "auto") -> str:
    """
    Capture recently played MIDI material from audible tracks into a clip
    (Live's "Capture MIDI"). Needs material to capture — check can_capture_midi
    (via get_transport) first.

    Parameters:
    - destination: "auto" (Session or Arrangement depending on the visible view),
      "session", or "arrangement".

    Note: confirm the captured clip via get_session_info / get_clip_info — the
    returned dict can be stale (song-property-write lag). Raises a limitation
    error if capturing into Session would need a new scene that can't be created.
    """
    try:
        name = resolve_capture_destination(destination)
        ableton = get_ableton_connection()
        result = ableton.send_command("capture_midi", {"destination": name})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error capturing MIDI: {str(e)}")
        return _err(f"Error capturing MIDI: {str(e)}")
@mcp.tool()
def capture_and_insert_scene(ctx: Context, mode: str = "all") -> str:
    """
    Capture the currently playing clips and insert them as a new scene after the
    selected scene. Needs clips currently playing.

    Parameters:
    - mode: "all" (the only Live.Song.CaptureMode value).

    Note: confirm the new scene via get_scenes (song-property-write lag). Raises a
    runtime error if creating the scene would exceed Live's limitations.
    """
    try:
        name = resolve_capture_mode(mode)
        ableton = get_ableton_connection()
        result = ableton.send_command("capture_and_insert_scene", {"mode": name})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error capturing scene: {str(e)}")
        return _err(f"Error capturing scene: {str(e)}")
@mcp.tool()
def trigger_session_record(
    ctx: Context, record_length: Union[float, int, str, None] = None
) -> str:
    """
    Trigger a new Session recording (records into armed tracks' clip slots).
    Arming/recording auto-starts playback — stop promptly in tests.

    Parameters:
    - record_length: optional fixed length in beats (> 0). Omit for an
      open-ended recording (Live's default).

    Note: confirm via get_transport (session_record / song-property-write lag).
    """
    try:
        length = coerce_record_length(record_length)
        params = {}
        if length is not None:
            params["record_length"] = length
        ableton = get_ableton_connection()
        result = ableton.send_command("trigger_session_record", params)
        return _ok(result)
    except Exception as e:
        logger.error(f"Error triggering session record: {str(e)}")
        return _err(f"Error triggering session record: {str(e)}")
@mcp.tool()
def stop_all_clips(
    ctx: Context,
    track_index: Optional[int] = None,
    quantized: Union[bool, int, str] = True,
) -> str:
    """
    Stop playing clips. With no track_index, stops all clips in the set while the
    song keeps playing; with track_index, stops only that track's running and
    triggered clips.

    Parameters:
    - track_index: optional 0-based regular-track index. Omit to stop all tracks.
    - quantized: honor global launch quantization (true) or stop immediately
      (false). Default true.
    """
    try:
        params = {"quantized": coerce_on_value(quantized)}
        if track_index is not None:
            params["track_index"] = coerce_track_index(track_index)
        ableton = get_ableton_connection()
        result = ableton.send_command("stop_all_clips", params)
        return _ok(result)
    except Exception as e:
        logger.error(f"Error stopping all clips: {str(e)}")
        return _err(f"Error stopping all clips: {str(e)}")
@mcp.tool()
def tap_tempo(ctx: Context) -> str:
    """
    Trigger Live's tap-tempo (one tap). Call repeatedly in time to set a tempo;
    a single tap nudges the tempo toward the tap interval.

    Note: confirm the resulting tempo via get_transport.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("tap_tempo")
        return _ok(result)
    except Exception as e:
        logger.error(f"Error tapping tempo: {str(e)}")
        return _err(f"Error tapping tempo: {str(e)}")
@mcp.tool()
def continue_playback(ctx: Context) -> str:
    """Resume playback from the current position (unlike start_playback, which
    restarts from the top)."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("continue_playback")
        return _ok("Continued playback")
    except Exception as e:
        logger.error(f"Error continuing playback: {str(e)}")
        return _err(f"Error continuing playback: {str(e)}")
@mcp.tool()
def set_metronome(ctx: Context, on: Union[bool, int, str]) -> str:
    """
    Turn the metronome on or off.

    Parameters:
    - on: true/false, on/off, 1/0
    """
    try:
        value = coerce_on_value(on)
        ableton = get_ableton_connection()
        result = ableton.send_command("set_metronome", {"on": value})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error setting metronome: {str(e)}")
        return _err(f"Error setting metronome: {str(e)}")
@mcp.tool()
def set_arrangement_record(ctx: Context, on: Union[bool, int, str]) -> str:
    """
    Arm or disarm arrangement record (record_mode).

    Parameters:
    - on: true/false, on/off, 1/0
    """
    try:
        value = coerce_on_value(on)
        ableton = get_ableton_connection()
        result = ableton.send_command("set_arrangement_record", {"on": value})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error setting arrangement record: {str(e)}")
        return _err(f"Error setting arrangement record: {str(e)}")
@mcp.tool()
def set_session_record(ctx: Context, on: Union[bool, int, str]) -> str:
    """
    Turn session record on or off.

    Parameters:
    - on: true/false, on/off, 1/0
    """
    try:
        value = coerce_on_value(on)
        ableton = get_ableton_connection()
        result = ableton.send_command("set_session_record", {"on": value})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error setting session record: {str(e)}")
        return _err(f"Error setting session record: {str(e)}")
@mcp.tool()
def set_punch(
    ctx: Context,
    punch_in: Union[bool, int, str] = None,
    punch_out: Union[bool, int, str] = None,
) -> str:
    """
    Set the arrangement punch-in/out flags. Only the parameters you provide are
    changed.

    Parameters:
    - punch_in: true/false, on/off, 1/0 (optional)
    - punch_out: true/false, on/off, 1/0 (optional)
    """
    try:
        fields = coerce_punch_fields(punch_in, punch_out)
        ableton = get_ableton_connection()
        params = {}
        if "punch_in" in fields:
            params["punch_in"] = fields["punch_in"]
        if "punch_out" in fields:
            params["punch_out"] = fields["punch_out"]
        result = ableton.send_command("set_punch", params)
        return _ok(result)
    except Exception as e:
        logger.error(f"Error setting punch: {str(e)}")
        return _err(f"Error setting punch: {str(e)}")
@mcp.tool()
def set_song_position(ctx: Context, time_beats: float) -> str:
    """
    Jump the playhead to an absolute position.

    Parameters:
    - time_beats: Position in beats (must be >= 0)
    """
    try:
        value = coerce_song_time(time_beats)
        ableton = get_ableton_connection()
        result = ableton.send_command("set_song_position", {"time_beats": value})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error setting song position: {str(e)}")
        return _err(f"Error setting song position: {str(e)}")
@mcp.tool()
def jump_by(ctx: Context, beats: float) -> str:
    """
    Nudge the playhead by a relative amount.

    Parameters:
    - beats: Beats to move (negative moves backward)
    """
    try:
        value = coerce_jump_beats(beats)
        ableton = get_ableton_connection()
        result = ableton.send_command("jump_by", {"beats": value})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error jumping by beats: {str(e)}")
        return _err(f"Error jumping by beats: {str(e)}")
# === Arrangement ==========================================================

@mcp.tool()
def get_cue_points(ctx: Context) -> str:
    """List arrangement cue points / locators (index, name, time)."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_cue_points")
        return _ok(result)
    except Exception as e:
        logger.error(f"Error getting cue points: {str(e)}")
        return _err(f"Error getting cue points: {str(e)}")
@mcp.tool()
def set_arrangement_loop(
    ctx: Context,
    enabled: Union[bool, int, str] = None,
    start: float = None,
    length: float = None,
) -> str:
    """
    Configure the arrangement loop brace. Only the parameters you provide are
    changed.

    Parameters:
    - enabled: true/false, on/off, 1/0 (optional)
    - start: Loop start in beats, >= 0 (optional)
    - length: Loop length in beats, > 0 (optional)
    """
    try:
        fields = coerce_loop_fields(enabled, start, length)
        ableton = get_ableton_connection()
        params = {}
        if "enabled" in fields:
            params["enabled"] = fields["enabled"]
        if "start" in fields:
            params["start"] = fields["start"]
        if "length" in fields:
            params["length"] = fields["length"]
        result = ableton.send_command("set_arrangement_loop", params)
        return _ok(result)
    except Exception as e:
        logger.error(f"Error setting arrangement loop: {str(e)}")
        return _err(f"Error setting arrangement loop: {str(e)}")
@mcp.tool()
def jump_to_cue(ctx: Context, direction: str = "next") -> str:
    """
    Jump to the next or previous arrangement cue point.

    Parameters:
    - direction: 'next' or 'prev' (aliases: forward/back accepted)
    """
    try:
        canonical = resolve_cue_direction(direction)
        ableton = get_ableton_connection()
        result = ableton.send_command("jump_to_cue", {"direction": canonical})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error jumping to cue: {str(e)}")
        return _err(f"Error jumping to cue: {str(e)}")
@mcp.tool()
def back_to_arrangement(ctx: Context) -> str:
    """Re-engage the arrangement timeline after launching session clips (clears
    the 'back to arrangement' override)."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("back_to_arrangement")
        return _ok(result)
    except Exception as e:
        logger.error(f"Error returning to arrangement: {str(e)}")
        return _err(f"Error returning to arrangement: {str(e)}")
@mcp.tool()
def re_enable_automation(ctx: Context) -> str:
    """Re-enable automation that was overridden by manual control changes."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("re_enable_automation")
        return _ok(result)
    except Exception as e:
        logger.error(f"Error re-enabling automation: {str(e)}")
        return _err(f"Error re-enabling automation: {str(e)}")
@mcp.tool()
def get_browser_tree(ctx: Context, category_type: str = "all", limit: int = 200) -> str:
    """
    Get the browser category tree from Ableton, flattened to a depth-first node
    list (each node carries its `depth`, so the hierarchy is reconstructable).

    Parameters:
    - category_type: Type of categories to get ('all', 'instruments', 'sounds',
      'drums', 'audio_effects', 'midi_effects')
    - limit: Max nodes to return (default 200). The list is truncated past this
      to stay within size limits; narrow `category_type` or raise `limit`.

    Returns JSON {category_type, total_folders, count, returned, truncated,
    nodes:[{name, path, depth, has_more}, ...]}. `count` is the full total;
    `nodes` holds at most `limit` of them.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_browser_tree", {
            "category_type": category_type
        })

        # Check if we got any categories
        if "available_categories" in result and len(result.get("categories", [])) == 0:
            available_cats = result.get("available_categories", [])
            return _err(f"No categories found for '{category_type}'. "
                   f"Available browser categories: {', '.join(available_cats)}")

        # Flatten the tree depth-first into a node list.
        nodes = []

        def walk(item, depth=0):
            if not item:
                return
            nodes.append({
                "name": item.get("name", "Unknown"),
                "path": item.get("path", ""),
                "depth": depth,
                "has_more": item.get("has_more", False),
            })
            for child in item.get("children", []):
                walk(child, depth + 1)

        for category in result.get("categories", []):
            walk(category)

        total = len(nodes)
        shown = nodes[:limit] if limit and limit > 0 else nodes
        payload = {
            "category_type": category_type,
            "total_folders": result.get("total_folders", 0),
            "count": total,
            "returned": len(shown),
            "truncated": len(shown) < total,
            "nodes": shown,
        }
        return _ok(payload)
    except Exception as e:
        error_msg = str(e)
        if "Browser is not available" in error_msg:
            logger.error(f"Browser is not available in Ableton: {error_msg}")
            return _err(f"Error: The Ableton browser is not available. Make sure Ableton Live is fully loaded and try again.")
        elif "Could not access Live application" in error_msg:
            logger.error(f"Could not access Live application: {error_msg}")
            return _err(f"Error: Could not access the Ableton Live application. Make sure Ableton Live is running and the Remote Script is loaded.")
        else:
            logger.error(f"Error getting browser tree: {error_msg}")
            return _err(f"Error getting browser tree: {error_msg}")
@mcp.tool()
def get_browser_items_at_path(ctx: Context, path: str, limit: int = 200) -> str:
    """
    Get browser items at a specific path in Ableton's browser.

    Parameters:
    - path: Path in the format "category/folder/subfolder"
            where category is one of the available browser categories in Ableton
    - limit: Max items to return (default 200). The list is truncated past this
            to stay within size limits; narrow `path` or raise `limit` for more.

    Returns JSON {path, count, returned, truncated, items:[...]} (plus any other
    fields Live returns). `count` is the full total; `items` holds at most `limit`.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_browser_items_at_path", {
            "path": path
        })

        # Check if there was an error with available categories
        if "error" in result and "available_categories" in result:
            error = result.get("error", "")
            available_cats = result.get("available_categories", [])
            return _err(f"Error: {error}\n"
                   f"Available browser categories: {', '.join(available_cats)}")

        items = result.get("items", [])
        total = result.get("count", len(items))
        shown = items[:limit] if limit and limit > 0 else items
        result["count"] = total
        result["returned"] = len(shown)
        result["truncated"] = len(shown) < total
        result["items"] = shown
        return _ok(result)
    except Exception as e:
        error_msg = str(e)
        if "Browser is not available" in error_msg:
            logger.error(f"Browser is not available in Ableton: {error_msg}")
            return _err(f"Error: The Ableton browser is not available. Make sure Ableton Live is fully loaded and try again.")
        elif "Could not access Live application" in error_msg:
            logger.error(f"Could not access Live application: {error_msg}")
            return _err(f"Error: Could not access the Ableton Live application. Make sure Ableton Live is running and the Remote Script is loaded.")
        elif "Unknown or unavailable category" in error_msg:
            logger.error(f"Invalid browser category: {error_msg}")
            return _err(f"Error: {error_msg}. Please check the available categories using get_browser_tree.")
        elif "Path part" in error_msg and "not found" in error_msg:
            logger.error(f"Path not found: {error_msg}")
            return _err(f"Error: {error_msg}. Please check the path and try again.")
        else:
            logger.error(f"Error getting browser items at path: {error_msg}")
            return _err(f"Error getting browser items at path: {error_msg}")
@mcp.tool()
def load_drum_kit(ctx: Context, track_index: int, rack_uri: str, kit_path: str) -> str:
    """
    Load a drum rack and then load a specific drum kit into it.
    
    Parameters:
    - track_index: The index of the track to load on
    - rack_uri: The URI of the drum rack to load (e.g., 'Drums/Drum Rack')
    - kit_path: Path to the drum kit inside the browser (e.g., 'drums/acoustic/kit1')
    """
    try:
        ableton = get_ableton_connection()
        
        # Step 1: Load the drum rack
        result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": rack_uri
        })
        
        if not result.get("loaded", False):
            return _err(f"Failed to load drum rack with URI '{rack_uri}'")
        # Step 2: Get the drum kit items at the specified path
        kit_result = ableton.send_command("get_browser_items_at_path", {
            "path": kit_path
        })
        
        if "error" in kit_result:
            return _err(f"Loaded drum rack but failed to find drum kit: {kit_result.get('error')}")
        
        # Step 3: Find a loadable drum kit
        kit_items = kit_result.get("items", [])
        loadable_kits = [item for item in kit_items if item.get("is_loadable", False)]
        
        if not loadable_kits:
            return _err(f"Loaded drum rack but no loadable drum kits found at '{kit_path}'")
        
        # Step 4: Load the first loadable kit
        kit_uri = loadable_kits[0].get("uri")
        load_result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": kit_uri
        })
        
        return _ok(f"Loaded drum rack and kit '{loadable_kits[0].get('name')}' on track {track_index}")
    except Exception as e:
        logger.error(f"Error loading drum kit: {str(e)}")
        return _err(f"Error loading drum kit: {str(e)}")
@mcp.tool()
def list_device_presets(ctx: Context, path: str, max_depth: int = 6,
                        limit: int = 100) -> str:
    """
    Recursively list loadable presets under a browser path.

    Use this to discover presets for a device/category without knowing their
    cryptic URIs, then load one with load_preset (pass a preset's `name` or its
    `relative_path` — load_preset searches subfolders, so either works).

    Parameters:
    - path: Browser path like 'instruments/Wavetable' or 'audio_effects/Reverb'
            (same grammar as get_browser_items_at_path; category is one of
            instruments, sounds, drums, audio_effects, midi_effects).
    - max_depth: How many levels of subfolders to descend (default 6).
    - limit: Max presets to return (default 100). Factory devices can expose
            hundreds; the result is truncated past this to stay within size
            limits — narrow `path` to a subfolder or raise `limit` for more.

    Returns JSON {path, count, returned, truncated, presets:[{name,
    relative_path, uri}, ...]}. `count` is the full total; `presets` holds at
    most `limit` of them.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_browser_presets", {
            "path": path,
            "max_depth": max_depth,
        })
        if "error" in result and "available_categories" in result:
            error = result.get("error", "")
            available_cats = result.get("available_categories", [])
            return _err(f"Error: {error}\n"
                   f"Available browser categories: {', '.join(available_cats)}")
        if "error" in result:
            return _err(f"Error: {result.get('error')}")
        presets = result.get("presets", [])
        total = result.get("count", len(presets))
        shown = presets[:limit] if limit and limit > 0 else presets
        truncated = len(shown) < total
        payload = {
            "path": result.get("path", path),
            "count": total,
            "returned": len(shown),
            "truncated": truncated,
            "presets": shown,
        }
        if truncated:
            payload["note"] = (f"Showing first {len(shown)} of {total} presets. "
                               f"Narrow `path` to a subfolder or raise `limit` to "
                               f"see the rest.")
        return _ok(payload)
    except Exception as e:
        logger.error(f"Error listing device presets: {str(e)}")
        return _err(f"Error listing device presets: {str(e)}")
@mcp.tool()
def load_preset(ctx: Context, track_index: int, path: str, name: str = None, track_type: str = "regular") -> str:
    """
    Load a preset onto a track by readable name/path (no URI required).

    Works for any loadable browser item, including instrument/effect presets
    (.adv) and rack/group presets (.adg). Loading onto a track that already
    holds an instrument HOT-SWAPS (replaces) it, matching Live's behavior.

    Parameters:
    - track_index: The index of the track to load onto (ignored for master).
    - path: If `name` is given, the folder to search (e.g.
            'instruments/Wavetable') — subfolders are searched recursively. If
            `name` is omitted, the full path to a single preset (e.g.
            'instruments/Wavetable/Ambient & Evolving/Dark Swarm.adg').
    - name: Optional preset name OR relative_path (as shown by
            list_device_presets) to match under `path`. Matched exact, then
            case-insensitive, then unique substring, across name and
            relative_path. Note factory preset names include their file
            extension (e.g. 'Dark Swarm.adg').
    - track_type: 'regular' (default), 'return', or 'master'. Only audio
            effects are valid on return/master tracks.

    Tip: run list_device_presets first, then pass a preset's `name` or
    `relative_path` here (it resolves nested presets, so either works).
    """
    try:
        ableton = get_ableton_connection()

        if name is None:
            folder, leaf = split_preset_path(path)
        else:
            folder, leaf = path, name

        # Resolve recursively so a leaf surfaced by list_device_presets loads
        # even when it lives in a subfolder under `folder`.
        presets_result = ableton.send_command("get_browser_presets", {
            "path": folder,
        })
        if "error" in presets_result:
            available_cats = presets_result.get("available_categories")
            if available_cats:
                return _err(f"Error: {presets_result.get('error')}\n"
                       f"Available browser categories: {', '.join(available_cats)}")
            return _err(f"Error: {presets_result.get('error')}")
        presets = presets_result.get("presets", [])
        chosen = match_recursive_preset(presets, leaf)
        uri = chosen.get("uri")
        if not uri:
            return _err(f"Preset '{chosen.get('name')}' has no loadable URI.")

        label = chosen.get("relative_path") or chosen.get("name")
        load_result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": uri,
            "track_type": track_type,
        })
        if load_result.get("loaded", False):
            return _ok(f"Loaded preset '{label}' (uri '{uri}') "
                   f"on {track_type} track {track_index}.")
        return _err(f"Failed to load preset '{label}' (uri '{uri}').")
    except ValueError as e:
        # match_recursive_preset / split_preset_path failures (clean messages).
        return _err(f"Error: {str(e)}")
    except Exception as e:
        logger.error(f"Error loading preset: {str(e)}")
        return _err(f"Error loading preset: {str(e)}")
# --- Preset-patch infrastructure (device-agnostic) ----------------------
# The LOM only exposes a device's automatable parameters; choosers, file refs,
# and structural state live only in the preset XML. These helpers patch a
# known-good factory preset, write it into the User Library, and load it
# through the normal browser path. Per-device XML logic lives in *_utils
# modules (see preset_patch + wavetable_preset_utils).
#
# Index note: Live only sees a brand-new preset file after it re-indexes the
# User Library (on launch / browser refresh). Once a filename is indexed,
# overwriting it and reloading reads fresh — no re-index needed.

# Multi-version glob fallback: matches any installed Live bundle's Core Library.
# hits[0] is alphabetical = Live 11 when both 11 and 12 are installed (the safer
# cross-version source — Live upgrades older preset schemas on load).
_APP_CORE = ("/Applications/Ableton*Live*.app/Contents/App-Resources/"
             "Core Library")
_FACTORY_TABLE_CACHE = None


def _running_live_major():
    """Major version of the Live the host is talking to (via the Remote Script's
    get_application_version), or None if it can't be resolved."""
    try:
        info = get_ableton_connection().send_command("get_application_version")
        return int(info.get("major"))
    except Exception:
        return None


def _core_for_major(major):
    """Core Library path of an installed Live with the given major version, or
    None. Seam so _app_core is unit-testable without real .app bundles."""
    hits = sorted(glob.glob(
        "/Applications/Ableton*Live*%d*.app/Contents/App-Resources/Core Library"
        % major))
    return hits[0] if hits else None


def _app_core():
    """Core Library of the RUNNING Live, so factory-asset reads (presets, the
    wavetable table list, factory racks) match the version the user is actually
    using when several Live versions are installed. Falls back to the
    multi-version glob (_APP_CORE) when the running version can't be resolved or
    its bundle isn't found. Not cached: stays correct if Live versions switch
    mid-session, at the cost of one tiny socket read per asset lookup."""
    major = _running_live_major()
    if major is not None:
        core = _core_for_major(major)
        if core:
            return core
    return _APP_CORE


def _factory_default_adv(filename, category="Instruments"):
    """Path to a factory-default preset (e.g. 'Wavetable.adv'), or raise."""
    hits = glob.glob("%s/Defaults/%s/%s" % (_app_core(), category, filename))
    if not hits:
        raise FileNotFoundError(
            "Factory default %s/%s not found under /Applications/Ableton*.app. "
            "Is Ableton Live (11 or 12) Suite installed?" % (category, filename)
        )
    return hits[0]


def _read_default_adv(filename, category="Instruments"):
    """Decompressed XML of a factory-default preset."""
    with gzip.open(_factory_default_adv(filename, category), "rt") as f:
        return f.read()


def _user_library_dir():
    """Resolve Live's configured User Library directory.

    Reads the actual <UserLibrary> project path from the newest Live
    preferences' Library.cfg (NOT a UserFolderInfo "Place", which is a
    different folder and was being matched by mistake). The library content
    lives under <ProjectPath>/User Library on some installs and directly under
    <ProjectPath> on others, so prefer whichever holds a Presets/ tree. Falls
    back to ~/Music/Ableton/User Library.
    """
    cfgs = sorted(
        glob.glob(os.path.expanduser(
            "~/Library/Preferences/Ableton/Live */Library.cfg")),
        key=lambda p: os.path.getmtime(p), reverse=True,
    )
    for cfg in cfgs:
        try:
            with open(cfg, "rb") as f:
                blob = f.read().decode("latin-1", "ignore")
        except OSError:
            continue
        u = blob.find("<UserLibrary>")
        if u < 0:
            continue
        m = re.search(r'<ProjectPath Value="([^"]*)"', blob[u:u + 600])
        if not m:
            continue
        base = m.group(1)
        for cand in (os.path.join(base, "User Library"), base):
            if os.path.isdir(os.path.join(cand, "Presets")):
                return cand
    return os.path.expanduser("~/Music/Ableton/User Library")


def _write_user_preset(xml, name, device_folder, category="Instruments",
                       ext="adv"):
    """Gzip-write `xml` to <UserLib>/Presets/<category>/<device_folder>/<name>.<ext>.

    Returns (dest_path, browser_path) where browser_path is the get_browser_*
    path for loading.
    """
    lib = _user_library_dir()
    dest_dir = os.path.join(lib, "Presets", category, device_folder)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "%s.%s" % (name, ext))
    with gzip.open(dest, "wt") as f:
        f.write(xml)
    browser_path = "user_library/Presets/%s/%s" % (category, device_folder)
    return dest, browser_path


def _load_user_preset(track_index, browser_path, name, ext="adv"):
    """Load a just-written User Library preset onto a track.

    Returns (loaded: bool, note: str|None). Distinguishes "not indexed yet"
    (ValueError from the matcher) from an outright load failure, so callers can
    surface the right guidance.
    """
    try:
        ableton = get_ableton_connection()
        presets_result = ableton.send_command("get_browser_presets", {
            "path": browser_path,
        })
        presets = (presets_result.get("presets", [])
                   if isinstance(presets_result, dict) else [])
        try:
            chosen = match_recursive_preset(presets, "%s.%s" % (name, ext))
        except ValueError:
            chosen = match_recursive_preset(presets, name)
        load_result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": chosen.get("uri"),
        })
        if load_result.get("loaded", False):
            return True, None
        return False, ("Preset written but load_browser_item did not confirm "
                       "loading onto track %s." % track_index)
    except ValueError:
        return False, (
            "Preset written, but Live's browser has not indexed it yet so it "
            "can't be loaded onto track %s. Refresh the browser (right-click "
            "User Library -> Refresh) or relaunch Live, then call load_preset "
            "with path '%s' name '%s'. (Re-running this tool after indexing "
            "loads it directly.)" % (track_index, browser_path, name)
        )
    except Exception as le:
        return False, "Preset written, but loading failed: %s" % le


def _read_user_preset(category, device_folder, name, ext="adg"):
    """Read + gunzip an existing User Library preset to XML (the pipeline's read
    side). Raises FileNotFoundError if it's not there yet.
    """
    lib = _user_library_dir()
    path = os.path.join(lib, "Presets", category, device_folder, "%s.%s" % (name, ext))
    if not os.path.isfile(path):
        raise FileNotFoundError(
            "User Library preset not found: %s. Run clone_rack first." % path)
    with gzip.open(path, "rt") as f:
        return f.read(), path


def _read_rack_template(template):
    """Read + gunzip a rack .adg template to XML.

    Resolves `template` two ways:
      (a) an absolute path or glob to a factory rack (e.g. under Core Library/
          Racks/...) — NOT Defaults/, so _read_default_adv does not apply;
      (b) a bare name of a rack already in the User Library (searched across all
          rack device-folders).
    Returns (xml, resolved_path). Raises FileNotFoundError if unresolved.
    """
    expanded = os.path.expanduser(str(template))
    # (a) direct path / glob
    if os.path.sep in expanded or "*" in expanded:
        hits = glob.glob(expanded)
        if hits:
            with gzip.open(hits[0], "rt") as f:
                return f.read(), hits[0]
        if os.path.sep in expanded and "*" not in expanded:
            raise FileNotFoundError("Rack file not found: %s" % expanded)
    # (b) factory rack by name under any Racks/<kind>/<sub>/<name>.adg
    name = os.path.splitext(os.path.basename(expanded))[0]
    hits = glob.glob(
        "%s/Racks/**/%s.adg" % (_app_core(), glob.escape(name)), recursive=True
    )
    if hits:
        with gzip.open(hits[0], "rt") as f:
            return f.read(), hits[0]
    # (c) user-library rack by name across rack device-folders
    lib = _user_library_dir()
    hits = glob.glob(
        os.path.join(
            glob.escape(lib), "Presets", "*", "*", "%s.adg" % glob.escape(name)
        )
    )
    if hits:
        with gzip.open(hits[0], "rt") as f:
            return f.read(), hits[0]
    raise FileNotFoundError(
        "Rack template %r not found as a path, a factory rack name, or a User "
        "Library preset name." % (template,))


def _scan_factory_tables(limit=400):
    """Return sorted unique factory wavetable names (SpriteName values)."""
    global _FACTORY_TABLE_CACHE
    if _FACTORY_TABLE_CACHE is not None:
        return _FACTORY_TABLE_CACHE
    names = set()
    files = glob.glob(
        "%s/Devices/Instruments/Wavetable/**/*.adv" % _app_core(), recursive=True
    )[:limit]
    for path in files:
        try:
            with gzip.open(path, "rt") as f:
                xml = f.read()
        except OSError:
            continue
        for m in re.findall(r'<SpriteName[12] Value="([^"]*)" />', xml):
            names.add(m)
    _FACTORY_TABLE_CACHE = sorted(names)
    return _FACTORY_TABLE_CACHE


@mcp.tool()
def list_wavetable_tables(ctx: Context) -> str:
    """
    List the factory Wavetable oscillator tables available by name, plus the
    unison-mode legend — the inputs for create_wavetable_preset.

    The oscillator wavetable selection, unison mode, and unison voice count are
    NOT in Wavetable's automatable parameter list, so they can't be set with
    set_device_parameter. create_wavetable_preset reaches them by writing a
    preset; this tool tells you the valid table names to pass it.

    Returns JSON {count, tables:[...], unison_modes:{name:int}, voices:[min,max]}.
    """
    try:
        tables = _scan_factory_tables()
        from ableton_mcp_max.wavetable_preset_utils import (
            UNISON_MODES, MIN_VOICES, MAX_VOICES,
        )
        payload = {
            "count": len(tables),
            "tables": tables,
            "unison_modes": UNISON_MODES,
            "voices": [MIN_VOICES, MAX_VOICES],
        }
        return _ok(payload)
    except Exception as e:
        logger.error(f"Error listing wavetable tables: {str(e)}")
        return _err(f"Error listing wavetable tables: {str(e)}")
@mcp.tool()
def create_wavetable_preset(ctx: Context, name: str, table1: str,
                            table2: str = None, unison_mode: str = "classic",
                            voices: int = 7, amount: float = 0.85,
                            osc1_pos: float = None, osc2_pos: float = None,
                            osc2_on: bool = True,
                            track_index: int = None) -> str:
    """
    Generate a Wavetable preset (.adv) in the User Library and optionally load it.

    This is the ONLY way to set Wavetable's oscillator table selection, unison
    mode, and unison voice count via MCP — those controls are absent from the
    automatable parameter API. The preset is built by patching Live's factory
    default, so everything else stays at default and the automatable params
    (osc detune/pos, unison amount, filter, envelopes) remain tweakable
    afterwards with set_device_parameter.

    Parameters
    - name: preset name (becomes '<name>.adv' under User Library; no slashes).
    - table1: factory wavetable for Osc 1 (see list_wavetable_tables, e.g.
            'Basic Shapes', 'Quad Saw', 'Logue Saw').
    - table2: factory wavetable for Osc 2 (defaults to table1).
    - unison_mode: name or int 0..6 — None, Classic (supersaw), Shimmer, Noise,
            Phase Sync, Position Spread, Random Note. Default 'classic'.
    - voices: unison voice count 2..8 (default 7).
    - amount: unison amount 0.0..1.0 (default 0.85).
    - osc1_pos / osc2_pos: optional wave position 0.0..1.0 (left at default if omitted).
    - osc2_on: enable Osc 2 (default True, for a 2-osc supersaw).
    - track_index: if given, attempt to load the new preset onto that track.

    Loading note: Live only sees a brand-new preset file after it re-indexes
    the User Library (on launch, or a browser refresh) — so a first-time load
    may report "written but not yet loadable". Once the name is indexed,
    re-running this tool overwrites the same file and loads fresh immediately.

    Returns JSON {written, path, settings, loaded, note}.
    """
    try:
        safe = validate_preset_name(name)
        # build_wavetable_adv validates inputs and raises ValueError on bad ones.
        xml = build_wavetable_adv(
            _read_default_adv("Wavetable.adv"), table1=table1, table2=table2,
            unison_mode=unison_mode, voices=voices, amount=amount,
            osc1_pos=osc1_pos, osc2_pos=osc2_pos, osc2_on=osc2_on, name=safe,
        )
        dest, browser_path = _write_user_preset(xml, safe, "Wavetable")

        loaded, note = False, None
        if track_index is not None:
            loaded, note = _load_user_preset(track_index, browser_path, safe)

        return _ok({
            "written": True,
            "path": dest,
            "settings": summarize_wavetable_adv(xml),
            "loaded": loaded,
            "note": note,
        })
    except (ValueError, FileNotFoundError) as e:
        return _err(f"Error: {str(e)}")
    except Exception as e:
        logger.error(f"Error creating wavetable preset: {str(e)}")
        return _err(f"Error creating wavetable preset: {str(e)}")
def _read_audio_meta(path):
    """Return (file_size_bytes, frames, sample_rate) for an audio file.

    Reads frame count + sample rate from WAV/AIFF headers (stdlib). For other
    formats frames/rate come back 0 (the caller should reject, since a 0-length
    sample region won't play). Raises FileNotFoundError if the path is missing.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError("sample not found: %s" % path)
    size = os.path.getsize(path)
    ext = os.path.splitext(path)[1].lower()
    frames, rate = 0, 0
    try:
        if ext == ".wav":
            import wave
            with wave.open(path, "rb") as w:
                frames, rate = w.getnframes(), w.getframerate()
        elif ext in (".aif", ".aiff", ".aifc"):
            import aifc
            with aifc.open(path, "rb") as a:
                frames, rate = a.getnframes(), int(a.getframerate())
    except Exception as e:
        logger.warning("could not read audio header for %s: %s", path, e)
        frames, rate = 0, 0
    return size, frames, rate


@mcp.tool()
def create_simpler_instrument(ctx: Context, name: str, sample_path: str,
                              root_key: int = 60,
                              track_index: int = None) -> str:
    """
    Create a Simpler preset that loads a chosen audio file, and optionally load it.

    The sample a Simpler plays is NOT in Live's automatable parameter API, so a
    preset is the only way to set it via MCP. This writes a Simpler .adv into
    the User Library referencing `sample_path` (Live relinks + recomputes on
    load). Everything else about Simpler (filter type, ADSR, LFO, warp via the
    UI) is automatable afterwards with set_device_parameter.

    Parameters
    - name: preset name (becomes '<name>.adv' under User Library; no slashes).
    - sample_path: absolute path to a .wav or .aif/.aiff file. Other formats are
            rejected (their frame count can't be read, which would yield a
            silent zero-length sample) — convert to WAV/AIFF first.
    - root_key: MIDI note the sample plays at unpitched (default 60 = C3).
    - track_index: if given, load the new preset onto that track.

    Returns JSON {written, path, sample, frames, sample_rate, loaded, note}.
    """
    try:
        safe = validate_preset_name(name)
        sample_path = os.path.expanduser(str(sample_path))
        size, frames, rate = _read_audio_meta(sample_path)
        if frames <= 0:
            return _err("Error: could not read a frame count for %r. Only .wav and "
                    ".aif/.aiff are supported (other formats would load as a "
                    "silent, zero-length sample). Convert to WAV/AIFF first."
                    % os.path.basename(sample_path))

        xml = build_simpler_adv(
            _read_default_adv("Simpler.adv"), sample_path=sample_path,
            file_size=size, frames=frames, sample_rate=rate, name=safe,
            root_key=root_key, relative_path=os.path.basename(sample_path),
            relative_path_type=0,
        )
        dest, browser_path = _write_user_preset(xml, safe, "Simpler")

        loaded, note = False, None
        if track_index is not None:
            loaded, note = _load_user_preset(track_index, browser_path, safe)

        return _ok({
            "written": True,
            "path": dest,
            "sample": sample_path,
            "frames": frames,
            "sample_rate": rate,
            "loaded": loaded,
            "note": note,
        })
    except (ValueError, FileNotFoundError) as e:
        return _err(f"Error: {str(e)}")
    except Exception as e:
        logger.error(f"Error creating simpler instrument: {str(e)}")
        return _err(f"Error creating simpler instrument: {str(e)}")
@mcp.tool()
def inspect_rack_preset(ctx: Context, template: str) -> str:
    """
    Inspect a rack preset (.adg) and report its macros and chain zones.

    Reads a rack by path (a factory rack under Core Library/Racks/...) or by
    name (a factory rack name, or a preset already in your User Library) and
    returns its structure — the inputs you need for rename_rack_macros and
    set_rack_zones. Reads only; nothing is written or loaded.

    Macros are reported 1-based (matching set_rack_macro); chains 0-based
    (matching get_rack_chains). key_zone/velocity_zone are null on audio-effect
    and midi-effect racks (those chains have only a chain_selector_zone).

    Parameters:
    - template: a .adg path/glob, OR a factory/User-Library rack name.

    Returns JSON {rack_type, num_visible_macros, macros:[...16...], chains:[...]}.
    """
    try:
        xml, path = _read_rack_template(template)
        summary = summarize_rack_adg(xml)
        summary["template_path"] = path
        return _ok(summary)
    except (ValueError, FileNotFoundError) as e:
        return _err(f"Error: {str(e)}")
    except Exception as e:
        logger.error(f"Error inspecting rack preset: {str(e)}")
        return _err(f"Error inspecting rack preset: {str(e)}")
@mcp.tool()
def clone_rack(ctx: Context, template: str, name: str) -> str:
    """
    Copy a rack preset into your User Library as a new working preset.

    Racks have no blank/default template, so the rack-preset pipeline starts by
    cloning an existing rack (factory or User Library). The clone becomes the
    working preset that rename_rack_macros / set_rack_zones edit in place; load
    the finished result later with load_preset using the returned browser_path.

    The User Library category and device-folder are derived from the rack type
    (instrument -> Instruments/Instrument Rack, audio_effect -> Audio Effects/
    Audio Effect Rack, midi_effect -> MIDI Effects/MIDI Effect Rack, drum ->
    Drums/Drum Rack).

    Parameters:
    - template: source rack — a .adg path/glob, or a factory/User-Library name.
    - name: new preset name (becomes '<name>.adg'; no slashes or leading dot).

    Returns JSON {written, path, browser_path, summary:{...inspect shape...}}.
    """
    try:
        safe = validate_preset_name(name)
        xml, _src = _read_rack_template(template)
        kind = detect_rack_type(xml)
        meta = RACK_TYPES[kind]
        dest, browser_path = _write_user_preset(
            xml, safe, meta["device_folder"], category=meta["category"], ext="adg")
        return _ok({
            "written": True,
            "path": dest,
            "browser_path": browser_path,
            "summary": summarize_rack_adg(xml),
        })
    except (ValueError, FileNotFoundError) as e:
        return _err(f"Error: {str(e)}")
    except Exception as e:
        logger.error(f"Error cloning rack: {str(e)}")
        return _err(f"Error cloning rack: {str(e)}")
def _user_rack_category(name):
    """Find which rack device-folder a User Library rack <name>.adg lives in.

    Returns (category, device_folder, xml). Raises FileNotFoundError if absent.
    """
    for kind, meta in RACK_TYPES.items():
        try:
            xml, _path = _read_user_preset(
                meta["category"], meta["device_folder"], name, ext="adg")
            return meta["category"], meta["device_folder"], xml
        except FileNotFoundError:
            continue
    raise FileNotFoundError(
        "No User Library rack named %r in any rack folder. Run clone_rack first."
        % name)


@mcp.tool()
def rename_rack_macros(ctx: Context, name: str, macro_names: dict = None,
                       macro_colors: dict = None,
                       macro_defaults: dict = None) -> str:
    """
    Rename / recolor / set defaults for a User Library rack's macros, in place.

    Operates on a rack preset previously created by clone_rack (the working
    preset). Only the macros you list are changed; the rest keep their values.
    Macro display names are NOT settable via the LOM — this preset edit is the
    only MCP route. Macros are addressed 1-based (matching set_rack_macro).

    Parameters:
    - name: the User Library rack preset name (from clone_rack).
    - macro_names: object {macro_number: "Display Name"} (no double-quote).
    - macro_colors: object {macro_number: color_int} (-1..69; -1 = no color).
    - macro_defaults: object {macro_number: default_float} (0..127).

    The file is overwritten in place, so it reloads fresh with load_preset
    without re-indexing. Returns JSON {written, path, macros:[...16...]}.
    """
    try:
        safe = validate_preset_name(name)
        category, device_folder, xml = _user_rack_category(safe)
        names = {int(k): v for k, v in (macro_names or {}).items()}
        colors = {int(k): v for k, v in (macro_colors or {}).items()}
        defaults = {int(k): v for k, v in (macro_defaults or {}).items()}
        out = patch_macros(xml, names=names, colors=colors, defaults=defaults)
        dest, _bp = _write_user_preset(
            out, safe, device_folder, category=category, ext="adg")
        return _ok({
            "written": True, "path": dest,
            "macros": summarize_rack_adg(out)["macros"],
        })
    except (ValueError, FileNotFoundError) as e:
        return _err(f"Error: {str(e)}")
    except Exception as e:
        logger.error(f"Error renaming rack macros: {str(e)}")
        return _err(f"Error renaming rack macros: {str(e)}")
@mcp.tool()
def set_rack_zones(ctx: Context, name: str, zones: list) -> str:
    """
    Set chain key / velocity / chain-selector zones on a User Library rack.

    Operates in place on a rack created by clone_rack. Chain zones are not
    settable via the LOM — this preset edit is the only MCP route. Chains are
    addressed 0-based (matching get_rack_chains). key and velocity are rejected
    for audio-effect / midi-effect racks (those chains only have a
    chain_selector zone).

    Each entry in `zones` is an object:
      {"chain": 0,
       "key": [0, 60]                 // shorthand [min,max], OR a full object:
       "velocity": {"min":0,"max":127,"crossfade_min":0,"crossfade_max":127},
       "chain_selector": [0, 63]}
    Provide only the zones you want to change. Validation enforces 0..127 and
    min <= crossfade_min <= crossfade_max <= max.

    Returns JSON {written, path, chains:[...]}.
    """
    try:
        safe = validate_preset_name(name)
        category, device_folder, xml = _user_rack_category(safe)
        kind = detect_rack_type(xml)
        if not isinstance(zones, list):
            return _err("Error: zones must be a list of {chain, key?, velocity?, chain_selector?} objects.")
        out = xml
        for entry in zones:
            if not isinstance(entry, dict) or "chain" not in entry:
                return _err("Error: each zones entry needs a 'chain' index.")
            ci = int(entry["chain"])
            for zone_key in ("key", "velocity", "chain_selector"):
                if zone_key in entry and entry[zone_key] is not None:
                    out = patch_chain_zone(out, kind, ci, zone_key, entry[zone_key])
        dest, _bp = _write_user_preset(
            out, safe, device_folder, category=category, ext="adg")
        return _ok({
            "written": True, "path": dest,
            "chains": summarize_rack_adg(out)["chains"],
        })
    except (ValueError, FileNotFoundError) as e:
        return _err(f"Error: {str(e)}")
    except Exception as e:
        logger.error(f"Error setting rack zones: {str(e)}")
        return _err(f"Error setting rack zones: {str(e)}")
@mcp.tool()
def add_rack_macro_mappings(ctx: Context, name: str, mappings: list) -> str:
    """
    Map rack macros to device parameters on a User Library rack, in place.

    Macro->parameter mappings are NOT settable via the LOM — this preset edit is
    the only MCP route. Operates on a rack created by clone_rack (the working
    preset). Macros are addressed 1-based (matching set_rack_macro); chains
    0-based (matching get_rack_chains).

    Each entry in `mappings` is an object:
      {"macro": 1, "chain": 0, "device": 0, "parameter": "Gain"}
    - macro: 1..16 macro number.
    - parameter: the parameter's XML tag name within the device (e.g. "Gain",
            "Volume"). Use inspect-style trial or Live's device to find tag names;
            an invalid name returns an error listing the device's available tags.
    - device address — either the flat single-level form:
        - chain: 0-based chain index.
        - device: 0-based device index within that chain.
      OR, to target a parameter inside a NESTED rack-in-rack, a "path" array of
      {chain, device} steps that descend one rack level each (the nested rack's
      type is auto-detected and may differ from the outer rack's). The flat form
      is equivalent to a one-step path. Example (chain 0 -> device 1 is a rack ->
      its chain 0 -> device 0):
        {"macro": 1,
         "path": [{"chain": 0, "device": 1}, {"chain": 0, "device": 0}],
         "parameter": "Frequency"}
      Supplying both "path" and flat chain/device is rejected as ambiguous.
    - range (optional): {"min": <float>, "max": <float>} to make the macro sweep a
            SUB-range of the parameter instead of its full range. min/max are in
            the parameter's NATIVE units (the same units as get_device_parameters'
            min/max/value — e.g. linear amplitude, Hz, dB), NOT 0..127. Setting
            min > max INVERTS the mapping (macro-up drives the param down). Omit
            for the default full-range mapping.

    Mappings are default full-range unless `range` is given. Re-mapping a
    parameter replaces its existing mapping; several parameters may share one
    macro. Load the result with load_preset, then verify by moving the macro
    (set_rack_macro) and reading the device parameter.

    Returns JSON {written, path, mappings:[...]}.
    """
    try:
        safe = validate_preset_name(name)
        if not isinstance(mappings, list) or not mappings:
            return _err("Error: mappings must be a non-empty list of {macro, chain, device, parameter} objects.")
        category, device_folder, xml = _user_rack_category(safe)
        kind = detect_rack_type(xml)
        out = patch_macro_mappings(xml, kind, mappings)
        dest, _bp = _write_user_preset(
            out, safe, device_folder, category=category, ext="adg")
        return _ok({
            "written": True, "path": dest, "mappings": mappings,
        })
    except (ValueError, FileNotFoundError) as e:
        return _err(f"Error: {str(e)}")
    except Exception as e:
        logger.error(f"Error adding rack macro mappings: {str(e)}")
        return _err(f"Error adding rack macro mappings: {str(e)}")
@mcp.tool()
def create_cue_point(ctx: Context, time: float) -> str:
    """
    Create a cue point (locator) on the Arrangement at the given time.

    Live's only cue API toggles a marker at the playhead, and playhead writes
    settle asynchronously, so this is orchestrated as separate commands: read
    the current playhead, move it to `time`, toggle a cue there, then restore
    the playhead. No-ops (created=false) if a cue already exists at `time`, so
    it never removes an existing marker. Verify the actual time (Live may snap
    to the grid) with get_cue_points.

    Parameters:
    - time: Position in beats (>= 0).
    """
    try:
        value = coerce_time(time)
        ableton = get_ableton_connection()
        # Capture the current playhead (settled read) so we can restore it.
        transport = ableton.send_command("get_transport", {})
        original = transport.get("current_song_time", 0.0)
        # Move the playhead (separate command → settles before the toggle).
        ableton.send_command("set_song_position", {"time_beats": value})
        result = ableton.send_command("create_cue_at_playhead", {})
        # Restore the playhead.
        ableton.send_command("set_song_position", {"time_beats": original})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error creating cue point: {str(e)}")
        return _err(f"Error creating cue point: {str(e)}")
@mcp.tool()
def delete_cue_point(ctx: Context, cue_index: int = None, index: int = None) -> str:
    """
    Delete a cue point (locator) by its index (as listed by get_cue_points).

    Orchestrated as separate commands (same reason as create_cue_point): look
    up the cue's time, move the playhead there, toggle it off, restore the
    playhead.

    Parameters:
    - cue_index: Index into the ordered cue-point list (>= 0). (`index` is
      accepted as a legacy alias.)
    """
    try:
        idx = coerce_index(_resolve_index(cue_index, index, label="cue_index"))
        ableton = get_ableton_connection()
        cues = ableton.send_command("get_cue_points", {})
        cue_list = cues.get("cue_points", [])
        if idx >= len(cue_list):
            n = len(cue_list)
            return _err("Error: Cue index out of range (0..%d)" % (n - 1)
                    if n else "Error: No cue points to delete")
        target_time = cue_list[idx]["time"]
        transport = ableton.send_command("get_transport", {})
        original = transport.get("current_song_time", 0.0)
        ableton.send_command("set_song_position", {"time_beats": target_time})
        result = ableton.send_command("delete_cue_at_playhead", {})
        ableton.send_command("set_song_position", {"time_beats": original})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error deleting cue point: {str(e)}")
        return _err(f"Error deleting cue point: {str(e)}")
@mcp.tool()
def get_arrangement_clips(ctx: Context, track_index: int, limit: int = 200) -> str:
    """
    List the clips on a track's Arrangement timeline.

    Parameters:
    - track_index: Index of the track.
    - limit: Max clips to return (default 200). The list is truncated past this
      to stay within size limits; raise `limit` for more.

    Returns JSON {track_index, count, returned, truncated, clips:[{index, name,
    start_time, end_time, length, is_midi_clip}, ...]}. `count` is the full
    total; `clips` holds at most `limit` of them.
    """
    try:
        idx = coerce_index(track_index)
        ableton = get_ableton_connection()
        result = ableton.send_command("get_arrangement_clips", {
            "track_index": idx,
        })
        clips = result.get("clips", [])
        total = result.get("count", len(clips))
        shown = clips[:limit] if limit and limit > 0 else clips
        payload = {
            "track_index": result.get("track_index", idx),
            "count": total,
            "returned": len(shown),
            "truncated": len(shown) < total,
            "clips": shown,
        }
        return _ok(payload)
    except Exception as e:
        logger.error(f"Error getting arrangement clips: {str(e)}")
        return _err(f"Error getting arrangement clips: {str(e)}")
@mcp.tool()
def duplicate_clip_to_arrangement(ctx: Context, track_index: int,
                                  source_slot_index: int,
                                  destination_time: float) -> str:
    """
    Place a Session-slot clip onto the same track's Arrangement timeline.

    The source clip is taken from a Session clip slot on the SAME track and
    duplicated onto that track's Arrangement at destination_time.

    Parameters:
    - track_index: Index of the track.
    - source_slot_index: Session clip-slot index on that track (must hold a clip).
    - destination_time: Arrangement position in beats (>= 0).
    """
    try:
        t_idx = coerce_index(track_index)
        s_idx = coerce_index(source_slot_index)
        dest = coerce_time(destination_time)
        ableton = get_ableton_connection()
        result = ableton.send_command("duplicate_clip_to_arrangement", {
            "track_index": t_idx,
            "source_slot_index": s_idx,
            "destination_time": dest,
        })
        return _ok(result)
    except Exception as e:
        logger.error(f"Error duplicating clip to arrangement: {str(e)}")
        return _err(f"Error duplicating clip to arrangement: {str(e)}")
@mcp.tool()
def delete_arrangement_clip(ctx: Context, track_index: int,
                            clip_index: int) -> str:
    """
    Delete a clip from a track's Arrangement timeline.

    Parameters:
    - track_index: Index of the track.
    - clip_index: Index into get_arrangement_clips' list (>= 0). Deleting
      re-indexes the remaining clips — re-read after.
    """
    try:
        t_idx = coerce_index(track_index)
        c_idx = coerce_index(clip_index)
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_arrangement_clip", {
            "track_index": t_idx,
            "clip_index": c_idx,
        })
        return _ok(result)
    except Exception as e:
        logger.error(f"Error deleting arrangement clip: {str(e)}")
        return _err(f"Error deleting arrangement clip: {str(e)}")


@mcp.tool()
def get_arrangement_structure(ctx: Context) -> str:
    """Derive the song's section structure from the Arrangement timeline.

    Sections are identified in two ways:
    - If cue points (locators) exist: sections = spans between consecutive
      locators (last locator to arrangement end = final section). Section
      names come from the locator names (note: Live auto-assigns sequential
      names "1", "2", etc. - original section names are not preserved in
      locators). source = "cues".
    - If no cue points: sections are inferred from clip start/stop
      change-points across all tracks. Named "Section 1", "Section 2", etc.
      with a density_label ("sparse"/"medium"/"dense"). source = "inferred".

    Each section includes per-section facts: active_tracks (track indices
    with at least one clip overlapping the span), clip_count, coverage
    (average per-track clip-beats / span-beats, 0.0-1.0), and energy
    (active_tracks * coverage, min-max normalized 0.0-1.0 across sections).

    Returns:
    {
      time_signature: [num, den],
      song_end_bar: float,         # bar of the arrangement end (1-indexed)
      source: "cues" | "inferred",
      section_count: int,
      sections: [
        {name, start_bar, length_bars, start_time, end_time,
         active_tracks, clip_count, coverage, energy}
      ]
    }

    Note: bar fields use Ableton's 1-indexed convention (bar 1 = beat 0).
    """
    try:
        ableton = get_ableton_connection()

        # 1. Time signature
        transport = ableton.send_command("get_transport", {})
        num = int(transport.get("signature_numerator", 4))
        den = int(transport.get("signature_denominator", 4))
        beats_per_bar = num * (4.0 / den)

        # 2. Track count (for the clips loop)
        session = ableton.send_command("get_session_info", {})
        track_count = int(session.get("track_count", 0))

        # 3. Cue points
        cue_result = ableton.send_command("get_cue_points", {})
        cue_list = cue_result.get("cue_points", [])

        # 4. Arrangement clips per track
        clips_by_track = []
        for t in range(track_count):
            try:
                r = ableton.send_command(
                    "get_arrangement_clips", {"track_index": t})
                clips_by_track.append(r.get("clips", []))
            except Exception:
                clips_by_track.append([])

        # 5. Song end = max end_time across all clips (and past last cue)
        all_ends = [c["end_time"] for track in clips_by_track for c in track]
        if cue_list:
            # Add 4 bars past the last cue so the final section has positive length
            # when there are no arrangement clips yet (common before calling build_arrangement)
            last_cue_time = max(c["time"] for c in cue_list)
            all_ends.append(last_cue_time + bars_to_beats(4, num, den))
        song_end = max(all_ends) if all_ends else 0.0

        # 6. Derive raw sections (name + start_time + end_time)
        if cue_list:
            raw_sections = sections_from_cues(cue_list, song_end)
            source = "cues"
        else:
            raw_sections = infer_sections(clips_by_track, song_end)
            source = "inferred"

        if not raw_sections:
            return _ok({
                "time_signature": [num, den],
                "song_end_bar": 1,
                "source": source,
                "section_count": 0,
                "sections": [],
            })

        # 7. Add bar fields and per-section facts
        result_sections = []
        for s in raw_sections:
            start_t = s["start_time"]
            end_t = s["end_time"]
            facts = section_facts({"start_time": start_t, "end_time": end_t},
                                  clips_by_track)
            # bar is 1-indexed: beat 0 = bar 1
            start_bar = 1.0 + start_t / beats_per_bar
            length_bars = (end_t - start_t) / beats_per_bar
            sec = {
                "name": s["name"],
                "start_bar": start_bar,
                "length_bars": length_bars,
                "start_time": start_t,
                "end_time": end_t,
                "active_tracks": facts["active_tracks"],
                "clip_count": facts["clip_count"],
                "coverage": facts["coverage"],
                "_raw_energy": len(facts["active_tracks"]) * facts["coverage"],
            }
            if "density_label" in s:
                sec["density_label"] = s["density_label"]
            result_sections.append(sec)

        normalize_energy(result_sections)

        # Remove internal _raw_energy key before returning
        for s in result_sections:
            s.pop("_raw_energy", None)

        song_end_bar = 1.0 + song_end / beats_per_bar

        return _ok({
            "time_signature": [num, den],
            "song_end_bar": song_end_bar,
            "source": source,
            "section_count": len(result_sections),
            "sections": result_sections,
        })
    except Exception as e:
        logger.error("Error getting arrangement structure: %s", e)
        return _err("Error getting arrangement structure: %s" % e)


@mcp.tool()
def build_arrangement(
    ctx: Context,
    sections: List[dict],
    write_locators: bool = True,
    replace: bool = False,
    start_bar: int = 1,
) -> str:
    """Assemble an Arrangement from Session clips using an explicit section map.

    Computes section start beats from bar lengths and the live time signature,
    then tiles Session clips into each section via duplicate_clip_to_arrangement.
    Optionally writes cue points (locators) at each section start so section
    positions are visible in Live and round-trip through get_arrangement_structure.
    Note: Live's LOM does not support setting CuePoint names - written locators
    receive Live's auto-sequential names ("1", "2", etc.), not the section names
    passed here.

    Parameters:
    - sections: list of section dicts:
        {
          "name": "Intro",           # required, non-empty string
          "length_bars": 8,          # required, positive number
          "clips": [                 # optional; omit for a silent section
            {
              "track_index": 0,      # non-negative int
              "source_slot_index": 0,# non-negative int (Session slot)
              "repeat": "fill"       # "fill" (tile to fill) or int (exact count)
            }
          ]
        }
    - write_locators: write a cue point at each section start (default true).
      Positions are correct; names are Live's auto-sequential labels, not the
      section names.
    - replace: before placing, delete all existing arrangement clips on every
      track referenced in the section map (idempotent re-builds). Default false.
    - start_bar: 1-indexed bar where the first section begins (default 1).

    Returns a summary of placed clips and locators. Always follow with a
    get_arrangement_structure call to verify (write-lag: returned counts may
    not reflect Live's final state).
    """
    try:
        validate_section_map(sections)
        ableton = get_ableton_connection()

        # Time signature
        transport = ableton.send_command("get_transport", {})
        num = int(transport.get("signature_numerator", 4))
        den = int(transport.get("signature_denominator", 4))

        # Compute section start beats
        computed = compute_section_starts(sections, int(start_bar), num, den)

        # Collect all track indices referenced across sections
        affected_tracks = set()
        for s in sections:
            for c in s.get("clips", []):
                affected_tracks.add(c["track_index"])

        # replace=True: clear existing arrangement clips on affected tracks
        if replace:
            for t in sorted(affected_tracks):
                try:
                    r = ableton.send_command(
                        "get_arrangement_clips", {"track_index": t})
                    existing = r.get("clips", [])
                    # Delete high-index-first to avoid re-indexing shift
                    for clip_entry in sorted(
                            existing, key=lambda x: x["index"], reverse=True):
                        ableton.send_command("delete_arrangement_clip", {
                            "track_index": t,
                            "clip_index": clip_entry["index"],
                        })
                except Exception:
                    pass  # track may have no arrangement clips - skip

        # Place clips section by section
        result_sections = []
        for s, cs in zip(sections, computed):
            section_start = cs["start_beat"]
            section_beats = cs["length_beats"]
            placed = []
            for clip_entry in s.get("clips", []):
                t = clip_entry["track_index"]
                slot = clip_entry["source_slot_index"]
                repeat = clip_entry.get("repeat", "fill")

                # Get clip length from the Session slot
                try:
                    info = ableton.send_command(
                        "get_clip_info",
                        {"track_index": t, "clip_index": slot})
                    clip_length = float(info.get("length", 0))
                except Exception as e:
                    raise ValueError(
                        "Cannot read clip info for track %d slot %d: %s"
                        % (t, slot, e))

                offsets = tiling_plan(section_beats, clip_length, repeat)
                for offset in offsets:
                    ableton.send_command("duplicate_clip_to_arrangement", {
                        "track_index": t,
                        "source_slot_index": slot,
                        "destination_time": section_start + offset,
                    })
                placed.append({
                    "track_index": t,
                    "source_slot_index": slot,
                    "count": len(offsets),
                    "first_time": section_start,
                })

            result_sections.append({
                "name": s["name"],
                "start_bar": 1.0 + section_start / (num * (4.0 / den)),
                "length_bars": s["length_bars"],
                "placed_clips": placed,
                "locator_written": False,  # filled in below if applicable
            })

        # Write locators if requested
        total_clips = sum(
            c["count"]
            for rs in result_sections
            for c in rs["placed_clips"]
        )
        if write_locators:
            try:
                transport2 = ableton.send_command("get_transport", {})
                original = transport2.get("current_song_time", 0.0)
            except Exception:
                original = 0.0
            for rs, cs in zip(result_sections, computed):
                beat = cs["start_beat"]
                try:
                    ableton.send_command("set_song_position", {"time_beats": beat})
                    ableton.send_command("create_cue_at_playhead", {})
                    rs["locator_written"] = True
                except Exception:
                    rs["locator_written"] = False
            try:
                ableton.send_command("set_song_position", {"time_beats": original})
            except Exception:
                pass

        return _ok({
            "built": True,
            "time_signature": [num, den],
            "total_clips_placed": total_clips,
            "sections": result_sections,
            "note": "Follow with get_arrangement_structure to verify (write-lag).",
        })
    except Exception as e:
        logger.error("Error building arrangement: %s", e)
        return _err("Error building arrangement: %s" % e)


def _resolve_auto_target(ableton, track_index, target_type, device_index,
                         parameter, mixer_property, send_index):
    """Normalize an automation parameter target. For device targets, resolve a
    parameter name->index via a get_device_parameters round-trip (mirrors
    set_device_parameter). Returns a dict of resolved fields to forward to the
    Remote Script."""
    ttype = normalize_target_type(target_type)
    if ttype == "mixer":
        canonical, sidx = normalize_mixer_target(mixer_property, send_index)
        return {
            "target_type": "mixer",
            "mixer_property": canonical,
            "send_index": sidx,
            "device_index": 0,
            "parameter_index": 0,
        }
    # device: resolve name/index against the live parameter list
    info = ableton.send_command(
        "get_device_parameters",
        {"track_index": track_index, "device_index": device_index},
    )
    plist = info.get("parameters", [])
    idx = resolve_parameter_index(plist, parameter)
    return {
        "target_type": "device",
        "device_index": device_index,
        "parameter_index": idx,
        "mixer_property": "",
        "send_index": -1,
    }


@mcp.tool()
def get_automation(
    ctx: Context,
    track_index: int,
    clip_index: int,
    target_type: str = "device",
    device_index: int = 0,
    parameter: Union[int, str] = 0,
    mixer_property: str = "",
    send_index: int = -1,
    clip_location: str = "session",
    from_time: float = 0.0,
    time_span: float = -1.0,
    resolution: int = 16,
) -> str:
    """
    Read a parameter's automation envelope in a clip as evenly-spaced samples
    (the Live API cannot enumerate breakpoints, only sample value_at_time).

    Parameters:
    - track_index, clip_index: locate the clip
    - clip_location: "session" (default) or "arrangement"
    - target_type: "device" (default) or "mixer"
      - device: device_index + parameter (name or index; rack macros included)
      - mixer: mixer_property in {volume, pan, send} (+ send_index for send)
    - from_time/time_span: sample window in beats (time_span<0 -> whole clip)
    - resolution: number of samples (>=1)
    Returns has_envelope plus a samples=[{time,value}] list.
    """
    try:
        loc = normalize_clip_location(clip_location)
        ableton = get_ableton_connection()
        target = _resolve_auto_target(
            ableton, track_index, target_type, device_index, parameter,
            mixer_property, send_index)
        payload = {
            "track_index": track_index,
            "clip_index": clip_index,
            "clip_location": loc,
            "from_time": from_time,
            "time_span": time_span,
            "resolution": coerce_resolution(resolution),
        }
        payload.update(target)
        result = ableton.send_command("get_automation", payload)
        return _ok(result)
    except Exception as e:
        logger.error(f"Error reading automation: {str(e)}")
        return _err(f"Error reading automation: {str(e)}")
@mcp.tool()
def set_automation(
    ctx: Context,
    track_index: int,
    clip_index: int,
    target_type: str = "device",
    device_index: int = 0,
    parameter: Union[int, str] = 0,
    mixer_property: str = "",
    send_index: int = -1,
    clip_location: str = "session",
    points: List[Dict[str, Any]] = None,
    time: float = None,
    value: float = None,
    duration: float = 0.0,
) -> str:
    """
    Write automation breakpoints into a clip (creating the envelope if absent).

    Provide EITHER a single point (time + value, optional duration) OR a
    `points` list of {time, value, duration?}. duration=0 inserts a single
    breakpoint; duration>0 inserts a flat step of that length. Values are
    clamped to the parameter's range by Live.

    Targeting is identical to get_automation (clip_location, target_type,
    device/mixer fields).
    """
    try:
        loc = normalize_clip_location(clip_location)
        breakpoints = normalize_breakpoints(points, time, value, duration)
        ableton = get_ableton_connection()
        target = _resolve_auto_target(
            ableton, track_index, target_type, device_index, parameter,
            mixer_property, send_index)
        payload = {
            "track_index": track_index,
            "clip_index": clip_index,
            "clip_location": loc,
            "breakpoints": breakpoints,
        }
        payload.update(target)
        result = ableton.send_command("set_automation", payload)
        return _ok(result)
    except Exception as e:
        logger.error(f"Error setting automation: {str(e)}")
        return _err(f"Error setting automation: {str(e)}")
@mcp.tool()
def clear_automation(
    ctx: Context,
    track_index: int,
    clip_index: int,
    target_type: str = "device",
    device_index: int = 0,
    parameter: Union[int, str] = 0,
    mixer_property: str = "",
    send_index: int = -1,
    clip_location: str = "session",
    from_time: float = None,
    time_span: float = None,
) -> str:
    """
    Clear a parameter's automation in a clip. Pass BOTH from_time and time_span
    to clear only that range; omit both to remove the parameter's whole envelope.

    Targeting is identical to get_automation.
    """
    try:
        loc = normalize_clip_location(clip_location)
        ableton = get_ableton_connection()
        target = _resolve_auto_target(
            ableton, track_index, target_type, device_index, parameter,
            mixer_property, send_index)
        payload = {
            "track_index": track_index,
            "clip_index": clip_index,
            "clip_location": loc,
            "from_time": from_time,
            "time_span": time_span,
        }
        payload.update(target)
        result = ableton.send_command("clear_automation", payload)
        return _ok(result)
    except Exception as e:
        logger.error(f"Error clearing automation: {str(e)}")
        return _err(f"Error clearing automation: {str(e)}")
@mcp.tool()
def create_automation_envelope(
    ctx: Context,
    track_index: int,
    clip_index: int,
    target_type: str = "device",
    device_index: int = 0,
    parameter: Union[int, str] = 0,
    mixer_property: str = "",
    send_index: int = -1,
    clip_location: str = "session",
) -> str:
    """
    Create an empty automation envelope for a parameter in a clip (no-op if one
    already exists; `created` reports which). Targeting is identical to
    get_automation. Note: set_automation already creates envelopes lazily; use
    this only when you want an empty lane without writing points.
    """
    try:
        loc = normalize_clip_location(clip_location)
        ableton = get_ableton_connection()
        target = _resolve_auto_target(
            ableton, track_index, target_type, device_index, parameter,
            mixer_property, send_index)
        payload = {
            "track_index": track_index,
            "clip_index": clip_index,
            "clip_location": loc,
        }
        payload.update(target)
        result = ableton.send_command("create_automation_envelope", payload)
        return _ok(result)
    except Exception as e:
        logger.error(f"Error creating automation envelope: {str(e)}")
        return _err(f"Error creating automation envelope: {str(e)}")
@mcp.tool()
def clear_all_automation(
    ctx: Context,
    track_index: int,
    clip_index: int,
    clip_location: str = "session",
) -> str:
    """
    Remove every automation envelope in a clip (clip.clear_all_envelopes()).
    """
    try:
        loc = normalize_clip_location(clip_location)
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "clear_all_automation",
            {"track_index": track_index, "clip_index": clip_index,
             "clip_location": loc},
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error clearing all automation: {str(e)}")
        return _err(f"Error clearing all automation: {str(e)}")
# === Phase 7: Change Listeners (polling buffer) ==========================
# Live's observer API is push-based; this MCP is request/response. So the
# Remote Script attaches a real Live listener whose callback buffers each
# change, and these tools register/poll/unregister/list. Claude drains events
# on demand via poll_changes — there is no server push.

@mcp.tool()
def register_listener(
    ctx: Context,
    scope: str,
    property: str,
    track_index: int = None,
    track_type: str = "regular",
    device_index: int = None,
    parameter: Union[int, str] = None,
    clip_index: int = None,
    scene_index: int = None,
) -> str:
    """
    Attach a change listener to a Live object and start buffering its events.
    Returns a listener_id to use with poll_changes / unregister_listener.

    scope + property:
    - transport: is_playing, current_song_time, tempo, metronome, record_mode,
      session_record, loop  (current_song_time fires continuously during
      playback — expect high event volume / dropped counts).
    - mixer (needs track_index, optional track_type regular|return|master):
      volume, pan, mute, solo, arm  (arm is regular-track only).
    - clip: playing_status, name, notes, has_clip (need track_index + clip_index);
      selected_scene (no selectors — observes the song view).
    - device: value (needs track_index, device_index, parameter name-or-index).

    Events are read on demand via poll_changes; nothing is pushed.
    """
    try:
        # Resolve a device parameter name/index to a concrete index server-side.
        parameter_index = None
        if needs_device_resolution(scope, property):
            if device_index is None:
                raise ValueError("device listener requires device_index")
            ableton = get_ableton_connection()
            info = ableton.send_command(
                "get_device_parameters",
                {"track_index": track_index, "device_index": device_index},
            )
            parameter_index = resolve_parameter_index(
                info.get("parameters", []),
                parameter if parameter is not None else 0,
            )
        descriptor = build_descriptor(
            scope, property,
            track_index=track_index, track_type=track_type,
            device_index=device_index, parameter_index=parameter_index,
            clip_index=clip_index, scene_index=scene_index,
        )
        ableton = get_ableton_connection()
        result = ableton.send_command("register_listener", {"descriptor": descriptor})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error registering listener: {str(e)}")
        return _err(f"Error registering listener: {str(e)}")
@mcp.tool()
def poll_changes(
    ctx: Context,
    listener_id: str = None,
    max_events: int = None,
) -> str:
    """
    Drain buffered change events. Omit listener_id to drain all listeners;
    pass one to drain just that listener. max_events caps the count returned
    per listener (oldest first); omit for all pending.

    Each event: {listener_id, target, property, value, seq}. Per-listener
    `dropped` counts events evicted because the buffer overflowed since the
    last poll (poll often if a target is high-volume).
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "poll_changes",
            {"listener_id": listener_id, "max_events": coerce_max_events(max_events)},
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error polling changes: {str(e)}")
        return _err(f"Error polling changes: {str(e)}")
@mcp.tool()
def unregister_listener(
    ctx: Context,
    listener_id: str = None,
) -> str:
    """
    Detach a listener and discard its buffer. Omit listener_id to remove ALL
    active listeners. Always detach listeners you no longer need.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "unregister_listener", {"listener_id": listener_id})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error unregistering listener: {str(e)}")
        return _err(f"Error unregistering listener: {str(e)}")
@mcp.tool()
def list_listeners(ctx: Context) -> str:
    """
    List active change listeners with each one's target plus its buffer's
    pending and dropped event counts.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("list_listeners")
        return _ok(result)
    except Exception as e:
        logger.error(f"Error listing listeners: {str(e)}")
        return _err(f"Error listing listeners: {str(e)}")
# Main execution
def main():
    """Run the MCP server"""
    mcp.run()

if __name__ == "__main__":
    main()