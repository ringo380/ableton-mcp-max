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
import platform
import shutil
import sys
from dataclasses import dataclass
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any, List, Optional, Union

from ableton_mcp_max import platform_utils as plat
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
from ableton_mcp_max.clipping_utils import annotate_meters, clipping_flags
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
    partition_master,
)
from ableton_mcp_max.sample_utils import (
    classify_sample,
    name_match,
    icloud_placeholder_path,
    refine_kind_by_length,
)
from ableton_mcp_max.tap_connection import AudioTapConnection
from ableton_mcp_max.tap_registry import TapRegistry
from ableton_mcp_max import composition_utils as comp
from ableton_mcp_max import groove_utils as groove
from ableton_mcp_max.groove_utils import normalize_groove_selector
from ableton_mcp_max import groove_preset_utils as groovep
from ableton_mcp_max.save_utils import (
    is_untitled_title,
    clean_set_name,
    set_name_from_path,
)
from ableton_mcp_max.export_utils import (
    plan_export,
    choose_menu_item,
    popup_matches,
    strip_menu_check,
    clean_render_name,
    loop_range_for,
)
from ableton_mcp_max import als_automation_utils as als
from ableton_mcp_max import stem_utils
from ableton_mcp_max import key_detection_utils as kd
from ableton_mcp_max import plugin_config_utils as pcu
from ableton_mcp_max import param_map_utils as pmu
from ableton_mcp_max import serum_state_codec as _ssc
from ableton_mcp_max import serum_fx_utils as _sfx
from ableton_mcp_max import serum_fx_catalog as _sfxcat
from ableton_mcp_max import serum_patch_utils as _spu
from ableton_mcp_max import serum_patch_catalog as _spcat
from ableton_mcp_max import catalog_db as _cat_db
from ableton_mcp_max import catalog_index as _cat_index
from ableton_mcp_max import catalog_query as _cat_query
from ableton_mcp_max import catalog_decide as _cat_decide
from ableton_mcp_max import catalog_adapt
from ableton_mcp_max import instrument_select
from ableton_mcp_max import ozone_utils as _oz
from ableton_mcp_max import ozone_param_catalog as _ozcat
from ableton_mcp_max import ozone_state_utils as _osu
from ableton_mcp_max import master_select as _msel
from ableton_mcp_max import catalog_query
from ableton_mcp_max import master_ozone_utils

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AbletonMCPServer")
# comtypes (Windows UIA) logs its typelib cache at INFO on every load.
logging.getLogger("comtypes").setLevel(logging.WARNING)


def _ok(data):
    """Wrap a successful tool result in the uniform {ok, data} envelope."""
    return json.dumps({"ok": True, "data": data}, indent=2)


def _err(message, **extra):
    """Wrap a tool failure in the uniform {ok, error} envelope. `extra` adds
    top-level facts a caller must not have to infer (render_audio's
    rendered=False: a timed-out render must never look like a delivered file)."""
    payload = {"ok": False, "error": str(message)}
    payload.update(extra)
    return json.dumps(payload, indent=2)


def _vol_value(v):
    """Coerce a get_mixer volume field to a float knob value.

    The Remote Script's get_mixer returns volume as a {value, min, max} dict
    (_param_dict), but the gain tools need the bare float to feed
    live_volume_to_db. Tolerate both shapes (and None)."""
    if isinstance(v, dict):
        return v.get("value")
    return v


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
    "set_track_fold", "focus_view", "capture_midi", "capture_and_insert_scene",
    "trigger_session_record", "stop_all_clips", "tap_tempo",
    "select_drum_pad", "assign_groove_to_clip", "set_song_scale",
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
    "capture_and_insert_scene", "set_song_scale",
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
        if measure:
            promoted = set()
            clip_rule = next((r for r in rules if r["id"] == "health.no_clipping"), None)
            ceiling = (clip_rule.get("params") or {}).get("ceiling_db", 0.0) if clip_rule else 0.0
            try:
                if _tap_registry.state.tracks():
                    # Tap path: one measure pass feeds both mix_signal and clipping.
                    name_by_index = {t["index"]: t["name"] for t in snapshot["tracks"]
                                     if t.get("index") is not None}
                    name_by_index[-1] = "Master"
                    tracks_out, sigs = _measure_pass(
                        measure_window_s, name_by_index=name_by_index)
                    # Per-track taps are pre-fader; the master tap is post-fader.
                    # Cross-track mix findings compare instruments only (the
                    # master would skew balance/masking); clipping still uses all.
                    per_track, master_sig = partition_master(sigs)
                    mix_findings = build_mix_findings(per_track, rules)
                    result["mix_signal"] = {"window_s": measure_window_s,
                                            "tracks": tracks_out,
                                            "master": master_sig,
                                            "findings": mix_findings}
                    promoted |= {f["id"] for f in mix_findings}
                    if clip_rule is not None:
                        meters = [{"name": s.get("name"), "index": s.get("index"),
                                   "track_type": "master" if s.get("index", 0) == -1 else "regular",
                                   "peak": s.get("peak")} for s in sigs]
                        clip_items = clipping_flags(meters, ceiling_db=ceiling)
                        result["findings"].extend(_build_clipping_findings(clip_items, snapshot))
                        promoted.add("health.no_clipping")
                elif clip_rule is not None:
                    # No-tap path: peak-hold pass over Live's output meters.
                    held = _peak_hold_pass(measure_window_s)
                    meters = _meters_from_held(held)
                    clip_items = clipping_flags(meters, ceiling_db=ceiling)
                    result["findings"].extend(_build_clipping_findings(clip_items, snapshot))
                    promoted.add("health.no_clipping")
            except Exception as e:
                logger.info("measure pass for analyze_set failed: %s", e)
            # A checked-but-clean clipping rule reports a single pass finding.
            if "health.no_clipping" in promoted and not any(
                    f["id"] == "health.no_clipping" for f in result["findings"]):
                result["findings"].append({
                    "id": "health.no_clipping", "domain": "health",
                    "status": "pass", "severity": "fail",
                    "evidence": "no track or master clipping detected",
                    "remediation": ""})
            result["deferred_rules"] = [d for d in result["deferred_rules"]
                                        if d["id"] not in promoted]
            result["summary"]["deferred"] = len(result["deferred_rules"])
            # Re-tally status counts now that clipping findings have been added.
            for k in ("pass", "fail", "warn", "info"):
                result["summary"][k] = sum(1 for f in result["findings"]
                                           if f.get("status") == k)
        result["findings"] = generate_actions(result["findings"], snapshot)
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
        "peak_dbfs": metrics["peak_dbfs"],
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


def _peak_hold_pass(window_s, interval_s=0.1):
    """Play the set and peak-hold every output meter (the no-tap clipping path).

    Polls get_output_meters every interval_s for window_s seconds, holding the
    max linear peak per track/return/master, then stops playback. Returns
    {tracks:{idx:peak}, returns:{idx:peak}, master:peak, names:{(type,idx):name},
    played}. Isolated as a seam so tests can stub it without Live.
    """
    ableton = get_ableton_connection()
    held_tracks, held_returns, names = {}, {}, {}
    held_master = 0.0
    try:
        start_t = ableton.send_command("get_transport").get("current_song_time", 0.0)
    except Exception:
        start_t = 0.0
    ableton.send_command("start_playback")
    deadline = time.time() + (window_s if window_s else 8.0)
    while time.time() < deadline:
        try:
            m = ableton.send_command("get_output_meters")
        except Exception as e:
            logger.info("output meter read failed: %s", e)
            break
        for t in m.get("tracks", []):
            i = t.get("index")
            held_tracks[i] = max(held_tracks.get(i, 0.0), t.get("peak", 0.0) or 0.0)
            names[("regular", i)] = t.get("name")
        for t in m.get("returns", []):
            i = t.get("index")
            held_returns[i] = max(held_returns.get(i, 0.0), t.get("peak", 0.0) or 0.0)
            names[("return", i)] = t.get("name")
        held_master = max(held_master, (m.get("master") or {}).get("peak", 0.0) or 0.0)
        time.sleep(interval_s)
    ableton.send_command("stop_playback")
    try:
        end_t = ableton.send_command("get_transport").get("current_song_time", start_t)
    except Exception:
        end_t = start_t
    return {"tracks": held_tracks, "returns": held_returns, "master": held_master,
            "names": names, "played": end_t > start_t}


def _meters_from_held(held, include_returns=True):
    """Flatten a _peak_hold_pass result into the meter list clipping_utils reads."""
    meters = []
    for i, peak in held.get("tracks", {}).items():
        meters.append({"name": held.get("names", {}).get(("regular", i)),
                       "index": i, "track_type": "regular", "peak": peak})
    if include_returns:
        for i, peak in held.get("returns", {}).items():
            meters.append({"name": held.get("names", {}).get(("return", i)),
                           "index": i, "track_type": "return", "peak": peak})
    meters.append({"name": "Master", "index": 0, "track_type": "master",
                   "peak": held.get("master", 0.0)})
    return meters


def _build_clipping_findings(clip_items, snapshot):
    """Expand clipping items into per-entity health.no_clipping fail findings.

    Each finding carries the index/type/peak/current-volume that
    generate_actions needs to compute a deterministic fader trim. A master tap's
    index -1 is mapped to the (master, 0) the mixer tools expect.
    """
    vol_by = {}
    for t in snapshot.get("tracks", []):
        vol_by[("regular", t.get("index"))] = (t.get("mixer") or {}).get("volume_db", 0.0)
    for r in snapshot.get("returns", []):
        vol_by[("return", r.get("index"))] = (r.get("mixer") or {}).get("volume_db", 0.0)
    master_vol = (snapshot.get("master") or {}).get("volume_db", 0.0)
    out = []
    for it in clip_items:
        ttype, idx = it.get("track_type", "regular"), it.get("index")
        if ttype == "master" or idx == -1:
            ttype, idx, cur, entity = "master", 0, master_vol, "Master"
        else:
            cur = vol_by.get((ttype, idx), 0.0)
            entity = it.get("name") or ("track %s" % idx)
        out.append({
            "id": "health.no_clipping", "domain": "health",
            "status": "fail", "severity": "fail", "entity": entity,
            "track_index": idx, "track_type": ttype,
            "peak_dbfs": it.get("peak_dbfs"), "overshoot_db": it.get("overshoot_db"),
            "current_volume_db": cur,
            "evidence": "%s peak %.1f dBFS (%.1f dB over)" % (
                entity, it.get("peak_dbfs"), it.get("overshoot_db")),
            "remediation": "Trim the track gain so its peak leaves headroom below 0 dBFS.",
        })
    return out


@mcp.tool()
def check_clipping(ctx: Context, window_s: float = 8.0, ceiling_db: float = 0.0,
                   include_returns: bool = True) -> str:
    """Play the set briefly and flag any track/return/master peaking past 0 dBFS.

    Peak-holds Live's post-fader output meters over a window_s playback pass (no
    audio tap / Max needed), converts the held linear peak to dBFS, and flags
    entities whose peak meets/exceeds ceiling_db (default 0.0 = full scale).

    Returns JSON {ok, data:{window_s, ceiling_db, played, entities, clipping,
    any_clipping}}:
    - entities: every track/return/master {name, index, track_type, peak_dbfs,
      is_clipping, overshoot_db}.
    - clipping: just the offenders, worst (highest peak) first.
    - any_clipping: bool; played: False if the transport did not advance.

    Honest scope: the LOM output meter is a post-fader peak sampled ~10x/sec, so
    this catches obvious overs but not sub-sample inter-sample peaks - for true
    peak (dBTP) load the MCP Audio Tap and use measure_mix / read_track_meter.
    """
    try:
        held = _peak_hold_pass(window_s)
    except Exception as e:
        logger.error("Error during clipping pass: %s", e)
        return _err("Error during clipping pass: %s" % e)
    meters = _meters_from_held(held, include_returns=include_returns)
    entities = annotate_meters(meters, ceiling_db=ceiling_db)
    clipping = clipping_flags(meters, ceiling_db=ceiling_db)
    return _ok({"window_s": window_s, "ceiling_db": ceiling_db,
                "played": held.get("played", False), "entities": entities,
                "clipping": clipping, "any_clipping": len(clipping) > 0})


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

    IMPORTANT - per-track taps are PRE-FADER: the MCP Tap is an audio-effect in
    the track's device chain and Ableton's mixer fader sits AFTER the device
    chain, so each per-track signal reflects the instrument + device-chain output,
    NOT the post-fader level. A fader move does not change its track's reading.
    The only post-fader measurement point is the master (or a return), so the
    master tap's signal (data.master) is the authoritative balance/loudness
    reference. Deploy one with deploy_taps (it auto-adds a master tap by default).

    Returns JSON {ok, data:{window_s, tracks, master, findings}}:
    - tracks: [{name, index, kind, signal:{...}}] one per connected PER-TRACK tap
      (the master tap is excluded here and reported under `master`).
    - master: the master tap's {name, index, kind, signal} (post-fader program
      output), or null when no master tap is connected.
    - findings: cross-track analysis from masking_utils over the per-track signals
      - masking (pairwise spectral overlap), balance (tracks sitting too far below
      the loudest), headroom (near-clip / over-compressed), stereo (mono-compat
      risk). Each is a (possibly empty) list. The master is NOT compared against
      instruments here (it would skew balance/masking).

    With no taps connected this still returns ok with empty tracks, null master,
    and empty findings (not an error). Track names blank-reported by the device
    are backfilled from the LOM track index.
    """
    name_by_index = _track_name_map()
    tracks_out, sigs = _measure_pass(window_s, region, name_by_index)
    per_track, master_sig = partition_master(sigs)
    master_entry = next((t for t in tracks_out if t.get("index") == -1), None)
    per_track_out = [t for t in tracks_out if t.get("index") != -1]
    findings = {
        "masking": masking_score(per_track),
        "balance": loudness_balance(per_track),
        "headroom": headroom_flags(per_track),
        "stereo": stereo_flags(per_track),
    }
    return _ok({"window_s": window_s, "tracks": per_track_out,
                "master": master_entry, "findings": findings})


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


def _load_tap_on_track(track_index, track_type="regular"):
    """Browser-load the User-Library MCP Tap device onto a track.

    Resolves the device in the browser via get_browser_presets +
    match_recursive_preset, then load_browser_item. track_type 'master' loads the
    tap onto the master bus for a post-fader program measurement (track_index is
    ignored by the handler for master). Raises on any failure so deploy_taps can
    record it (and fall back to a manual-drag hint).
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
                               {"track_index": track_index, "item_uri": uri,
                                "track_type": track_type})
    if not res.get("loaded", False):
        raise RuntimeError("load_browser_item did not confirm")
    return chosen.get("relative_path") or chosen.get("name") or TAP_DEVICE_NAME


def _find_taps():
    """Return [(track_type, track_index, device_index)] for every loaded MCP Tap
    device, across regular tracks AND the master bus."""
    raw = get_ableton_connection().send_command("get_analysis_snapshot")
    out = []
    for t in raw.get("tracks", []):
        ti = t.get("index")
        if ti is None:
            continue
        for d in t.get("devices", []):
            if d.get("name") == TAP_DEVICE_NAME and d.get("index") is not None:
                out.append(("regular", ti, d.get("index")))
    master = raw.get("master") or {}
    for d in master.get("devices", []):
        if d.get("name") == TAP_DEVICE_NAME and d.get("index") is not None:
            out.append(("master", 0, d.get("index")))
    return out


def _delete_device_raw(track_type, track_index, device_index):
    """Delete one device over the wire (regular track or master). Raises on
    failure."""
    get_ableton_connection().send_command(
        "delete_device",
        {"track_index": track_index, "device_index": device_index,
         "track_type": track_type})


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
def deploy_taps(ctx: Context, track_indices: List[int] = None,
                include_master: bool = True) -> str:
    """Load the MCP Tap metering device onto tracks for per-track analysis.

    track_indices: omit to auto-target every regular audio track + every MIDI
    track holding an instrument; or pass explicit track indices. Use -1 for the
    master bus (e.g. track_indices=[-1] taps the master only). The device must be
    present in the User Library (copy m4l/'MCP Tap.amxd' there once); see
    m4l/README.md.

    include_master (default True): in auto-target mode (track_indices omitted),
    also drop a tap on the master bus. The master tap is the only POST-FADER
    measurement point, so it is the authoritative balance/loudness reference -
    per-track taps are pre-fader (instrument + device-chain output, ahead of the
    fader) and do not reflect fader moves. Pass include_master=False to skip it.
    When track_indices is given explicitly, include_master is ignored (add -1 to
    the list yourself).

    Idempotent: a target that ALREADY holds an MCP Tap is skipped (reported in
    already_present) rather than getting a second, duplicate tap stacked on it.
    Use remove_taps to clear taps before re-deploying.

    Returns JSON {ok, data:{targets, deployed:[{track_index,device}],
    already_present:[{track_index,device}], failed:[{track_index,error}]}}. If
    EVERY load fails (e.g. the device isn't in the browser), data.manual is true
    with a drag-it-yourself message listing the target tracks - the registry
    still works once the device is dragged on by hand. After deploying, run
    measure_mix or analyze_set(measure=True).

    A slow Max-for-Live / Node-for-Max boot (notably Live 12 / Max 8.6) can
    outlast the socket read timeout, so the load reply is lost even though the
    device loaded + connected. When a load times out, deploy_taps polls the tap
    registry and, if a tap connects on that track, records it as deployed with
    "confirmed_via": "registry" instead of failing.
    """
    try:
        if track_indices is None:
            targets = _audio_instrument_track_indices()
            if include_master and -1 not in targets:
                targets.append(-1)
        else:
            targets = list(track_indices)
        # Idempotent: a track that ALREADY holds an MCP Tap is left alone.
        # Without this, re-running deploy stacks a second identical metering
        # device on the same track - apply_master always taps the master, so
        # every mastering pass used to append another tap to it.
        existing = {(tt, ti) for tt, ti, _di in _find_taps()}
        deployed, failed, already = [], [], []
        for i in targets:
            track_type = "master" if i == -1 else "regular"
            # _find_taps reports the master as ("master", 0), not index -1.
            if (track_type, 0 if i == -1 else i) in existing:
                already.append({"track_index": i, "device": TAP_DEVICE_NAME})
                continue
            before = {t.get("uuid") for t in _tap_registry.state.tracks()}
            try:
                label = _load_tap_on_track(i, track_type)
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
        data = {"targets": targets, "deployed": deployed,
                "already_present": already, "failed": failed}
        # Only a genuine all-failed run warrants the drag-it-yourself message -
        # targets skipped because a tap is already there are a success.
        if targets and not deployed and not already:
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

    Scans all regular tracks AND the master bus for devices named 'MCP Tap' and
    deletes them (per-track, highest device index first so re-indexing is safe).
    Returns JSON {ok, data:{removed_count,
    removed:[{track_type,track_index,device_index}], errors:[...]}}. No-op
    (removed_count 0) when none are loaded.
    """
    try:
        found = _find_taps()
        # delete highest device_index first within each track so re-indexing
        # never shifts a still-pending target on the same track.
        ordered = sorted(found, key=lambda p: (p[0], p[1], -p[2]))
        removed, errors = [], []
        for tt, ti, di in ordered:
            try:
                _delete_device_raw(tt, ti, di)
                removed.append({"track_type": tt, "track_index": ti, "device_index": di})
            except Exception as e:
                errors.append({"track_type": tt, "track_index": ti,
                               "device_index": di, "error": str(e)})
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
        current_vol = _vol_value(mixer.get("volume"))
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


@mcp.tool()
def gain_stage_track(
    ctx: Context,
    track_index: int,
    target_db: float = -18.0,
    window_s: float = 4.0,
    max_iterations: int = 3,
    track_type: str = "regular",
) -> str:
    """Play the set, measure the track's LUFS via its MCP Tap, and iteratively
    converge the fader to target_db.

    IMPORTANT - on a regular/return track the MCP Tap is PRE-FADER (it sits in the
    device chain, ahead of the mixer fader), so moving the fader does NOT change
    what the tap reads: the loop measures the instrument + device-chain level, not
    the post-fader output, and re-measuring will show the same value (it may report
    not-converged). Use this as an instrument-level gain-stage (the first-pass
    correction is still a valid trim toward target), or run it on the MASTER
    (track_type='master', the post-fader program output) for true loudness
    convergence.

    Requires an MCP Tap device deployed on the target track (via deploy_taps).
    Plays the arrangement for window_s seconds each iteration, integrates the
    buffered tap blocks into LUFS, computes the correction, and applies it via
    the fader. Repeats up to max_iterations times or until within 1 dB of target.

    Parameters:
    - track_index: index of the regular/return/master track to stage
    - target_db: target integrated LUFS (default -18.0, a standard gain-staging level)
    - window_s: playback capture window per iteration in seconds (default 4.0)
    - max_iterations: maximum correction cycles (default 3)
    - track_type: "regular" (default), "return", or "master"

    Returns JSON {ok, data:{track_index, target_db, before_db, after_db,
    correction_db, converged, iterations, volume_before, volume_after}}.
    {ok:false,error} if no tap is connected for this track.
    """
    try:
        uuid = _uuid_for_index(track_index)
        if uuid is None:
            return _err("No tap connected for track %s" % track_index)

        ableton = get_ableton_connection()
        mixer_initial = ableton.send_command(
            "get_mixer", {"track_index": track_index, "track_type": track_type}
        )
        volume_before = _vol_value(mixer_initial.get("volume"))
        if volume_before is None:
            return _err("Volume not available for track %s" % track_index)

        sample_rate = 48000
        for t in _tap_registry.state.tracks():
            if t.get("uuid") == uuid:
                sample_rate = t.get("sample_rate", 48000)
                break

        before_db = None
        measured_db = None
        last_vol = volume_before
        total_correction = 0.0
        converged = False
        iterations = 0

        for _ in range(max(1, max_iterations)):
            iterations += 1
            _tap_registry.state.reset(uuid)
            _run_measure_playback(window_s)
            buf = _tap_registry.state.buffer(uuid)
            metrics = _integrate_buffer(buf, sample_rate)
            measured_db = metrics.get("integrated_lufs")
            if measured_db is None:
                return _err("No audio data received for track %s; is the set playing?" % track_index)
            if before_db is None:
                before_db = measured_db
            delta = target_db - measured_db
            if abs(delta) < 1.0:
                converged = True
                break
            current_db = live_volume_to_db(last_vol)
            new_db = max(-70.0, min(6.0, current_db + delta))
            new_vol = db_to_live_volume(new_db)
            ableton.send_command(
                "set_mixer_property",
                {"track_index": track_index, "track_type": track_type,
                 "property": "volume", "value": new_vol, "send_index": -1},
            )
            last_vol = new_vol
            total_correction += delta

        mixer_final = ableton.send_command(
            "get_mixer", {"track_index": track_index, "track_type": track_type}
        )
        volume_after = _vol_value(mixer_final.get("volume"))
        if volume_after is None:
            volume_after = last_vol

        return _ok({
            "track_index": track_index,
            "track_type": track_type,
            "target_db": target_db,
            "before_db": before_db,
            "after_db": measured_db,
            "correction_db": round(total_correction, 1),
            "converged": converged,
            "iterations": iterations,
            "volume_before": volume_before,
            "volume_after": volume_after,
        })
    except Exception as e:
        logger.error("Error in gain_stage_track: %s", e)
        return _err("Error in gain_stage_track: %s" % e)


@mcp.tool()
def balance_mix(
    ctx: Context,
    reference_track_index: int,
    window_s: float = 8.0,
    target_offsets: list = None,
    tracks: list = None,
) -> str:
    """Single coherent measure pass + batch-apply level corrections.

    Runs one measure_mix-style playback window across all connected taps,
    then adjusts each track's fader so its integrated LUFS matches the
    reference track (plus any per-track offset_db you specify). Tracks within
    1 dB of their target are skipped. All corrections are applied individually
    (not batched) so each adjust_track_gain call validates its own target.

    IMPORTANT - per-track taps are PRE-FADER (instrument + device-chain level,
    ahead of the mixer fader). The correction math is still right for OUTPUT
    balance: it adds each track's pre-fader gap onto its fader so output =
    pre_fader + fader matches the reference - but ONLY if the reference track's
    fader is left as the anchor, and the result CANNOT be re-verified by
    re-measuring the same per-track taps (their readings are invariant to the
    fader). To confirm the balance landed, deploy a master tap and read the
    post-fader program output (measure_mix data.master).

    Parameters:
    - reference_track_index: track whose LUFS is the balance baseline
    - window_s: capture length in seconds (default 8.0)
    - target_offsets: optional list of {track_index, offset_db} specifying
      how many dB above/below the reference each track should sit
    - tracks: optional list of track indices to correct (subset of tapped tracks)

    Returns JSON {ok, data:{reference_track_index, reference_db, window_s,
    adjustments:[{track_index, name, before_db, delta_db, skipped}]}}.
    """
    try:
        tracks_out, sigs = _measure_pass(window_s)
        kind_by_index = {t.get("index"): t.get("kind", "regular") for t in tracks_out}
        ref_lufs = None
        for s in sigs:
            if s.get("index") == reference_track_index:
                ref_lufs = s.get("integrated_lufs")
                break
        if ref_lufs is None:
            return _err(
                "Reference track %s not found in tap signals. "
                "Is a tap deployed on that track?" % reference_track_index
            )

        deltas = compute_balance_deltas(sigs, reference_track_index, target_offsets)

        # Filter to the requested subset
        if tracks is not None:
            track_set = set(tracks)
            deltas = [d for d in deltas if d["track_index"] in track_set]

        ableton = get_ableton_connection()
        adjustments = []
        for d in deltas:
            if d["skipped"]:
                adjustments.append({
                    "track_index": d["track_index"],
                    "name": d["name"],
                    "before_db": d["current_lufs"],
                    "delta_db": d["delta_db"],
                    "skipped": True,
                })
                continue
            idx = d["track_index"]
            track_type = kind_by_index.get(idx, "regular")
            mixer = ableton.send_command(
                "get_mixer", {"track_index": idx, "track_type": track_type}
            )
            vol = _vol_value(mixer.get("volume"))
            if vol is None:
                adjustments.append({
                    "track_index": idx,
                    "name": d["name"],
                    "before_db": d["current_lufs"],
                    "delta_db": d["delta_db"],
                    "skipped": True,
                    "skip_reason": "volume not available",
                })
                continue
            current_db = live_volume_to_db(vol)
            new_db = max(-70.0, min(6.0, current_db + d["delta_db"]))
            new_vol = db_to_live_volume(new_db)
            ableton.send_command(
                "set_mixer_property",
                {"track_index": idx, "track_type": track_type,
                 "property": "volume", "value": new_vol, "send_index": -1},
            )
            adjustments.append({
                "track_index": idx,
                "name": d["name"],
                "before_db": d["current_lufs"],
                "delta_db": d["delta_db"],
                "skipped": False,
            })

        return _ok({
            "reference_track_index": reference_track_index,
            "reference_db": ref_lufs,
            "window_s": window_s,
            "adjustments": adjustments,
        })
    except Exception as e:
        logger.error("Error in balance_mix: %s", e)
        return _err("Error in balance_mix: %s" % e)


@mcp.tool()
def apply_findings(
    ctx: Context,
    findings: list,
    dry_run: bool = True,
    severity_filter: list = None,
    focus: list = None,
) -> str:
    """Translate analyze_set findings into a correction plan and optionally apply it.

    Takes the ``findings`` list from analyze_set output (or a merged list) and
    executes the mechanically-fixable ones. Findings with an ``action`` dict
    (added by analyze_set's generate_actions enrichment) that match the
    severity_filter are applied; others are reported as skipped with a reason.

    IMPORTANT: dry_run defaults to True - the plan is returned without mutating
    Live. Always inspect the plan before passing dry_run=False.

    Parameters:
    - findings: list of finding dicts from analyze_set data.findings (must
      have been produced with action enrichment - i.e. from this server v0.12+)
    - dry_run: when True (default), return the plan without applying changes
    - severity_filter: list of severities to include (default ["fail", "warn"])
    - focus: optional list of finding ids to restrict to

    Returns JSON {ok, data:{dry_run, plan:[{finding_id, severity, action, status,
    [error]}], planned_count, skipped_count, skipped_reasons}}.
    """
    try:
        sev = severity_filter if severity_filter is not None else ["fail", "warn"]
        plan_data = build_correction_plan(findings, severity_filter=sev, focus=focus)

        if dry_run:
            return _ok({
                "dry_run": True,
                "plan": plan_data["plan"],
                "planned_count": plan_data["planned_count"],
                "skipped_count": plan_data["skipped_count"],
                "skipped_reasons": plan_data["skipped_reasons"],
            })

        ableton = get_ableton_connection()
        results = []
        for entry in plan_data["plan"]:
            action = entry["action"]
            tool_name = action.get("tool")
            params = action.get("params", {})
            try:
                if tool_name == "set_mixer_property":
                    ableton.send_command("set_mixer_property", {
                        "track_index": params.get("track_index", 0),
                        "track_type": params.get("track_type", "regular"),
                        "property": params.get("property"),
                        "value": params.get("value"),
                        "send_index": params.get("send_index", -1),
                    })
                    results.append({**entry, "status": "applied"})
                else:
                    results.append({**entry, "status": "error",
                                    "error": "unknown tool %s" % tool_name})
            except Exception as exc:
                results.append({**entry, "status": "error", "error": str(exc)})

        applied = sum(1 for r in results if r["status"] == "applied")
        return _ok({
            "dry_run": False,
            "plan": results,
            "planned_count": len(results),
            "applied_count": applied,
            "skipped_count": plan_data["skipped_count"],
            "skipped_reasons": plan_data["skipped_reasons"],
        })
    except Exception as e:
        logger.error("Error in apply_findings: %s", e)
        return _err("Error in apply_findings: %s" % e)


# --- Graceful Live quit / restart -----------------------------------------
# kill -TERM is a crash from Live's POV (recovery modal on relaunch), so we quit
# through the Apple 'quit' event and answer the unsaved-changes dialog by
# keystroke. The LOM exposes no save-state or save API, so "dirty" is detected by
# Live still being alive shortly after the quit (a clean quit is fast), and
# "save" is the dialog's Return — an Untitled set has no path, so it then pops a
# Save-As dialog we can't fill (reported back, not guessed). The OS calls below
# are seams so the orchestration is unit-testable without touching real apps.
LIVE_PORT = 9877
IS_WINDOWS = plat.is_windows(sys.platform)
if IS_WINDOWS:
    from ableton_mcp_max import win_ui as _win


def _os_name():
    """The OS the UI layer is driving: plat.WIN whenever the Windows layer is
    selected (so its title/name rules apply even when tests select it on a
    Mac), else the real platform."""
    return plat.WIN if IS_WINDOWS else sys.platform


def _prefs_base():
    """Parent dir of Live's per-version preference dirs."""
    return plat.prefs_base(sys.platform, os.path.expanduser("~"),
                           os.environ.get("APPDATA"))


def _running_live_version():
    """'x.y.z' of the Live the host is talking to, or None."""
    try:
        info = get_ableton_connection().send_command("get_application_version")
        return "%d.%d.%d" % (int(info["major"]), int(info["minor"]),
                             int(info["bugfix"]))
    except Exception:
        return None


def _win_pref_dirs():
    """Windows 'Live x.y.z\\Preferences' dirs, best LAST: the running Live's
    exact version when known, else the highest version (numeric sort)."""
    dirs = [os.path.join(d, "Preferences")
            for d in glob.glob(os.path.join(_prefs_base(), "Live *"))]
    dirs = [d for d in dirs if os.path.isdir(d)]
    parents = plat.order_pref_dirs(sys.platform,
                                   [os.path.dirname(d) for d in dirs],
                                   _running_live_version())
    return [os.path.join(p, "Preferences") for p in parents]


def _documents_dir():
    """The user's Documents known folder (follows OneDrive redirection on
    Windows), or None if it can't be resolved."""
    if not IS_WINDOWS:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _GUID(ctypes.Structure):
            _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD),
                        ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]
        # FOLDERID_Documents {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
        fid = _GUID(0xFDD39AD0, 0x238F, 0x46AF,
                    (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85,
                                         0x48, 0x03, 0x69, 0xC7))
        out = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(fid), 0, None, ctypes.byref(out)) != 0:
            return None
        path = out.value
        ctypes.windll.ole32.CoTaskMemFree(out)
        return path
    except Exception:
        return None


def _osa_unavailable():
    if IS_WINDOWS:
        raise RuntimeError("Internal error: a macOS-only UI path was reached on "
                           "Windows.")


def _osa(script):
    """Run an AppleScript and wait. Keystroke/System-Events scripts return
    immediately; used for the dialog answers. Seam for tests."""
    _osa_unavailable()
    subprocess.run(["/usr/bin/osascript", "-e", script],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)


def _osa_async(script):
    """Fire an AppleScript without waiting — for the 'quit' event, which BLOCKS
    until the save dialog (if any) is answered. Seam for tests."""
    _osa_unavailable()
    subprocess.Popen(["/usr/bin/osascript", "-e", script],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _osa_get(script):
    """Run an AppleScript and RETURN its stripped stdout ('' on error). Seam for
    tests; used to read UI state (window title, sheet presence)."""
    _osa_unavailable()
    try:
        out = subprocess.check_output(["/usr/bin/osascript", "-e", script],
                                      stderr=subprocess.DEVNULL, timeout=20)
        return out.decode("utf-8", "replace").strip()
    except Exception:
        return ""


# System Events targets the Live process by its (version-stable) executable name.
_LIVE_PROC = "Live"


def _as_literal(s):
    r"""Escape a string for embedding inside an AppleScript "..." literal."""
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def _live_window_title(proc=_LIVE_PROC):
    """Title of Live's main SET window ('' if unreadable). 'Untitled' for a set
    with no file on disk (see save_utils.is_untitled_title).

    Reads the first AXStandardWindow, NOT `window 1`: a plugin's custom editor
    (e.g. a freshly loaded Ozone 12) opens as an AXFloatingWindow that sits ON
    TOP of the set window and persists, so `window 1` returns the PLUGIN's title
    ("Ozone 12/1-Serum 2"). That wrong title poisons every consumer - the set
    looks mis-titled to the .als path resolver (_current_set_path filters log
    lines by it) and save_set reports a save that never landed. Falls back to
    `window 1` when no standard window is readable.

    On Windows the main window's title is 'Name* - Ableton Live 12 Suite';
    the app suffix and the unsaved '*' are stripped so callers see the same
    bare set name as on macOS."""
    if IS_WINDOWS:
        return plat.set_title_from_window_title(_os_name(), _win_raw_title())
    title = _osa_get(
        'tell application "System Events" to tell process "%s" to get name of '
        '(first window whose subrole is "AXStandardWindow")' % proc)
    if title:
        return title
    return _osa_get(
        'tell application "System Events" to tell process "%s" '
        'to get name of window 1' % proc)


def _live_window_count(proc=_LIVE_PROC):
    """Number of windows on the Live process (0 if unreadable / screen locked).
    Live's Save-As path panel appears as an EXTRA standard window (not an
    AXSheet), so a count above the 1-window baseline signals a dialog is open."""
    if IS_WINDOWS:
        pid = _win.listening_pid(LIVE_PORT)
        return len(_win.windows(pid)) if pid else 0
    out = _osa_get(
        'tell application "System Events" to tell process "%s" '
        'to get (count of windows)' % proc)
    try:
        return int(out)
    except ValueError:
        return 0


def _live_app_and_pid(port=LIVE_PORT):
    """(.app path, pid int) of the Live process listening on `port`, or
    (None, None). This is authoritatively the Live the MCP talks to. On
    Windows the 'app' is the Live .exe path."""
    if IS_WINDOWS:
        pid = _win.listening_pid(port)
        exe = _win.process_image(pid) if pid else None
        return (exe, pid) if exe else (None, None)
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
    if IS_WINDOWS:           # os.kill(pid, 0) TERMINATES a process on Windows
        return _win.pid_alive(pid)
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _open_app(app):
    if IS_WINDOWS:
        _win.launch(app)
        return
    subprocess.run(["/usr/bin/open", "-a", app], check=False)


def _port_listening(port=LIVE_PORT):
    if IS_WINDOWS:
        return _win.listening_pid(port) is not None
    try:
        out = subprocess.check_output(
            ["/usr/sbin/lsof", "-nP", "-iTCP:%d" % port, "-sTCP:LISTEN", "-t"],
            stderr=subprocess.DEVNULL)
        return bool(out.strip())
    except Exception:
        return False


def _app_name(app_path):
    """'Ableton Live 12 Suite' from a .app path (for AppleScript 'tell app') or
    a Windows .exe path."""
    base = os.path.basename(app_path)
    for ext in (".app", ".exe"):
        if base.lower().endswith(ext):
            return base[:-len(ext)]
    return base


def _wait_until(predicate, timeout, interval=1.0, sleep=time.sleep):
    """Poll predicate() until truthy or timeout; return the final value."""
    waited = 0.0
    while waited < timeout and not predicate():
        sleep(interval)
        waited += interval
    return predicate()


def _keystroke(s):
    _osa('tell application "System Events" to keystroke "%s"' % _as_literal(s))


def _press_return():
    _osa('tell application "System Events" to keystroke return')


def _live_press_escape():
    """Press Escape (key code 53; 'keystroke escape' is not valid AppleScript)."""
    _osa('tell application "System Events" to key code 53')


def _click_file_menu(item, proc=_LIVE_PROC):
    """Click a Live File-menu item by name. Clicking the menu is focus-independent
    (unlike a Cmd-key keystroke), so opening the save panel is reliable even if
    Live isn't frontmost the instant we fire. On Windows the item's
    WM_COMMAND is posted to Live's native menu bar (also focus-independent)."""
    if IS_WINDOWS:
        _win.post_menu(_win_live()[1], "File", item)
        return
    _osa('tell application "System Events" to tell process "%s" to click '
         'menu item "%s" of menu 1 of menu bar item "File" of menu bar 1'
         % (proc, _as_literal(item)))


# Roots Ableton may drop a "<name> Project" folder into. The Save panel saves to
# its LAST-USED location, which isn't introspectable, so we look here best-effort
# to report the resolved path — but never fail the save if it's not found.
# --- Windows UI layer ------------------------------------------------------
# Live 12 on Windows has a native Win32 menu bar, uses the stock Windows Save
# dialog for Save As / export, and draws its own prompts (exposed through UI
# Automation). So the Windows flows below post menu commands (focus-free),
# answer prompts by UIA Invoke (focus-free), and TYPE the file name into the
# native Save dialog - the one step that brings Live to the front, because the
# dialog ignores a name set by window message (see win_ui.file_dialog_save).

_WIN_SAVE_SET_DIALOG = "Save Live Set As:"
_WIN_SAVE_AUDIO_DIALOG = "Save Audio File As:"


def _win_live():
    """(pid, main hwnd, exe) of the Live listening on LIVE_PORT."""
    pid = _win.listening_pid(LIVE_PORT)
    hwnd = _win.main_window(pid) if pid else None
    if not hwnd:
        raise RuntimeError("No running Ableton Live found on port %d." % LIVE_PORT)
    return pid, hwnd, _win.process_image(pid)


def _win_raw_title():
    try:
        return _win.window_title(_win_live()[1])
    except RuntimeError:
        return ""


def _win_wait_window(pid, title, timeout, sleep=time.sleep):
    """hwnd of `pid`'s window titled `title` once it appears, else None."""
    found = []

    def _seen():
        h = _win.find_window(pid, title)
        if h:
            found[:] = [h]
        return bool(h)

    _wait_until(_seen, timeout=timeout, interval=0.25, sleep=sleep)
    return found[0] if found else None


def _win_prompt(pid):
    """(hwnd, {button name: element}) of a Live-drawn prompt (an unnamed
    top-level window with Yes/No/OK/Cancel buttons), or (None, {})."""
    from ableton_mcp_max import win_uia
    for hwnd, title, cls in _win.windows(pid):
        if title or cls != _win.LIVE_WINDOW_CLASS:
            continue
        try:
            root = win_uia.element(hwnd)
        except Exception:
            continue
        buttons = {}
        for name in ("Yes", "No", "OK", "Cancel"):
            el = win_uia.find(root, name, win_uia.BUTTON)
            if el is not None:
                buttons[name] = el
        if buttons:
            return hwnd, buttons
    return None, {}


def _win_press_prompt(buttons, name):
    from ableton_mcp_max import win_uia
    win_uia.invoke(buttons[name])


def _win_confirm_overwrite(pid, sleep=time.sleep):
    """Answer an 'already exists - replace it?' confirmation (the stock
    'Confirm Save As' box or a Live prompt) with Yes. True if one was seen."""
    from ableton_mcp_max import win_uia
    for hwnd, title in _win.dialogs(pid):
        if title.startswith("Confirm"):
            el = win_uia.find(win_uia.element(hwnd), "Yes", win_uia.BUTTON)
            if el is not None:
                win_uia.invoke(el)
                return True
            return _win.dialog_click(hwnd, _win.IDYES)
    _hwnd, buttons = _win_prompt(pid)
    if "Yes" in buttons and "No" in buttons:
        _win_press_prompt(buttons, "Yes")
        return True
    return False


def _win_saved_path(folder, basename):
    """The .als a Save dialog just wrote into `folder`: Live writes either
    <folder>/<name>.als (saving inside an existing project) or wraps it as
    <folder>/<name> Project/<name>.als. '' if neither exists."""
    best, best_mtime = "", -1.0
    for cand in (os.path.join(folder, "%s.als" % basename),
                 os.path.join(folder, "%s Project" % basename, "%s.als" % basename)):
        try:
            m = os.path.getmtime(cand)
        except OSError:
            continue
        if m > best_mtime:
            best, best_mtime = cand, m
    return best


def _win_save_as_impl(name, sleep=time.sleep):
    basename = clean_set_name(name, illegal=plat.illegal_name_chars(_os_name()))
    pid, hwnd, exe = _win_live()
    result = {"app": exe, "name": basename}
    _win.post_menu(hwnd, "File", "Save Live Set As...")
    dlg = _win_wait_window(pid, _WIN_SAVE_SET_DIALOG, timeout=8.0, sleep=sleep)
    if not dlg:
        result["saved"] = False
        result["error"] = "The Save Live Set As dialog did not appear."
        return result
    folder = _win.file_dialog_folder(dlg)
    _win.file_dialog_save(dlg, basename)
    # Re-using a name raises an overwrite confirmation; the name was chosen
    # explicitly, so confirm it (same as the macOS Replace sheet).
    def _settled():
        if _win.find_window(pid, _WIN_SAVE_SET_DIALOG) is None and \
                _live_window_title() == basename:
            return True
        _win_confirm_overwrite(pid)
        return False
    if not _wait_until(_settled, timeout=15.0, interval=0.5, sleep=sleep):
        dlg = _win.find_window(pid, _WIN_SAVE_SET_DIALOG)
        if dlg:
            _win.dialog_click(dlg, _win.IDCANCEL)
        result["saved"] = False
        result["error"] = ("Save-As did not complete (title is %r, not %r)."
                           % (_live_window_title(), basename))
        return result
    result["saved"] = True
    path = (_win_saved_path(folder, basename) if folder else "") or \
        _find_saved_set(basename)
    if path:
        result["path"] = path
        _SAVED_SET_PATHS[basename] = path
    return result


def _win_save_set_impl(name="", sleep=time.sleep):
    if name:
        return _win_save_as_impl(name, sleep=sleep)
    pid, hwnd, exe = _win_live()
    raw = _win.window_title(hwnd)
    title = plat.set_title_from_window_title(_os_name(), raw)
    if is_untitled_title(title):
        return {"app": exe, "saved": False, "untitled": True, "title": title,
                "error": ("Set is untitled (no file on disk). Pass a name "
                          "(save_set(name=...) or save_set_as) to save it.")}
    _win.post_menu(hwnd, "File", "Save Live Set")
    # A titled set saves in place; the '*' unsaved marker leaving the title
    # is the confirmation. A Save-As dialog instead means Live thinks the set
    # has no file - cancel it rather than guess a location.
    def _done():
        if _win.find_window(pid, _WIN_SAVE_SET_DIALOG):
            return True
        return not plat.window_title_dirty(_os_name(), _win.window_title(hwnd))
    _wait_until(_done, timeout=10.0, interval=0.3, sleep=sleep)
    dlg = _win.find_window(pid, _WIN_SAVE_SET_DIALOG)
    if dlg:
        _win.dialog_click(dlg, _win.IDCANCEL)
        return {"app": exe, "saved": False, "title": title,
                "error": ("A save dialog appeared on Save - the set looks "
                          "untitled. Use save_set(name=...) to give it a name.")}
    if plat.window_title_dirty(_os_name(), _win.window_title(hwnd)):
        return {"app": exe, "saved": False, "title": title,
                "error": "Live still shows unsaved changes after Save."}
    return {"app": exe, "saved": True, "title": title}


def _win_restart_live_impl(save="discard", relaunch=True, wait_timeout=90.0,
                           dirty_after=5.0, sleep=time.sleep):
    if save not in ("discard", "save"):
        raise ValueError("save must be 'discard' or 'save' (got %r)." % save)
    pid, hwnd, exe = _win_live()
    raw = _win.window_title(hwnd)
    dirty = bool(plat.window_title_dirty(_os_name(), raw))
    result = {"app": exe, "pid": pid, "save": save, "was_dirty": dirty}
    if dirty and save == "save" and is_untitled_title(
            plat.set_title_from_window_title(_os_name(), raw)):
        # Saving would open a Save-As dialog this can't name - refuse up front
        # instead of leaving Live half-quit.
        result["quit"] = False
        result["error"] = ("The set is Untitled with unsaved changes - save it "
                           "first with save_set_as, or restart with "
                           "save='discard'.")
        return result

    _win.close(hwnd)                       # graceful quit (like Apple 'quit')
    # A clean set closes its window at once; a dirty one raises Live's
    # 'Save changes to "X" before closing?' prompt (Yes / No / Cancel).
    def _settled():
        return bool(_win_prompt(pid)[1]) or not _win.main_window(pid)
    _wait_until(_settled, timeout=dirty_after if dirty else 2.0,
                interval=0.25, sleep=sleep)
    _hwnd, buttons = _win_prompt(pid)
    if buttons:
        result["was_dirty"] = True
        want = "Yes" if save == "save" else "No"
        if want in buttons:
            _win_press_prompt(buttons, want)
            result["dialog_answered"] = save

    if not _wait_until(lambda: not _win.pid_alive(pid), timeout=45.0,
                       interval=1.0, sleep=sleep):
        result["quit"] = False
        if _win.main_window(pid):
            result["error"] = ("Live did not quit (a dialog may still be open "
                               "in Live).")
        else:
            # Seen on Windows: the window closes but the process hangs in
            # shutdown (a thread stuck in the audio driver) and cannot be
            # killed. Don't relaunch on top of it.
            result["error"] = ("Live closed its window but the process is still "
                               "exiting (pid %d). If it stays in Task Manager as "
                               "'Not responding', end it there or reboot, then "
                               "start Live." % pid)
        return result
    result["quit"] = True

    if relaunch:
        _win.launch(exe)
        result["relaunched"] = True
        result["surface_up"] = _wait_until(_port_listening, timeout=wait_timeout,
                                           sleep=sleep)
    return result


def _win_reload_set(path, set_name, settle=0.6, timeout=30.0, sleep=time.sleep,
                    probe=None):
    pid, hwnd, _exe = _win_live()
    _win.post_menu(hwnd, "File", "New Live Set")
    sleep(settle)
    for _ in range(3):
        _p, buttons = _win_prompt(pid)
        if not buttons:
            break
        for answer in ("No", "OK", "Yes"):
            if answer in buttons:
                _win_press_prompt(buttons, answer)
                break
        sleep(settle)
    _open_file(path)

    def _ready():
        if _live_window_title() != set_name:
            return False
        if probe is None:
            return True
        try:
            probe()
            return True
        except Exception:
            return False

    ok = _wait_until(_ready, timeout=timeout, interval=1.0, sleep=sleep)
    return {"reloaded": bool(ok), "title": _live_window_title()}


def _save_search_roots():
    return plat.save_search_roots(sys.platform, os.path.expanduser("~"),
                                  _documents_dir())


# name -> exact .als path of sets this server saved (Windows reads the folder
# off the Save dialog, so it knows exactly where a Save-As landed).
_SAVED_SET_PATHS = {}


def _find_saved_set(basename):
    """Best-effort absolute path of a just-saved set, or '' if not located.
    Ableton wraps a saved set as '<basename> Project/<basename>.als'."""
    known = _SAVED_SET_PATHS.get(basename)
    if known and os.path.exists(known):
        return known
    best, best_mtime = "", -1.0
    for root in _save_search_roots():
        cand = os.path.join(root, "%s Project" % basename, "%s.als" % basename)
        try:
            m = os.path.getmtime(cand)
        except OSError:
            continue
        if m > best_mtime:
            best, best_mtime = cand, m
    return best


def _save_as_impl(name, sleep=time.sleep):
    """Save the current set under `name` via Live's Save-As panel (File menu).
    Controls the NAME only — Ableton's panel saves to its last-used location and
    wraps the set in a '<name> Project' folder; arbitrary-directory navigation
    through the panel is not reliably scriptable. Returns a status dict; raises
    ValueError on a bad name / RuntimeError if no running Live is found."""
    if IS_WINDOWS:
        return _win_save_as_impl(name, sleep=sleep)
    basename = clean_set_name(name)                # raises ValueError if bad
    app, pid = _live_app_and_pid()
    if not app:
        raise RuntimeError("No running Ableton Live found on port %d." % LIVE_PORT)
    appname = _app_name(app)
    result = {"app": app, "name": basename}

    _osa('tell application "%s" to activate' % appname)
    sleep(0.4)
    baseline = _live_window_count()
    _click_file_menu("Save Live Set As...")
    if not _wait_until(lambda: _live_window_count() > baseline,
                       timeout=5.0, interval=0.4, sleep=sleep):
        result["saved"] = False
        result["error"] = ("Save-As panel did not appear (System Events may lack "
                            "Accessibility permission, or the screen is locked).")
        return result
    # The name field is focused on open — replace its default, then Save (Return).
    _osa('tell application "System Events" to keystroke "a" using {command down}')
    sleep(0.2)
    _keystroke(basename)
    sleep(0.3)
    for _ in range(4):
        _press_return()
        if _wait_until(lambda: _live_window_count() == baseline
                       and _live_window_title() == basename,
                       timeout=2.0, interval=0.4, sleep=sleep):
            result["saved"] = True
            path = _find_saved_set(basename)
            if path:
                result["path"] = path
            return result
    result["saved"] = False
    result["error"] = ("Save-As name entered but the title did not settle to %r — "
                       "Live may not have been frontmost; verify in Live." % basename)
    return result


def _save_set_impl(name="", sleep=time.sleep):
    """Save the current set. Empty `name` saves a TITLED set in place (File > Save
    Live Set); an Untitled set needs a name (routes to Save-As). A non-empty
    `name` always Saves-As under that name. Returns a status dict; raises
    ValueError/RuntimeError as _save_as_impl does."""
    if IS_WINDOWS:
        return _win_save_set_impl(name=name, sleep=sleep)
    app, pid = _live_app_and_pid()
    if not app:
        raise RuntimeError("No running Ableton Live found on port %d." % LIVE_PORT)
    appname = _app_name(app)
    title = _live_window_title()
    if name:
        return _save_as_impl(name, sleep=sleep)
    if is_untitled_title(title):
        return {"app": app, "saved": False, "untitled": True, "title": title,
                "error": ("Set is untitled (no file on disk). Pass a name "
                          "(save_set(name=...) or save_set_as) to save it.")}
    # Titled set: save in place via the menu (focus-independent, no Cmd+S needed).
    _osa('tell application "%s" to activate' % appname)
    sleep(0.4)
    baseline = _live_window_count()
    _click_file_menu("Save Live Set")
    sleep(0.6)
    # An unexpected panel means the title read mis-classified an untitled set.
    if _live_window_count() > baseline:
        _live_press_escape()
        return {"app": app, "saved": False, "title": title,
                "error": ("A save panel appeared on Save — the set looks untitled. "
                          "Use save_set(name=...) to give it a name.")}
    return {"app": app, "saved": True, "title": title}


def _restart_live_impl(save="discard", relaunch=True, wait_timeout=90.0,
                       dirty_after=5.0, sleep=time.sleep):
    """Gracefully quit (and optionally relaunch) the running Live. Returns a
    status dict; raises ValueError on a bad save policy / RuntimeError if no
    Live is found."""
    if IS_WINDOWS:
        return _win_restart_live_impl(save=save, relaunch=relaunch,
                                      wait_timeout=wait_timeout,
                                      dirty_after=dirty_after, sleep=sleep)
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
            # Return = Save (overwrites a set that already has a file). An
            # Untitled set instead pops a Save-As path panel this can't fill, so
            # the quit is reported failed — name/save such a set by hand first,
            # or use save_set/save_set_as before restarting.
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
            "panel needs a name (save it first via save_set_as), or System Events "
            "lacks Accessibility permission to answer the dialog.")
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
      for a set that already has a file — an Untitled set has no name and the
      quit is reported as failed, so save it first via save_set_as).
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
def save_set(ctx: Context, name: str = "") -> str:
    """Save the current Live set to disk (there is no LOM save API — this drives
    Live's save UI: via System Events on macOS, so Live must have Accessibility
    permission; via Live's menu and the Windows Save dialog on Windows. A
    Save-As briefly brings Live to the front).

    name: leave empty to save a TITLED set in place (File > Save Live Set; a
      no-op if clean). For an UNTITLED set you MUST pass a name (an empty call
      returns an error). A non-empty name always Saves-As under that name.
    The set is saved to Live's last-used save location (Ableton wraps it in a
    '<name> Project' folder unless that location is already inside a project);
    the tool controls the NAME, not the directory. A name may not contain '/'
    or ':' (on Windows, none of \\ / : * ? " < > | either).

    Returns JSON {ok, data:{saved, title|name, path?, untitled?, error?}}.
    'path' is the saved file: exact on Windows (read off the Save dialog),
    best-effort on macOS (it searches common save folders). Confirmation is by
    the window title; verify on disk if it matters.
    """
    try:
        data = _save_set_impl(name=name or "")
        return _ok(data)
    except (ValueError, RuntimeError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("save_set error: %s", e)
        return _err("save_set error: %s" % e)


@mcp.tool()
def save_set_as(ctx: Context, name: str) -> str:
    """Save the current Live set under a new NAME (File > Save Live Set As). Use
    for an Untitled set, or to save a copy under a new name. Drives Live's save
    UI (System Events on macOS - needs Accessibility permission; the Windows
    Save dialog on Windows) and briefly focuses Live. An existing file of the
    same name is replaced.

    name: the set name (not a path). Saved to Live's last-used save location,
      wrapped in a '<name> Project' folder unless that location is already
      inside a project - the tool controls the name, not the directory. A name
      may not contain '/' or ':' (on Windows, none of \\ / : * ? " < > |).

    Returns JSON {ok, data:{saved, name, path?, error?}}. 'path' is exact on
    Windows, best-effort on macOS; confirmation is by the window title.
    """
    try:
        data = _save_as_impl(name)
        return _ok(data)
    except (ValueError, RuntimeError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("save_set_as error: %s", e)
        return _err("save_set_as error: %s" % e)


# === Render / export ======================================================
# The LOM has no render/bounce/export API, so render_audio drives Live's Export
# Audio/Video dialog over Accessibility. Two hard constraints shape everything
# below (both verified against Live 12.4.2, see the design spec):
#   * The Render Start/Length sliders are UNWRITABLE (AXSetValue silently no-ops
#     and click-then-type is ignored), so the range is established BEFORE the
#     dialog opens: arrangement loop -> focus Arranger -> Edit > Select Loop,
#     which turns the loop into the time selection the dialog actually reads.
#   * Dialog toggles CLICK-TOGGLE, they do not set - so every toggle is read and
#     clicked only on a mismatch; a blind click inverts an already-correct one.

_EXPORT_WINDOW = "Export Audio/Video"
# The panel that asks for the file name after Export (macOS window name /
# Windows stock Save dialog title).
_SAVE_WINDOW = "Save Audio File As:" if IS_WINDOWS else "Save"
_EXPORT_MENU_ITEM = "Export Audio/Video..."
_RENDER_START_BAR = "Start of Rendered Sample (Bar)"
_RENDER_START_BEAT = "Start of Rendered Sample (Beat)"
_RENDER_START_16TH = "Start of Rendered Sample (Sixteenths)"
_RENDER_LENGTH_BAR = "Length of Rendered Sample (Bar)"
_RENDER_LENGTH_BEAT = "Length of Rendered Sample (Beat)"
_RENDER_LENGTH_16TH = "Length of Rendered Sample (Sixteenths)"
# Live writes AIFF as .aif on 12.4 but the extension is not contractual - accept
# both spellings rather than resolving to a null path on a good render.
_RENDER_EXT = {"WAV": ("wav",), "AIFF": ("aif", "aiff"),
               "FLAC": ("flac",), "MP3": ("mp3",)}
# The dialog's range boxes are quantised to 1/16, so a span that is not a whole
# number of sixteenths can be seeded up to one sixteenth away from the request.
_RANGE_TOL = 0.25 + 1e-6


def _rsleep(seconds):
    """Sleep seam for the render executor (patched out in tests)."""
    time.sleep(seconds)


def _click_edit_menu(item, proc=_LIVE_PROC):
    """Click a Live Edit-menu item by name (same focus-independent path as
    _click_file_menu)."""
    if IS_WINDOWS:
        _win.post_menu(_win_live()[1], "Edit", item)
        return
    _osa('tell application "System Events" to tell process "%s" to click '
         'menu item "%s" of menu 1 of menu bar item "Edit" of menu bar 1'
         % (proc, _as_literal(item)))


def _live_window_exists(title, proc=_LIVE_PROC):
    """True if Live currently has a window named `title`."""
    if IS_WINDOWS:
        pid = _win.listening_pid(LIVE_PORT)
        return bool(pid and _win.find_window(pid, title))
    out = _osa_get('tell application "System Events" to tell process "%s" to get '
                   '(count of (windows whose name is "%s"))'
                   % (proc, _as_literal(title)))
    try:
        return int(out) > 0
    except ValueError:
        return False


class _ExportUI:
    """Thin AX seam over the Export dialog. Every control is addressed by its AX
    `description` (the dialog's titles are all `missing value`)."""

    def _elem(self, kind, desc):
        return ('first %s of group 1 of window "%s" whose description is "%s"'
                % (kind, _EXPORT_WINDOW, _as_literal(desc)))

    def _tell(self, body):
        return ('tell application "System Events" to tell process "%s" to %s'
                % (_LIVE_PROC, body))

    def read_toggle(self, desc):
        return _osa_get(self._tell('get value of (%s)'
                                   % self._elem("button", desc)))

    def click_toggle(self, desc):
        _osa(self._tell('click (%s)' % self._elem("button", desc)))

    def read_popup(self, desc):
        # A pop-up's VALUE reads back clean ("WAV") - only the dropdown's item
        # names carry the selected-item check mark.
        return _osa_get(self._tell('get value of (%s)'
                                   % self._elem("pop up button", desc)))

    def _dropdown_prelude(self):
        # Live does NOT hang an AXMenu off the pop-up button ('menu 1 of <pop up
        # button>' raises "Invalid index" - it has zero menu children). The open
        # dropdown is a SEPARATE, UNNAMED window on the Live process, with the
        # AXMenuItems two AXGroups deep.
        #
        # An open dropdown leaves TWO unnamed windows behind, and only one of
        # them holds the items - but the empty one cannot be filtered out with a
        # compound `whose` clause: System Events' filter engine cannot evaluate
        # `(count of UI elements) > 0` and fails the whole query with -1700
        # ("Can't make 5 into type specifier"). So find it by iterating.
        return (
            '  set _dd to missing value\n'
            '  repeat with w in (every window whose name is "")\n'
            '    if (count of UI elements of w) > 0 then\n'
            '      set _dd to UI element 1 of UI element 1 of w\n'
            '      exit repeat\n'
            '    end if\n'
            '  end repeat\n'
            '  if _dd is missing value then return ""\n')

    def open_popup(self, desc):
        _osa(self._tell('click (%s)' % self._elem("pop up button", desc)))

    def menu_items(self):
        """Names of the open dropdown's items (in Live's order), [] if none."""
        out = _osa_get(
            'tell application "System Events"\n'
            ' tell process "%s"\n'
            '%s'
            '  set _items to {}\n'
            '  repeat with m in (menu items of _dd)\n'
            '    set end of _items to (name of m as text)\n'
            '  end repeat\n'
            '  set AppleScript\'s text item delimiters to (ASCII character 10)\n'
            '  return _items as text\n'
            ' end tell\n'
            'end tell' % (_LIVE_PROC, self._dropdown_prelude()))
        return [n for n in out.split("\n") if n.strip()]

    def click_menu_item(self, name):
        _osa(
            'tell application "System Events"\n'
            ' tell process "%s"\n'
            '%s'
            '  click (first menu item of _dd whose name is "%s")\n'
            ' end tell\n'
            'end tell' % (_LIVE_PROC, self._dropdown_prelude(), _as_literal(name)))

    def set_popup(self, desc, value):
        """Open the pop-up's dropdown and click the wanted item. Raises if the
        dropdown does not offer it (Escape first, so Live is not left with an
        open menu)."""
        self.open_popup(desc)
        _rsleep(0.3)
        names = self.menu_items()
        pick = choose_menu_item(names, value)
        if pick is None:
            _live_press_escape()
            raise RuntimeError(
                "The '%s' dropdown has no '%s' option (it offers: %s)."
                % (desc, value,
                   ", ".join(strip_menu_check(n) for n in names) or "nothing"))
        self.click_menu_item(pick)
        _rsleep(0.2)

    def read_slider(self, desc):
        out = _osa_get(self._tell('get value of (%s)'
                                  % self._elem("slider", desc)))
        try:
            return float(out)
        except ValueError:
            return None

    def press(self, desc):
        _osa(self._tell('click (%s)' % self._elem("button", desc)))


def _win_set_popup(ui, desc, value):
    """Windows ExportUI.set_popup: expand the ComboBox, pick the item from the
    unnamed dropdown window Live opens (UIA MenuItems, the selected one named
    '<x>, checked'), and collapse + raise if it isn't offered."""
    from ableton_mcp_max import win_uia
    combo = ui._get(desc, win_uia.COMBO)
    pid = _win.listening_pid(LIVE_PORT)
    before = set(h for h, _t, _c in _win.windows(pid))
    win_uia.expand(combo)
    items = []

    def _opened():
        for h, t, c in _win.windows(pid):
            if h in before or t or c != _win.LIVE_WINDOW_CLASS:
                continue
            found = win_uia.find_all(win_uia.element(h), win_uia.MENUITEM)
            if found:
                items[:] = found
                return True
        return False

    _wait_until(_opened, timeout=3.0, interval=0.15, sleep=_rsleep)
    names = [el.CurrentName for el in items]
    pick = choose_menu_item(names, value)
    if pick is None:
        try:
            win_uia.collapse(combo)
        except Exception:
            pass
        raise RuntimeError(
            "The '%s' dropdown has no '%s' option (it offers: %s)."
            % (desc, value,
               ", ".join(strip_menu_check(n) for n in names) or "nothing"))
    win_uia.invoke(items[names.index(pick)])
    _rsleep(0.2)


class _LazyWinExportUI:
    """Builds the UIA ExportUI on first use, so comtypes/UIA load only when a
    render actually runs - a UIA problem then fails render_audio alone, not
    the whole server at import."""
    _real = None

    def __getattr__(self, attr):
        if _LazyWinExportUI._real is None:
            from ableton_mcp_max import win_uia
            _LazyWinExportUI._real = win_uia.ExportUI(
                lambda: _win.find_window(_win.listening_pid(LIVE_PORT) or 0,
                                         _EXPORT_WINDOW),
                _win_set_popup)
        return getattr(_LazyWinExportUI._real, attr)


_export_ui = _LazyWinExportUI() if IS_WINDOWS else _ExportUI()


def _apply_toggles(toggles, ui):
    """Read each toggle and click ONLY on a mismatch (a click TOGGLES - blindly
    clicking a correct control inverts it). Returns the clicked descriptions."""
    clicked = []
    for t in toggles:
        desc, want = t["description"], t["want"]
        if ui.read_toggle(desc) != want:
            ui.click_toggle(desc)
            clicked.append(desc)
    return clicked


def _open_export_dialog():
    """Click File > Export Audio/Video... and wait for the dialog. False if it
    never appears."""
    _click_file_menu(_EXPORT_MENU_ITEM)
    return _wait_until(lambda: _live_window_exists(_EXPORT_WINDOW),
                       timeout=10.0, interval=0.4, sleep=_rsleep)


def _verify_export_range(ui, start_beats, length_beats, sig):
    """(ok, detail) for the range the dialog seeded itself with, checked in
    BEATS across all six range boxes - so a span that is not a whole number of
    bars (the whole-song default) is verified too."""
    if sig <= 0:
        return True, {"verified": False, "reason": "unknown time signature"}
    got = {d: ui.read_slider(d) for d in
           (_RENDER_START_BAR, _RENDER_START_BEAT, _RENDER_START_16TH,
            _RENDER_LENGTH_BAR, _RENDER_LENGTH_BEAT, _RENDER_LENGTH_16TH)}
    if any(v is None for v in got.values()):
        return True, {"verified": False, "reason": "range sliders unreadable"}
    # Start is displayed 1-based (bar 1 beat 1 sixteenth 1 == beat 0); length is
    # 0-based (0 bars 0 beats 1 sixteenth == one sixteenth long).
    got_start = ((got[_RENDER_START_BAR] - 1) * sig
                 + (got[_RENDER_START_BEAT] - 1)
                 + (got[_RENDER_START_16TH] - 1) * 0.25)
    got_length = (got[_RENDER_LENGTH_BAR] * sig
                  + got[_RENDER_LENGTH_BEAT]
                  + got[_RENDER_LENGTH_16TH] * 0.25)
    detail = {"verified": True,
              "start_beats": round(got_start, 4),
              "length_beats": round(got_length, 4),
              "want_start_beats": round(float(start_beats), 4),
              "want_length_beats": round(float(length_beats), 4)}
    ok = (abs(got_start - float(start_beats)) <= _RANGE_TOL
          and abs(got_length - float(length_beats)) <= _RANGE_TOL)
    return ok, detail


def _verify_dialog_state(ui, plan):
    """Descriptions whose value does not match the plan after we set it."""
    bad = []
    for t in plan["toggles"]:
        if ui.read_toggle(t["description"]) != t["want"]:
            bad.append(t["description"])
    for p in plan["popups"]:
        # popup_matches, not ==: Live 11 reports the main output as "Master"
        # where Live 12 says "Main".
        if not popup_matches(ui.read_popup(p["description"]), p["value"]):
            bad.append(p["description"])
    return bad


def _dialog_is_open():
    return (_live_window_exists(_EXPORT_WINDOW)
            or _live_window_exists(_SAVE_WINDOW))


def _dismiss_export_dialog(ui):
    """Best-effort: leave Live with NO modal export dialog up. While one is
    modal Live's main thread stops pumping scheduled messages, so any Remote
    Script command (the loop restore below) blocks for the full socket timeout
    and every later MCP call times out too - the dialog must go first. Returns
    True if nothing is left open."""
    for _ in range(3):
        if not _dialog_is_open():
            return True
        try:
            if _live_window_exists(_SAVE_WINDOW):
                if IS_WINDOWS:
                    pid = _win.listening_pid(LIVE_PORT)
                    _win.dialog_click(_win.find_window(pid, _SAVE_WINDOW),
                                      _win.IDCANCEL)
                else:
                    _live_press_escape()  # the Save panel has no AX Cancel
            else:
                ui.press("Cancel")
        except Exception as e:
            logger.error("render_audio: could not dismiss the dialog: %s", e)
            if IS_WINDOWS:
                # The dialog may already be closing; WM_CLOSE whatever is left
                # (equivalent to its Cancel).
                pid = _win.listening_pid(LIVE_PORT)
                for title in (_SAVE_WINDOW, _EXPORT_WINDOW):
                    h = _win.find_window(pid, title) if pid else None
                    if h:
                        _win.close(h)
            else:
                _live_press_escape()
        _rsleep(0.5)
    left = _dialog_is_open()
    if left:
        logger.error("render_audio: an export dialog is still open in Live.")
    return not left


_REPLACE_BUTTON = "Replace"


def _replace_sheet_open():
    """True if the Save panel is showing its '... already exists. Do you want to
    replace it?' sheet."""
    out = _osa_get('tell application "System Events" to tell process "%s" to get '
                   '(count of sheets of (first window whose name is "%s"))'
                   % (_LIVE_PROC, _SAVE_WINDOW))
    try:
        return int(out) > 0
    except ValueError:
        return False


def _confirm_replace_sheet():
    """Click the replace-confirmation sheet's Replace button. The sheet's buttons
    ARE AX-pressable and carry real NAMES (unlike the Save panel's, which has
    none) - so this is focus-independent, where a Return keystroke is not."""
    _osa('tell application "System Events" to tell process "%s" to click '
         '(first button of sheet 1 of (first window whose name is "%s") '
         'whose name is "%s")' % (_LIVE_PROC, _SAVE_WINDOW, _REPLACE_BUTTON))


def _mdfind_named(basename):
    try:
        out = subprocess.check_output(["/usr/bin/mdfind", "-name", basename],
                                      stderr=subprocess.DEVNULL, timeout=30)
        return out.decode("utf-8", "replace").splitlines()
    except Exception:
        return []


def _live_window_handles():
    """Windows: hwnds of Live's visible top-level windows (a snapshot taken
    before a render, so windows that were already open - plugin editors,
    Settings - never count as render windows)."""
    pid = _win.listening_pid(LIVE_PORT)
    return set(h for h, _t, _c in _win.windows(pid)) if pid else set()


def _render_finished(baseline=None):
    """True once the render's dialogs are all gone. On Windows also wait for
    any window that appeared since `baseline` (the render progress box) to
    close, so the file is complete before it is claimed."""
    if _live_window_exists(_EXPORT_WINDOW) or _live_window_exists(_SAVE_WINDOW):
        return False
    if IS_WINDOWS and baseline is not None:
        return not (_live_window_handles() - baseline)
    return True


def _render_candidates(basename, folder=None):
    """Paths that might be the render: Spotlight hits on macOS; on Windows the
    exact file in the Save dialog's folder, else a shallow walk of the usual
    export folders (no Spotlight there)."""
    if not IS_WINDOWS:
        return _mdfind_named(basename)
    if folder:
        return [os.path.join(folder, n) for n in os.listdir(folder)] \
            if os.path.isdir(folder) else []
    out = []
    for root in plat.render_search_roots(_os_name(), os.path.expanduser("~"),
                                         _documents_dir()):
        base_depth = root.rstrip("\\/").count(os.sep)
        for dirpath, dirnames, filenames in os.walk(root):
            if dirpath.count(os.sep) - base_depth >= 3:
                dirnames[:] = []
            out.extend(os.path.join(dirpath, f) for f in filenames
                       if f.lower().startswith(basename.lower() + "."))
    return out


def _resolve_render_path(basename, exts, since, folder=None):
    """Newest '<basename>.<ext>' (any ext in `exts`) modified at/after `since`,
    or ''. Spotlight, NOT a `find ~ -not -path "*/Library/*"` walk: Live renders
    into its last-used export directory, which is commonly iCloud Drive under
    ~/Library/Mobile Documents - such a walk silently misses the file. `since` is
    taken before the dialog opens, so a same-named file older than it is a stale
    leftover and must not be claimed. On Windows `folder` is the directory the
    Save dialog showed, read before saving."""
    want = set(("%s.%s" % (basename, e)).lower() for e in exts)
    best, best_mtime = "", -1.0
    for path in _render_candidates(basename, folder):
        if os.path.basename(path).lower() not in want:
            continue
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if mtime < since or mtime <= best_mtime:
            continue
        best, best_mtime = path, mtime
    return best


def _file_stats(path):
    """(bytes, duration_s) for a rendered file; duration only for PCM formats
    the stdlib can read."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return None, None
    duration = None
    try:
        import wave
        with wave.open(path, "rb") as w:
            rate = w.getframerate()
            if rate:
                duration = round(w.getnframes() / float(rate), 3)
    except Exception:
        duration = None
    return size, duration


def _render_audio_impl(name, start_bar=None, end_bar=None, file_type="WAV",
                       bit_depth=24, sample_rate=44100, normalize=False,
                       mp3=False, mono=False,
                       analysis_file=True, dither="No Dither", timeout=600.0):
    basename = clean_render_name(                  # raises ValueError if bad
        name, illegal=plat.illegal_name_chars(_os_name()))
    plan = plan_export(file_type=file_type, bit_depth=bit_depth,
                       sample_rate=sample_rate, normalize=normalize, mp3=mp3,
                       mono=mono,
                       analysis_file=analysis_file, dither=dither)
    app, _pid = _live_app_and_pid()
    if not app:
        raise RuntimeError("No running Ableton Live found on port %d." % LIVE_PORT)

    ableton = get_ableton_connection()
    transport = ableton.send_command("get_transport") or {}
    sig = int(transport.get("signature_numerator", 4) or 4)
    song_length = float(transport.get("song_length", 0.0) or 0.0)
    start_beats, length_beats = loop_range_for(start_bar, end_bar,
                                               song_length, sig)
    # The loop brace is user-visible state we are about to overwrite; restore it
    # on EVERY exit path.
    prior_loop = {"enabled": bool(transport.get("loop", False)),
                  "start": float(transport.get("loop_start", 0.0) or 0.0),
                  "length": float(transport.get("loop_length", 4.0) or 4.0)}
    try:
        return _render_with_dialog(ableton, app, basename, plan, sig,
                                   start_beats, length_beats, start_bar,
                                   end_bar, timeout)
    finally:
        # Dismiss BEFORE restoring: a still-open modal dialog would block the
        # loop restore for the Remote Script's whole socket timeout and then
        # swallow the failure. Never let either step overwrite the real result.
        try:
            _dismiss_export_dialog(_export_ui)
        except Exception as e:
            logger.error("render_audio: dialog cleanup failed: %s", e)
        try:
            ableton.send_command("set_arrangement_loop", prior_loop)
        except Exception as e:
            logger.error("render_audio: could not restore the loop: %s", e)


def _render_with_dialog(ableton, app, basename, plan, sig, start_beats,
                        length_beats, start_bar, end_bar, timeout):
    # The dialog reads the arrangement TIME SELECTION, and its own range sliders
    # cannot be written - so seed the range here, before it opens.
    ableton.send_command("set_arrangement_loop",
                         {"enabled": True, "start": start_beats,
                          "length": length_beats})
    ableton.send_command("focus_view", {"view": "Arranger"})
    appname = _app_name(app)
    if IS_WINDOWS:
        # Select Loop acts on Live's focused view: with another Live window in
        # front (Settings, a plugin editor) it silently does nothing and the
        # dialog seeds a 1/16 range. Bring the SET window to the front first.
        _win.activate(_win_live()[1])
    else:
        _osa('tell application "%s" to activate' % appname)
    _rsleep(0.4)
    _click_edit_menu("Select Loop")
    _rsleep(0.3)

    since = time.time()
    baseline = _live_window_handles() if IS_WINDOWS else None
    if not _open_export_dialog():
        if IS_WINDOWS:
            return _err("The Export Audio/Video dialog did not appear (another "
                        "dialog may be open in Live).")
        return _err("The Export Audio/Video dialog did not appear (System Events "
                    "may lack Accessibility permission, or the screen is locked).")

    ui = _export_ui
    ok, range_detail = _verify_export_range(ui, start_beats, length_beats, sig)
    if not ok:
        ui.press("Cancel")
        return _err("The Export dialog seeded the wrong range (%s) - not "
                    "rendering. Check that the Arrangement view is reachable and "
                    "that Edit > Select Loop is enabled." % range_detail)

    # Toggles FIRST: with Encode PCM off, the File Type / Recording Bit Depth /
    # Dither popups are disabled and setting them silently no-ops.
    clicked = _apply_toggles(plan["toggles"], ui)
    for popup in plan["popups"]:
        try:
            ui.set_popup(popup["description"], popup["value"])
        except Exception as e:
            ui.press("Cancel")
            return _err("%s - cancelled without rendering." % e)

    bad = _verify_dialog_state(ui, plan)
    if bad:
        ui.press("Cancel")
        return _err("The Export dialog would not accept: %s - cancelled without "
                    "rendering." % ", ".join(bad))

    ui.press("Export")
    if not _wait_until(lambda: _live_window_exists(_SAVE_WINDOW),
                       timeout=15.0, interval=0.4, sleep=_rsleep):
        return _err("Export was pressed but the Save panel never appeared.",
                    rendered=False)

    folder = None
    if IS_WINDOWS:
        # Stock Windows Save dialog: read its target folder off the address
        # bar (so the result path is exact, no search), type the name and
        # press Save. An overwrite prompt is confirmed below.
        pid = _win.listening_pid(LIVE_PORT)
        dlg = _win.find_window(pid, _SAVE_WINDOW)
        folder = _win.file_dialog_folder(dlg) or None
        _win.file_dialog_save(dlg, basename)
        _wait_until(lambda: not _live_window_exists(_SAVE_WINDOW)
                    or _win_confirm_overwrite(pid),
                    timeout=5.0, interval=0.5, sleep=_rsleep)
    else:
        # The Save panel has no AX-pressable Save button: confirm by typing
        # the name and pressing Return (the _save_as_impl pattern).
        _osa('tell application "%s" to activate' % appname)
        _rsleep(0.3)
        _osa('tell application "System Events" to keystroke "a" using {command down}')
        _rsleep(0.2)
        _keystroke(basename)
        _rsleep(0.3)
        _press_return()
        # Re-rendering an existing name raises a '"x.wav" already exists. Do you
        # want to replace it?' sheet. It is a SHEET OF THE SAVE PANEL (not of
        # the Export dialog), and Return does NOT confirm it - but unlike the
        # Save panel itself it has real AX buttons, addressable by NAME. Click
        # "Replace" outright; a blind Return loop here hangs to the render
        # timeout with the sheet up.
        _wait_until(lambda: not _live_window_exists(_SAVE_WINDOW)
                    or _replace_sheet_open(),
                    timeout=5.0, interval=0.5, sleep=_rsleep)
        if _replace_sheet_open():
            _confirm_replace_sheet()

    done = _wait_until(lambda: _render_finished(baseline), timeout=timeout,
                       interval=1.0, sleep=_rsleep)
    if not done:
        return _err("The render did not finish within %ss (the Export/Save "
                    "windows are still open). No file is claimed; check Live."
                    % timeout, rendered=False)

    primary_exts = (_RENDER_EXT[plan["file_type"]] if plan["pcm"]
                    else _RENDER_EXT["MP3"])

    def _resolve(exts):
        if folder is not None:      # Windows: the dialog told us the folder
            return _resolve_render_path(basename, exts, since, folder=folder)
        return _resolve_render_path(basename, exts, since)

    # Spotlight does not index the file the instant Live closes it, so a single
    # mdfind right after the render loses the race and reports path=null for a
    # file that is sitting on disk. Poll briefly.
    _wait_until(lambda: bool(_resolve(primary_exts)),
                timeout=15.0, interval=1.0, sleep=_rsleep)
    path = _resolve(primary_exts)
    extra = []
    if plan["pcm"] and plan["mp3"]:
        _wait_until(lambda: bool(_resolve(_RENDER_EXT["MP3"])),
                    timeout=15.0, interval=1.0, sleep=_rsleep)
        mp3_path = _resolve(_RENDER_EXT["MP3"])
        if mp3_path:
            extra.append(mp3_path)
    size, duration = _file_stats(path) if path else (None, None)

    return _ok({
        "name": basename,
        "path": path or None,
        "extra_paths": extra,
        "bytes": size,
        "duration_s": duration,
        "file_type": plan["file_type"],
        "bit_depth": int(plan["bit_depth"]),
        "sample_rate": int(plan["sample_rate"]),
        "pcm": plan["pcm"],
        "mp3": plan["mp3"],
        "range": {"start_bar": start_bar, "end_bar": end_bar},
        "toggles_clicked": clicked,
        "range_check": range_detail,
        "rendered": True,
    })


@mcp.tool()
def render_audio(ctx: Context, name: str, start_bar: Optional[int] = None,
                 end_bar: Optional[int] = None, file_type: str = "WAV",
                 bit_depth: int = 24, sample_rate: int = 44100,
                 normalize: bool = False, mp3: bool = False, mono: bool = False,
                 analysis_file: bool = True,
                 dither: str = "No Dither", timeout: float = 600.0) -> str:
    """Bounce the set's Main output to an audio file on disk (there is no LOM
    render API - this drives Live's Export Audio/Video dialog: via System
    Events on macOS, so Live needs Accessibility permission; via UI Automation
    and the Windows Save dialog on Windows. It briefly focuses Live and switches
    it to the Arrangement view).

    name: the file name (not a path; may not contain '/' or ':', and on Windows
      none of \\ / : * ? " < > |). Re-using a name overwrites the existing file
      (the Replace prompt is confirmed).
    start_bar / end_bar: 1-based bar range, end EXCLUSIVE (5..13 = 8 bars). Pass
      neither to render the whole song. The range is applied by setting the
      arrangement loop and selecting it - the dialog's own range sliders are not
      writable. The loop brace is restored afterwards, but Live is LEFT IN THE
      ARRANGEMENT VIEW and the arrangement TIME SELECTION is left on the rendered
      range (the LOM cannot restore a time selection).
    file_type: WAV | AIFF | FLAC | MP3. bit_depth: 16 | 24 | 32.
    sample_rate: 44100 | 48000 | 88200 | 96000 | 176400 | 192000.
    mp3: also emit an MP3 alongside a PCM file_type.
    Return and Main effects are always included: this bounces the Main output,
      whose signal contains them by definition (Live disables that option here).
    dither: No Dither | Triangular | Rectangular | POW-r 1 | POW-r 2 | POW-r 3.
    timeout: seconds to wait for the render to finish (a full track takes real
      time; the tool polls, it never sleeps a fixed amount).

    The output DIRECTORY is Live's last-used export location and is not
    controllable. On Windows 'path' is exact (the folder is read off the Save
    dialog). On macOS it is resolved afterwards via Spotlight and may be null
    even on a successful render (the file exists, we just could not locate it).

    Returns JSON {ok, data:{name, path, extra_paths, bytes, duration_s,
    file_type, bit_depth, sample_rate, range, rendered}}.
    """
    try:
        return _render_audio_impl(
            name, start_bar=start_bar, end_bar=end_bar, file_type=file_type,
            bit_depth=bit_depth, sample_rate=sample_rate, normalize=normalize,
            mp3=mp3, mono=mono,
            analysis_file=analysis_file, dither=dither, timeout=timeout)
    except (ValueError, RuntimeError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("render_audio error: %s", e)
        return _err("render_audio error: %s" % e)


# === Arrangement-timeline automation (#30) ============================== #
# The LOM cannot write arrangement automation, so set_arrangement_automation
# patches the saved .als and reloads Live in place. Targeting is by value PROBE
# (set the param to a unique sentinel, read it back, locate the matching
# <Manual> in the XML -> its AutomationTarget Id). See als_automation_utils.

def _live_log_path():
    """Path to the running Live version's Log.txt (best-effort: latest version
    directory under ~/Library/Preferences/Ableton; on Windows the running
    version's %APPDATA%\\Ableton\\Live x.y.z\\Preferences)."""
    if IS_WINDOWS:
        dirs = _win_pref_dirs()
    else:
        dirs = sorted(glob.glob(os.path.join(_prefs_base(), "Live *")))
    for d in reversed(dirs):
        cand = os.path.join(d, "Log.txt")
        if os.path.exists(cand):
            return cand
    return ""


def _current_set_path(title=None):
    """Resolve the absolute .als path of the currently-open set by parsing the
    last `Loading document "<...>.als"` line in Live's Log.txt that exists on
    disk and isn't a factory default (under the .app bundle). When `title` is
    given, require the file's basename to match it. '' if unresolved.

    This is more reliable than guessing from common save folders (handles /tmp
    and arbitrary directories) and reads the path Live actually loaded (so it
    sidesteps the iCloud stale-copy trap)."""
    log = _live_log_path()
    if not log:
        return ""
    try:
        with open(log, "r", encoding="utf-8", errors="replace") as f:
            data = f.read()
    except OSError:
        return ""
    best = ""
    for m in re.finditer(r'Loading document "([^"]+\.als)"', data):
        p = m.group(1)
        if plat.is_factory_set_path(sys.platform, p):   # factory default set
            continue
        if title and set_name_from_path(p) != title:
            continue
        if os.path.exists(p):
            best = p                     # later (more recent) matches win
    return best


def _open_file(path):
    """Open a file with its default app (Live for .als). Seam for tests."""
    if IS_WINDOWS:
        _win.open_file(path)
        return
    subprocess.run(["/usr/bin/open", path], check=False)


def _new_set_keystroke():
    """Cmd+N — start a new (empty) Live set, closing the current one. Seam."""
    _osa('tell application "System Events" to keystroke "n" using {command down}')


def _reload_set(path, set_name, settle=0.6, timeout=30.0, sleep=time.sleep,
                probe=None):
    """Reload `path` in place: Cmd+N (new set, closes the current) then
    `open <path>`. Waits until the front window title == set_name and an optional
    probe read succeeds (absorbing the one `None.None(Song)` stale-handle error
    the reload causes). No app quit. Returns {reloaded, title}.

    Dialog handling: the caller saves the set first, so it's clean -> Cmd+N pops
    only Live's "this action will stop audio, proceed?" confirmation (the audio
    engine is active), whose default (Return) PROCEEDS. We must NOT press Cmd+D
    here (that's the SAVE dialog's Don't-Save, which won't appear on a clean set;
    and Return on a save dialog would mean Save, overwriting our patched .als).
    After Cmd+N proceeds, Live sits on a silent blank set, so the subsequent
    `open` loads with no stop-audio prompt.

    Windows: File > New Live Set is posted to the menu. If Live still asks to
    save, the answer is No - the patched .als on disk is what must load, and
    saving the in-memory set would overwrite the patch. Any other prompt (e.g.
    a stop-audio confirmation) is accepted with its OK/Yes."""
    if IS_WINDOWS:
        return _win_reload_set(path, set_name, settle=settle, timeout=timeout,
                               sleep=sleep, probe=probe)
    app, pid = _live_app_and_pid()
    if not app:
        raise RuntimeError("No running Ableton Live found on port %d." % LIVE_PORT)
    name = _app_name(app)
    _osa('tell application "%s" to activate' % name)
    sleep(0.4)
    baseline = _live_window_count()
    _new_set_keystroke()
    sleep(settle)
    # Proceed through the stop-audio confirmation (Return = default = proceed).
    for _ in range(3):
        if _live_window_count() <= baseline:
            break
        _osa('tell application "%s" to activate' % name)
        _press_return()
        sleep(settle)
    _open_file(path)

    def _ready():
        if _live_window_title() != set_name:
            return False
        if probe is None:
            return True
        try:
            probe()
            return True
        except Exception:
            return False

    ok = _wait_until(_ready, timeout=timeout, interval=1.0, sleep=sleep)
    return {"reloaded": bool(ok), "title": _live_window_title()}


# A distinctive irrational-ish base fraction per lane, very unlikely to collide
# with a real default <Manual> value (which tend to be round or factory presets).
_PROBE_BASE = 0.6376168291
_PROBE_STEP = 0.0173962041


def _probe_fraction(i):
    """A unique fraction in (0, 1) for lane i."""
    f = (_PROBE_BASE + i * _PROBE_STEP) % 1.0
    # keep clear of the exact 0/1 edges
    return min(0.999, max(0.001, f))


def _arr_auto_impl(ableton, lanes, reload, save_impl, reload_impl,
                   read_als=als.read_als, write_als=als.write_als):
    """Core of set_arrangement_automation, factored behind seams (save_impl,
    reload_impl, read/write) so it is unit-testable without Live. Mutates the
    on-disk .als; returns the result dict."""
    title = _live_window_title()
    if is_untitled_title(title):
        raise ValueError("Set is untitled — save it first via save_set_as, then "
                         "retry (arrangement automation patches the .als on disk).")
    # Resolve from Live's log (handles arbitrary dirs); fall back to a common-root
    # search for a set that was Save-As'd this session (no "Loading document" line).
    path = _current_set_path(title) or _find_saved_set(title)
    if not path:
        raise RuntimeError(
            "Could not resolve the current set's .als path from Live's log or the "
            "common save folders. Open/save the set so it's a real file on disk.")
    set_name = set_name_from_path(path)

    results = []
    probes = []   # (lane_idx, readback_value, first_value, vmin, vmax, points, replace)
    for i, lane in enumerate(lanes):
        r = {"track_index": lane.get("track_index"),
             "device_index": lane.get("device_index", 0),
             "parameter": lane.get("parameter"),
             "ok": False}
        try:
            ti = int(lane["track_index"])
            di = int(lane.get("device_index", 0))
            param = lane["parameter"]
            points = lane["points"]
            if not points:
                raise ValueError("lane has no points")
            tt = lane.get("track_type", "regular")
            info = ableton.send_command(
                "get_device_parameters",
                {"track_index": ti, "device_index": di, "track_type": tt})
            params = info.get("parameters", [])
            pidx = resolve_parameter_index(params, param)
            pinfo = params[pidx]
            if pinfo.get("is_quantized"):
                raise ValueError("parameter %r is quantized — not supported in v1 "
                                 "(continuous params and macros only)" % param)
            vmin = pinfo.get("min")
            vmax = pinfo.get("max")
            if vmin is None or vmax is None or vmin == vmax:
                raise ValueError("parameter %r has no usable [min,max] range" % param)
            sentinel = vmin + _probe_fraction(i) * (vmax - vmin)
            ableton.send_command(
                "set_device_parameter",
                {"track_index": ti, "device_index": di, "parameter_index": pidx,
                 "value": sentinel, "track_type": tt})
            # Read back the value Live actually stored (it may round).
            info2 = ableton.send_command(
                "get_device_parameters",
                {"track_index": ti, "device_index": di, "track_type": tt})
            readback = info2.get("parameters", [])[pidx].get("value")
            first_value = float(points[0]["value"])
            probes.append({"lane": i, "track_index": ti, "device_index": di,
                           "param_index": pidx, "track_type": tt,
                           "readback": readback, "first_value": first_value,
                           "vmin": vmin, "vmax": vmax, "points": points,
                           "replace": bool(lane.get("replace", True)),
                           "result": r})
            r["param_index"] = pidx
        except Exception as e:
            r["error"] = str(e)
        results.append(r)

    if not probes:
        return {"set_path": path, "reloaded": False, "lanes": results,
                "error": "no resolvable lanes"}

    # ONE save flushes every probed sentinel to disk; then resolve all targets.
    save_res = save_impl()
    if not save_res.get("saved"):
        return {"set_path": path, "reloaded": False, "lanes": results,
                "error": "save_set failed: %s" % save_res.get("error", save_res)}

    xml = read_als(path)
    to_inject = []
    for pr in probes:
        r = pr["result"]
        try:
            tgt = read_target_after_manual_safe(xml, pr["readback"])
            pr["pointee_id"] = tgt["pointee_id"]
            pr["manual_literal"] = tgt["manual_literal"]
            r["pointee_id"] = tgt["pointee_id"]
            to_inject.append(pr)
        except Exception as e:
            r["error"] = "target resolve failed: %s" % e

    if not to_inject:
        return {"set_path": path, "reloaded": False, "lanes": results,
                "error": "no targets resolved"}

    # Apply all envelope injections + Manual patch-backs to the XML. FloatEvent
    # Ids are allocated from Live's global <NextPointeeId> pool (Live 12 rejects
    # the set as corrupt if any FloatEvent lacks an Id); the counter is bumped at
    # the end so Live won't reuse them.
    next_id = als.next_pointee_id(xml)
    for pr in to_inject:
        r = pr["result"]
        pid = pr["pointee_id"]
        pts = pr["points"]
        vmin, vmax = pr["vmin"], pr["vmax"]
        first_event_id = next_id
        next_id += len(pts) + 1            # +1 for the leading sentinel event
        xml = als.inject_envelope(
            xml, pr["track_index"], pid,
            lambda eid, pts=pts, pid=pid, vmin=vmin, vmax=vmax, feid=first_event_id:
                als.build_envelope_xml(pid, pts, eid, feid,
                                       value_min=vmin, value_max=vmax),
            replace=pr["replace"])
        xml = als.patch_manual(xml, pr["manual_literal"], pr["first_value"],
                               value_min=vmin, value_max=vmax)
        r["ok"] = True
        r["points_written"] = len(pts)

    xml = als.set_next_pointee_id(xml, next_id)
    write_als(path, xml)

    reloaded = False
    if reload:
        rr = reload_impl(path, set_name)
        reloaded = rr.get("reloaded", False)
    else:
        # Leave Live's in-memory knobs at the first-point value (not the probe
        # sentinel) so the set looks right until the user reloads. The envelope
        # itself is only on disk until then.
        for pr in to_inject:
            try:
                ableton.send_command(
                    "set_device_parameter",
                    {"track_index": pr["track_index"], "device_index": pr["device_index"],
                     "parameter_index": pr["param_index"], "value": pr["first_value"],
                     "track_type": pr["track_type"]})
            except Exception:
                pass

    return {"set_path": path, "reloaded": reloaded, "lanes": results}


def read_target_after_manual_safe(xml, value):
    """Thin wrapper so the impl can be monkeypatched in tests."""
    return als.find_target_after_manual(xml, value)


@mcp.tool()
def set_arrangement_automation(
    ctx: Context,
    lanes: List[Dict[str, Any]],
    reload: bool = True,
) -> str:
    """Write Arrangement-timeline automation (device-parameter / rack-macro
    breakpoint envelopes bound to song position) by patching the set's .als file
    and reloading Live in place. This is the ONLY way to author arrangement
    automation — the LOM cannot (clip envelopes are session-only).

    The set MUST be saved to a real file first (an Untitled set errors — use
    save_set_as). Live is briefly focused (System Events on macOS) for the in-place
    reload, and the open set is reloaded from disk (~5s); one MCP call right
    after may transiently fail and self-heal.

    lanes: list of automation lanes, each a dict:
      - track_index (int): the OWNING track (regular Midi/Audio, document order).
      - device_index (int, default 0): device on that track.
      - parameter (int|str): parameter index or name (case-insensitive). Macros
        are addressed by their parameter name ("Macro 1", etc.).
      - track_type (str, default 'regular'): 'regular' | 'return' | 'master'.
      - points (list[{time, value}]): breakpoints. time in BEATS; value in the
        parameter's NATIVE units (clamped to its range). >=1 required; sorted
        automatically; duplicate times = a vertical step.
      - replace (bool, default True): replace any existing arrangement envelope
        for this parameter (idempotent rewrites).
    reload: reload the set in place when done (default True). False leaves the
      patched envelope on disk only (reload Live yourself to see it).

    Targeting uses a VALUE PROBE: each param is briefly set to a unique sentinel,
    the set is saved, and the matching value in the .als locates the parameter —
    so it works for macros, native params, nested-in-rack params, and AU/VST
    plugins alike. Quantized (stepped) params are NOT supported in v1.

    Returns JSON {ok, data:{set_path, reloaded, lanes:[{track_index,
    device_index, parameter, pointee_id?, points_written?, ok, error?}]}}.
    A lane that can't be resolved is reported ok:false and skipped; siblings
    still apply.
    """
    try:
        if not lanes:
            return _err("lanes must be a non-empty list")
        ableton = get_ableton_connection()
        data = _arr_auto_impl(
            ableton, lanes, reload,
            save_impl=lambda: _save_set_impl(name=""),
            reload_impl=lambda p, n: _reload_set(
                p, n, probe=lambda: get_ableton_connection().send_command(
                    "get_session_info")),
        )
        return _ok(data)
    except (ValueError, RuntimeError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("set_arrangement_automation error: %s", e)
        return _err("set_arrangement_automation error: %s" % e)


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
def focus_view(ctx: Context, view: str = "Arranger") -> str:
    """
    Show and focus one of Live's main views: "Arranger" (default) or "Session".

    Deterministic, unlike the View menu's Toggle item - some commands are only
    available in one view (Edit > Select Loop, which render_audio relies on,
    is disabled in Session view).
    """
    try:
        v = (view or "Arranger").strip()
        if v not in ("Arranger", "Session"):
            return _err(f"view must be 'Arranger' or 'Session' (got {view!r}).")
        ableton = get_ableton_connection()
        result = ableton.send_command("focus_view", {"view": v})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error focusing view: {str(e)}")
        return _err(f"Error focusing view: {str(e)}")
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
def probe_plugin_parameters(
    ctx: Context, track_index: int, device_index: int, track_type: str = "regular"
) -> str:
    """
    Read the FULL parameter-name list of a third-party VST/AU plugin device
    (e.g. Serum 2) - the names Live can Configure, not just the automatable
    subset visible in get_device_parameters.

    A freshly loaded plugin exposes only 'Device On' as a LOM DeviceParameter;
    its real knobs are reachable only after they are 'Configured'. This probe
    returns every parameter name the plugin reports, so a param-map pack can be
    generated and used to expose a chosen subset via expose_plugin_parameters.

    Parameters:
    - track_index: index of the track (ignored for master)
    - device_index: index of the plugin device on that track (0 = first device)
    - track_type: 'regular' (default), 'return', or 'master'

    Returns JSON: device_name, class_name, parameter_count, names (ordered list;
    the Configure-slot id for names[i] is id_base + i), bank_indices.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "probe_plugin_parameters",
            {
                "track_index": track_index,
                "device_index": device_index,
                "track_type": track_type,
            },
        )
        return _ok(result)
    except Exception as e:
        logger.error(f"Error probing plugin parameters: {str(e)}")
        return _err(f"Error probing plugin parameters: {str(e)}")


# Default Manual value written into a freshly-exposed Configure slot. Live
# reconciles it against the plugin's real parameter range/value on load, so a
# neutral mid-point is a safe placeholder (the plugin's own ProcessorState chunk,
# stored separately in the .als, is the source of truth for the actual sound).
_EXPOSE_DEFAULT_MANUAL = "0.5"


def _expose_plugin_impl(track_index, device_index, track_type, params, manual,
                        reload, save_impl, reload_impl,
                        read_als=als.read_als, write_als=als.write_als,
                        find_track_span=als.find_track_span,
                        title_fn=None, resolve_path=None):
    """Core of expose_plugin_parameters, factored behind seams (save/reload/IO)
    so it is unit-testable without Live. Saves the set, patches the target
    plugin device's <ParameterList> with the pack params (filling empty Configure
    slots + allocating target ids from <NextPointeeId>), writes the .als, and
    reloads. Returns the result dict."""
    if track_type == "regular":
        _span = lambda x: find_track_span(x, track_index)
    elif track_type == "return":
        _span = lambda x: als.find_return_track_span(x, track_index)
    elif track_type == "master":
        _span = lambda x: als.find_master_track_span(x)
    else:
        raise ValueError("track_type must be regular, return, or master")
    title = (title_fn or _live_window_title)()
    if is_untitled_title(title):
        raise ValueError("Set is untitled — save it first via save_set_as, then "
                         "retry (exposure patches the .als on disk).")

    save_res = save_impl()
    if not save_res.get("saved"):
        return {"reloaded": False, "exposed_count": 0,
                "dropped_count": len(params), "method": "live_set",
                "error": "save_set failed: %s" % save_res.get("error", save_res)}

    path = (resolve_path or (lambda: _current_set_path(title) or
                             _find_saved_set(title)))()
    if not path:
        raise RuntimeError(
            "Could not resolve the current set's .als path from Live's log or the "
            "common save folders. Open/save the set so it's a real file on disk.")
    set_name = set_name_from_path(path)

    xml = read_als(path)
    # Count how many params will actually fit (empty slots in the target list).
    ts, te = _span(xml)
    pl_s, pl_e = pcu.locate_param_list(xml, ts, te, device_index)
    n_empty = len(pcu.find_empty_slots(xml[pl_s:pl_e]))
    n_filled_existing = pcu.count_slots(xml[pl_s:pl_e]) - n_empty
    count = min(len(params), n_empty)
    if count == 0:
        return {"set_path": path, "reloaded": False, "exposed_count": 0,
                "dropped_count": len(params), "method": "live_set",
                "error": "no empty Configure slots on device %d (all %d slots "
                         "already configured)" % (device_index,
                                                  pcu.count_slots(xml[pl_s:pl_e]))}

    # Allocate the 2 target ids per slot from <NextPointeeId> (Live rejects the
    # set if any target id >= NextPointeeId). The bump rewrites one token, which
    # can shift offsets, so re-locate the list on the bumped doc before filling.
    xml, start_id = pcu.bump_next_pointee_id(xml, count)
    ts, te = _span(xml)
    pl_s, pl_e = pcu.locate_param_list(xml, ts, te, device_index)

    fill_params = []
    for i, p in enumerate(params):
        fill_params.append({
            "param_id": int(p["param_id"]),
            "name": p["name"],
            "manual": manual,
            "visual_index": n_filled_existing + i,
        })
    new_plist, dropped = pcu.fill_slots(xml[pl_s:pl_e], fill_params, start_id)
    xml = xml[:pl_s] + new_plist + xml[pl_e:]
    write_als(path, xml)

    reloaded = False
    if reload:
        rr = reload_impl(path, set_name)
        reloaded = rr.get("reloaded", False)

    return {"set_path": path, "reloaded": reloaded,
            "exposed_count": count, "dropped_count": dropped,
            "method": "live_set"}


@mcp.tool()
def expose_plugin_parameters(
    ctx: Context,
    track_index: int,
    device_index: int = 0,
    pack: str = "serum2",
    track_type: str = "regular",
    reload: bool = True,
) -> str:
    """Expose a third-party VST/AU plugin's parameters as live, settable LOM
    DeviceParameters by Configuring them via the .als backdoor.

    A freshly loaded plugin (e.g. Serum 2) exposes ONLY 'Device On' to the LOM;
    its real knobs become controllable only after they are 'Configured', and Live
    has no API for that. This tool fills the plugin device's empty Configure slots
    from a committed param-map pack, then reloads the set in place. Afterward the
    exposed params are reachable by the normal get_device_parameters /
    set_device_parameter (and automatable / arrangement-automatable).

    The set MUST be saved to a real file first (an Untitled set errors — use
    save_set_as). Live is briefly focused for the in-place reload (~5s); one MCP
    call right after may transiently fail and self-heal. Regular tracks only in v1
    (VST/AU instruments load on regular tracks).

    Parameters:
    - track_index: the track holding the plugin (regular Midi/Audio, doc order).
    - device_index: device on that track (0 = first). Must be the VST/AU plugin.
    - pack: param-map pack name under param_maps/ (default 'serum2'); its params
      (each a real plugin ParameterId + name) fill the Configure slots, capped at
      the 128-slot pool — any overflow is dropped and reported.
    - track_type: 'regular' only in v1.
    - reload: reload the set in place when done (default True). False leaves the
      patched .als on disk (reload Live yourself to see the exposed params).

    Returns JSON {ok, data:{set_path, exposed_count, dropped_count, method,
    reloaded, error?}}. exposed_count is how many params were Configured (fit in
    the empty slots); dropped_count is pack params that didn't fit.
    """
    try:
        loaded = pmu.load_pack(pack)
        ableton = get_ableton_connection()  # ensure Live is reachable before save
        data = _expose_plugin_impl(
            track_index, device_index, track_type, loaded["params"],
            _EXPOSE_DEFAULT_MANUAL, reload,
            save_impl=lambda: _save_set_impl(name=""),
            reload_impl=lambda p, n: _reload_set(
                p, n, probe=lambda: get_ableton_connection().send_command(
                    "get_session_info")),
        )
        if data.get("dropped_count"):
            logger.warning("expose_plugin_parameters: dropped %d params (slot pool "
                           "full)", data["dropped_count"])
        return _ok(data)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("expose_plugin_parameters error: %s", e)
        return _err("expose_plugin_parameters error: %s" % e)


@mcp.tool()
def get_ozone_modules(ctx: Context, track_index: int, device_index: int = 0,
                      track_type: str = "master") -> str:
    """List an Ozone 12 instance's modules with exposed/bypassed state.

    Reads the device's currently-exposed LOM params (get_device_parameters) and
    reports, per Ozone module, whether any of its params are exposed and whether
    its Bypass is engaged. Ozone 12 lives on the master by default.
    """
    try:
        pack = _ozcat.load()
        conn = get_ableton_connection()
        dp = conn.send_command("get_device_parameters", {
            "track_index": track_index, "device_index": device_index,
            "track_type": track_type})
        exposed_names = {p["name"] for p in dp.get("parameters", [])}
        bypassed = {}
        for p in dp.get("parameters", []):
            info = _oz.parse_param_name(p["name"])
            if info["module"] and info["role"] == "bypass":
                # Prefer the module-level (section=None) bypass -- that's the one
                # set_ozone_module_enabled writes. A per-section bypass (EQ has
                # stereo_main/aux) must not overwrite it, else the summary can
                # disagree with the module-level enable state.
                if info["section"] is None or info["module"] not in bypassed:
                    bypassed[info["module"]] = p["value"] >= 0.5
        groups = _ozcat.catalog_by_module(pack)
        modules = []
        for key in sorted(k for k in groups if k != "GLOBAL"):
            names = {p["name"] for p in groups[key]}
            modules.append({
                "key": key, "name": _oz.MODULES.get(key, key),
                "exposed": bool(names & exposed_names),
                "bypassed": bypassed.get(key),
            })
        return _ok({"modules": modules})
    except Exception as e:
        logger.error("get_ozone_modules error: %s", e)
        return _err("get_ozone_modules error: %s" % e)


@mcp.tool()
def expose_ozone_modules(ctx: Context, track_index: int, modules: list,
                         device_index: int = 0, track_type: str = "master",
                         reload: bool = True) -> str:
    """Configure the given Ozone 12 modules' params as settable LOM params.

    Ozone exposes 873 params but Ableton Configures at most 128 at once; this
    fills the device's Configure slots with the requested modules' params (in
    order), reloads the set in place, and reports overflow. The set must be saved
    first (save_set_as). modules: list of module keys (e.g. ["EQ","MAX","IMG"]);
    see get_ozone_modules for keys.
    """
    try:
        pack = _ozcat.load()
        plan = _oz.pack_modules(pack["params"], modules, cap=128)
        if not plan["selected"]:
            return _err("no catalog params for modules %s" % modules)
        get_ableton_connection()  # ensure reachable before save
        data = _expose_plugin_impl(
            track_index, device_index, track_type, plan["selected"],
            _EXPOSE_DEFAULT_MANUAL, reload,
            save_impl=lambda: _save_set_impl(name=""),
            reload_impl=lambda p, n: _reload_set(
                p, n, probe=lambda: get_ableton_connection().send_command(
                    "get_session_info")),
        )
        data["overflow"] = plan["overflow"]
        return _ok(data)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("expose_ozone_modules error: %s", e)
        return _err("expose_ozone_modules error: %s" % e)


def _oz_set_by_name(track_index, device_index, track_type, name, normalized):
    # set_device_parameter's send_command contract takes parameter_index (int),
    # not a name -- resolve name -> index against the live param list first.
    conn = get_ableton_connection()
    info = conn.send_command("get_device_parameters", {
        "track_index": track_index, "device_index": device_index,
        "track_type": track_type})
    params = info.get("parameters", [])
    idx = resolve_parameter_index(params, name)
    return conn.send_command("set_device_parameter", {
        "track_index": track_index, "device_index": device_index,
        "track_type": track_type, "parameter_index": idx, "value": normalized})


@mcp.tool()
def get_ozone_module(ctx: Context, track_index: int, module: str,
                     device_index: int = 0, track_type: str = "master") -> str:
    """Read the currently-exposed params of one Ozone 12 module (native + normalized)."""
    try:
        pack = _ozcat.load()
        by_name = {p["name"]: p for p in pack["params"]}
        conn = get_ableton_connection()
        dp = conn.send_command("get_device_parameters", {
            "track_index": track_index, "device_index": device_index,
            "track_type": track_type})
        out = []
        for p in dp.get("parameters", []):
            info = _oz.parse_param_name(p["name"])
            if info["module"] != module:
                continue
            cat_p = by_name.get(p["name"], {})
            out.append({"name": p["name"], "role": info["role"],
                        "band": info["band"], "section": info["section"],
                        "normalized": p["value"],
                        "native": _oz.to_native(cat_p, p["value"]) if cat_p else None})
        if not out:
            return _err("module %s not exposed; call expose_ozone_modules first" % module)
        return _ok({"module": module, "name": _oz.MODULES.get(module, module),
                    "params": out})
    except Exception as e:
        logger.error("get_ozone_module error: %s", e)
        return _err("get_ozone_module error: %s" % e)


@mcp.tool()
def set_ozone_module_param(ctx: Context, track_index: int, module: str, role: str,
                           value: float, band: int = None, section: str = None,
                           native: bool = True, device_index: int = 0,
                           track_type: str = "master") -> str:
    """Set one Ozone 12 module param. role/band/section identify the param (see
    get_ozone_module); value is native units by default (native=False for 0-1).
    The param must be exposed first (expose_ozone_modules)."""
    try:
        pack = _ozcat.load()
        p = _ozcat.find_param(pack, module, role.lower(), band=band, section=section)
        if p is None:
            return _err("no Ozone param for module=%s role=%s band=%s section=%s"
                        % (module, role, band, section))
        normalized = _oz.to_normalized(p, value) if native else max(0.0, min(1.0, value))
        res = _oz_set_by_name(track_index, device_index, track_type, p["name"], normalized)
        return _ok({"name": p["name"], "normalized": normalized, "result": res})
    except Exception as e:
        logger.error("set_ozone_module_param error: %s", e)
        return _err("set_ozone_module_param error: %s" % e)


@mcp.tool()
def set_ozone_module_enabled(ctx: Context, track_index: int, module: str, on: bool,
                             device_index: int = 0, track_type: str = "master") -> str:
    """Enable/disable an Ozone 12 module via its Bypass param (on=True -> not
    bypassed). The module's Bypass must be exposed (expose_ozone_modules)."""
    try:
        pack = _ozcat.load()
        p = _ozcat.find_param(pack, module, "bypass")
        if p is None:
            return _err("no Bypass param for module %s" % module)
        # Bypass = 1 means bypassed; on=True -> value 0
        res = _oz_set_by_name(track_index, device_index, track_type, p["name"],
                              0.0 if on else 1.0)
        return _ok({"name": p["name"], "on": on, "result": res})
    except Exception as e:
        logger.error("set_ozone_module_enabled error: %s", e)
        return _err("set_ozone_module_enabled error: %s" % e)


def _oz_apply(track_index, device_index, track_type, module, items):
    """items: list of (role, band, section, native_value); None values are not
    requested (skipped silently). A requested role that doesn't resolve to a
    catalog param is recorded in `skipped` so a no-op isn't reported as success.
    Returns (applied_names, skipped_roles)."""
    pack = _ozcat.load()
    applied = []
    skipped = []
    for role, band, section, val in items:
        if val is None:
            continue
        p = _ozcat.find_param(pack, module, role, band=band, section=section)
        if p is None:
            skipped.append(role)
            continue
        normalized = _oz.to_normalized(p, val)
        _oz_set_by_name(track_index, device_index, track_type, p["name"], normalized)
        applied.append(p["name"])
    return applied, skipped


@mcp.tool()
def set_ozone_eq_band(ctx: Context, track_index: int, band: int, freq: float = None,
                      gain: float = None, q: float = None, enable: float = None,
                      section: str = "stereo_main", device_index: int = 0,
                      track_type: str = "master") -> str:
    """Set an Ozone 12 EQ band (freq Hz / gain dB / q / enable) in one call.
    The EQ module must be exposed first (expose_ozone_modules ["EQ"])."""
    try:
        applied, skipped = _oz_apply(track_index, device_index, track_type, "EQ", [
            ("frequency", band, section, freq),
            ("gain", band, section, gain),
            ("q", band, section, q),
            ("enable", band, section, enable),
        ])
        return _ok({"module": "EQ", "band": band, "applied": applied,
                    "skipped": skipped})
    except Exception as e:
        logger.error("set_ozone_eq_band error: %s", e)
        return _err("set_ozone_eq_band error: %s" % e)


@mcp.tool()
def set_ozone_maximizer(ctx: Context, track_index: int, threshold: float = None,
                        ceiling: float = None, character: float = None,
                        device_index: int = 0, track_type: str = "master") -> str:
    """Set Ozone 12 Maximizer controls (threshold via input gain, output ceiling,
    character). Maximizer must be exposed first (expose_ozone_modules ["MAX"])."""
    try:
        applied, skipped = _oz_apply(track_index, device_index, track_type, "MAX", [
            ("input gain", None, None, threshold),
            ("output level", None, None, ceiling),
            ("character", None, None, character),
        ])
        return _ok({"module": "MAX", "applied": applied, "skipped": skipped})
    except Exception as e:
        logger.error("set_ozone_maximizer error: %s", e)
        return _err("set_ozone_maximizer error: %s" % e)


@mcp.tool()
def set_ozone_dynamics_band(ctx: Context, track_index: int, band: int,
                            comp_threshold: float = None, comp_ratio: float = None,
                            comp_attack: float = None, comp_release: float = None,
                            section: str = "stereo_main", device_index: int = 0,
                            track_type: str = "master") -> str:
    """Set an Ozone 12 Dynamics band's compressor controls in one call. Dynamics
    must be exposed first (expose_ozone_modules ["DYN"])."""
    try:
        applied, skipped = _oz_apply(track_index, device_index, track_type, "DYN", [
            ("band comp threshold", band, section, comp_threshold),
            ("band comp ratio", band, section, comp_ratio),
            ("band comp attack", band, section, comp_attack),
            ("band comp release", band, section, comp_release),
        ])
        return _ok({"module": "DYN", "band": band, "applied": applied,
                    "skipped": skipped})
    except Exception as e:
        logger.error("set_ozone_dynamics_band error: %s", e)
        return _err("set_ozone_dynamics_band error: %s" % e)


def _resolve_track_span(xml, track_index, track_type):
    if track_type == "regular":
        return als.find_track_span(xml, track_index)
    if track_type == "return":
        return als.find_return_track_span(xml, track_index)
    if track_type == "master":
        return als.find_master_track_span(xml)
    raise ValueError("track_type must be regular, return, or master")


def _ozone_state_read_impl(track_index, device_index, track_type, module, *,
                           save_impl, read_als=als.read_als,
                           resolve_path=None, title_fn=None):
    """Save the set, decode the target Ozone device's ProcessorState from disk,
    and return native param values. module=None -> a per-module summary.
    Returns {ok, set_path, ...} or {ok:False, error}."""
    save_res = save_impl()
    if not save_res.get("saved"):
        return {"ok": False, "error": "save_set failed: %s" % save_res.get("error", save_res)}
    path = _serum_fx_resolve_path(title_fn, resolve_path)
    xml = read_als(path)
    ts, te = _resolve_track_span(xml, track_index, track_type)
    s, e = pcu.locate_processor_state(xml, ts, te, device_index)
    if not _osu.is_ozone_state(xml[s:e]):
        return {"ok": False, "set_path": path,
                "error": "device %d on track %d is not an Ozone 12 plugin"
                         % (device_index, track_index)}
    tree = _osu.decode(_osu.from_hex(xml[s:e])).tree
    if module is None:
        elems = tree["DSP State"]["Value"]["DSP Elements"]["Value"]
        mods = []
        for name in sorted(elems):
            leaves = _osu.module_leaves(tree, name)
            byp = leaves.get("Bypass") or leaves.get("Global Bypass")
            mods.append({"name": name, "param_count": len(leaves),
                         "bypass": byp["value"] if byp else None})
        return {"ok": True, "set_path": path, "modules": mods}
    blob_module = _oz.normalize_module(module)
    try:
        leaves = _osu.module_leaves(tree, blob_module)
    except ValueError:
        return {"ok": False, "set_path": path,
                "error": "unknown module %r (normalized %r)" % (module, blob_module)}
    params = [{"name": n, "type": v["type"], "value": v["value"]}
              for n, v in sorted(leaves.items())]
    return {"ok": True, "set_path": path, "module": blob_module, "params": params}


def _ozone_state_mutate_impl(track_index, device_index, track_type, changes, *,
                             reload, save_impl, reload_impl,
                             read_als=als.read_als, write_als=als.write_als,
                             resolve_path=None, title_fn=None):
    """Save, patch the target Ozone device's ProcessorState with `changes`
    ({module: {param: value}}, module names normalized), re-encode, splice, write,
    and optionally reload. Returns {ok, reloaded, set_path, applied, skipped}."""
    save_res = save_impl()
    if not save_res.get("saved"):
        return {"ok": False, "reloaded": False,
                "error": "save_set failed: %s" % save_res.get("error", save_res)}
    path = _serum_fx_resolve_path(title_fn, resolve_path)
    xml = read_als(path)
    ts, te = _resolve_track_span(xml, track_index, track_type)
    s, e = pcu.locate_processor_state(xml, ts, te, device_index)
    if not _osu.is_ozone_state(xml[s:e]):
        return {"ok": False, "reloaded": False, "set_path": path,
                "error": "device %d on track %d is not an Ozone 12 plugin"
                         % (device_index, track_index)}
    normalized = {}
    for m, p in changes.items():
        normalized.setdefault(_oz.normalize_module(m), {}).update(p)
    st = _osu.decode(_osu.from_hex(xml[s:e]))
    applied, skipped = _osu.apply_changes(st.tree, normalized)
    if not applied:
        return {"ok": True, "reloaded": False, "set_path": path,
                "applied": applied, "skipped": skipped}
    new_hex = _osu.to_hex(_osu.encode(st, st.tree))
    xml = xml[:s] + new_hex + xml[e:]
    write_als(path, xml)
    reloaded = False
    if reload:
        rr = reload_impl(path, set_name_from_path(path))
        reloaded = bool(rr.get("reloaded", False)) if isinstance(rr, dict) else bool(rr)
    return {"ok": True, "reloaded": reloaded, "set_path": path,
            "applied": applied, "skipped": skipped}


@mcp.tool()
def get_ozone_state(ctx: Context, track_index: int, device_index: int = 0,
                    track_type: str = "master", module: str = None) -> str:
    """Read Ozone 12 params directly from the plugin state blob (native values).

    Unlike get_ozone_module, this needs NO Configure/exposure and returns REAL
    native units (Hz/dB, not clamped 0-1) for ANY module. Saves the set, then
    decodes the device's ProcessorState from the .als on disk (no reload).

    Parameters:
    - track_index: track holding the Ozone 12 instance.
    - device_index: which plugin device on the track (0 = first).
    - track_type: 'master' (default), 'return', or 'regular'.
    - module: a module name (blob-native like 'Maximizer', or a Phase 1 key like
      'MAX'). Omit for a per-module summary of the whole instance.

    Returns JSON {ok, data:{set_path, module, params:[{name,type,value}]}} for one
    module, or {ok, data:{set_path, modules:[{name,param_count,bypass}]}} for all.
    """
    try:
        get_ableton_connection()  # fail fast if Live is unreachable
        res = _ozone_state_read_impl(
            track_index, device_index, track_type, module,
            save_impl=lambda: _save_set_impl(name=""))
        if not res.get("ok"):
            return _err(res.get("error", "get_ozone_state failed"))
        res.pop("ok", None)
        return _ok(res)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("get_ozone_state error: %s", e)
        return _err("get_ozone_state error: %s" % e)


@mcp.tool()
def set_ozone_state(ctx: Context, track_index: int, changes: dict,
                    device_index: int = 0, track_type: str = "master",
                    reload: bool = True) -> str:
    """Author Ozone 12 params in native units by patching the state blob.

    Batch authoring: `changes` sets many params across many modules in ONE
    save+patch+reload. Native units land un-clamped (unlike the Phase 1 wrappers),
    with no 128-slot cap. Only changes existing params (never adds modules);
    unknown module/param or a wrong type is reported in `skipped`, not silently
    dropped. The set must be saved to a real file first (save_set_as).

    Parameters:
    - track_index: track holding the Ozone 12 instance.
    - changes: {module: {param: value}}. module is blob-native ('Maximizer',
      'Dynamic EQ') or a Phase 1 key ('MAX','DYNEQ'). value is native and typed
      per the param (Float dB/Hz, Bool bypass, UInt mode); see get_ozone_state.
    - device_index: which plugin device on the track (0 = first).
    - track_type: 'master' (default), 'return', or 'regular'.
    - reload: reload the set in place after patching (default True).

    Returns JSON {ok, data:{set_path, reloaded, applied:[...], skipped:[...]}}.
    """
    try:
        get_ableton_connection()
        res = _ozone_state_mutate_impl(
            track_index, device_index, track_type, changes, reload=reload,
            save_impl=lambda: _save_set_impl(name=""),
            reload_impl=lambda p, n: _reload_set(
                p, n, probe=lambda: get_ableton_connection().send_command(
                    "get_session_info")))
        if not res.get("ok"):
            return _err(res.get("error", "set_ozone_state failed"))
        res.pop("ok", None)
        return _ok(res)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("set_ozone_state error: %s", e)
        return _err("set_ozone_state error: %s" % e)


def _serum_fx_resolve_path(title_fn, resolve_path):
    title = (title_fn or _live_window_title)()
    if is_untitled_title(title):
        raise ValueError("Set is untitled - save it first via save_set_as, then retry.")
    path = (resolve_path or (lambda: _current_set_path(title) or _find_saved_set(title)))()
    if not path:
        raise RuntimeError("Could not resolve the current set's .als path.")
    return path


def _serum_fx_read_impl(track_index, device_index, *, save_impl,
                        read_als=als.read_als, find_track_span=als.find_track_span,
                        resolve_path=None, title_fn=None, project_fn=None):
    """Read-only Serum 2 FX listing. Saves the set, decodes the device's
    ProcessorState from disk, and returns the FX list (no reload).

    Returns {ok, set_path, fx:[...]} or {ok:False, error:...}."""
    save_res = save_impl()
    if not save_res.get("saved"):
        return {"ok": False, "error": "save_set failed: %s" % save_res.get("error", save_res)}
    path = _serum_fx_resolve_path(title_fn, resolve_path)
    xml = read_als(path)
    ts, te = find_track_span(xml, track_index)
    spans = pcu.locate_plugin_state(xml, ts, te, device_index)
    s, e = spans["processor"]
    if not pcu.is_serum_state(xml[s:e]):
        return {"ok": False, "set_path": path,
                "error": "device %d on track %d is not a Serum 2 plugin" % (device_index, track_index)}
    blob = _ssc.from_hex(xml[s:e])
    tree = _ssc.decode(blob).tree
    if project_fn is None:
        return {"ok": True, "set_path": path, "fx": _sfx.list_fx(tree)}
    payload = {"ok": True, "set_path": path}
    payload.update(project_fn(tree))
    return payload


def _serum_fx_mutate_impl(track_index, device_index, mutate_fn, *, reload,
                          save_impl, reload_impl,
                          read_als=als.read_als, write_als=als.write_als,
                          find_track_span=als.find_track_span,
                          resolve_path=None, title_fn=None,
                          catalog_loader=_sfxcat.load_catalog):
    """Apply mutate_fn(catalog, tree) to the ProcessorState blob only, re-encode,
    splice it back, write, and optionally reload. ControllerState is left
    untouched (incompatible FX schema). Returns {ok, reloaded, set_path}."""
    save_res = save_impl()
    if not save_res.get("saved"):
        return {"ok": False, "reloaded": False,
                "error": "save_set failed: %s" % save_res.get("error", save_res)}
    path = _serum_fx_resolve_path(title_fn, resolve_path)
    xml = read_als(path)
    ts, te = find_track_span(xml, track_index)
    spans = pcu.locate_plugin_state(xml, ts, te, device_index)
    if not pcu.is_serum_state(xml[spans["processor"][0]:spans["processor"][1]]):
        return {"ok": False, "reloaded": False, "set_path": path,
                "error": "device %d on track %d is not a Serum 2 plugin" % (device_index, track_index)}
    catalog = catalog_loader()
    # Processor-only: ControllerState uses an incompatible FX schema
    # (defaultPlainValues, no type/wrapper); deferred to live verification (Task 7).
    s, e = spans["processor"]
    st = _ssc.decode(_ssc.from_hex(xml[s:e]))
    mutate_fn(catalog, st.tree)
    new_hex = _ssc.to_hex(_ssc.encode(st, st.tree))
    xml = xml[:s] + new_hex + xml[e:]
    write_als(path, xml)
    reloaded = False
    if reload:
        reloaded = bool(reload_impl(path, set_name_from_path(path)))
    return {"ok": True, "reloaded": reloaded, "set_path": path}


@mcp.tool()
def get_serum_fx(ctx: Context, track_index: int, device_index: int = 0) -> str:
    """List the FX in a Serum 2 instance's three FX racks (read-only).

    Saves the set, then decodes the device's plugin state from the .als on disk
    (no reload). Returns JSON {ok, data:{set_path, fx:[{rack, slot, type, name,
    enabled, params}]}}. params are native Serum units. State authoring only -
    FX are NOT LOM-automatable knobs; use set_serum_fx_param etc. to change them.

    Parameters:
    - track_index: track holding the Serum 2 instance.
    - device_index: which VST/AU plugin device on the track (0 = first plugin), not chain position."""
    try:
        get_ableton_connection()  # fail fast if Live is unreachable
        result = _serum_fx_read_impl(
            track_index, device_index,
            save_impl=lambda: _save_set_impl(name=""))
        if not result.get("ok"):
            return _err(result.get("error", "get_serum_fx failed"))
        return _ok({"set_path": result.get("set_path"), "fx": result.get("fx")})
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("get_serum_fx error: %s", e)
        return _err("get_serum_fx error: %s" % e)


@mcp.tool()
def set_serum_fx_param(
    ctx: Context,
    track_index: int,
    rack: int,
    slot: int,
    kparam: str,
    value: float,
    device_index: int = 0,
    reload: bool = True,
) -> str:
    """Set one Serum FX parameter (native units) on rack (0-2) / slot.

    Patches the plugin state in the .als and reloads the set in place. value is a
    native Serum value (e.g. kParamWet in %, kParamFreq in Hz); validated against
    the catalog's observed range. State authoring - not a live LOM knob.

    Parameters:
    - track_index: track holding the Serum 2 instance.
    - rack: FX rack index (0, 1, or 2).
    - slot: slot within the rack (0-based).
    - kparam: Serum internal parameter key (e.g. "kParamWet").
    - value: native Serum value; validated against catalog min/max.
    - device_index: which VST/AU plugin device on the track (0 = first plugin), not chain position.
    - reload: reload the set in Live after patching (default True).

    Returns JSON {ok, data:{reloaded, set_path}}."""
    try:
        get_ableton_connection()
        def mutate_fn(catalog, tree):
            _sfx.set_fx_param(catalog, tree, rack, slot, kparam, value)
        result = _serum_fx_mutate_impl(
            track_index, device_index, mutate_fn, reload=reload,
            save_impl=lambda: _save_set_impl(name=""),
            reload_impl=lambda p, n: _reload_set(p, n))
        if not result.get("ok"):
            return _err(result.get("error", "set_serum_fx_param failed"))
        return _ok(result)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("set_serum_fx_param error: %s", e)
        return _err("set_serum_fx_param error: %s" % e)


@mcp.tool()
def insert_serum_fx(
    ctx: Context,
    track_index: int,
    rack: int,
    index: int,
    fx_type: int,
    device_index: int = 0,
    reload: bool = True,
) -> str:
    """Insert an FX of catalog fx_type into a Serum rack (0-2) at index.

    fx_type ints come from get_serum_fx / the serum2_fx catalog. New FX uses
    Serum defaults (empty plainParams). State authoring (not a live LOM knob);
    patches the .als and reloads the set.

    Parameters:
    - track_index: track holding the Serum 2 instance.
    - rack: FX rack index (0, 1, or 2).
    - index: position to insert at (0 = before all existing FX).
    - fx_type: integer FX type from the catalog (see get_serum_fx).
    - device_index: which VST/AU plugin device on the track (0 = first plugin), not chain position.
    - reload: reload the set in Live after patching (default True).

    Returns JSON {ok, data:{reloaded, set_path}}."""
    try:
        get_ableton_connection()
        def mutate_fn(catalog, tree):
            _sfx.insert_fx(catalog, tree, rack, index, fx_type)
        result = _serum_fx_mutate_impl(
            track_index, device_index, mutate_fn, reload=reload,
            save_impl=lambda: _save_set_impl(name=""),
            reload_impl=lambda p, n: _reload_set(p, n))
        if not result.get("ok"):
            return _err(result.get("error", "insert_serum_fx failed"))
        return _ok(result)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("insert_serum_fx error: %s", e)
        return _err("insert_serum_fx error: %s" % e)


@mcp.tool()
def remove_serum_fx(
    ctx: Context,
    track_index: int,
    rack: int,
    slot: int,
    device_index: int = 0,
    reload: bool = True,
) -> str:
    """Remove the FX at rack (0-2) / slot from a Serum instance.

    State authoring (not a live LOM knob); patches the .als and reloads the set.

    Parameters:
    - track_index: track holding the Serum 2 instance.
    - rack: FX rack index (0, 1, or 2).
    - slot: slot within the rack to remove (0-based).
    - device_index: which VST/AU plugin device on the track (0 = first plugin), not chain position.
    - reload: reload the set in Live after patching (default True).

    Returns JSON {ok, data:{reloaded, set_path}}."""
    try:
        get_ableton_connection()
        def mutate_fn(catalog, tree):
            _sfx.remove_fx(tree, rack, slot)
        result = _serum_fx_mutate_impl(
            track_index, device_index, mutate_fn, reload=reload,
            save_impl=lambda: _save_set_impl(name=""),
            reload_impl=lambda p, n: _reload_set(p, n))
        if not result.get("ok"):
            return _err(result.get("error", "remove_serum_fx failed"))
        return _ok(result)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("remove_serum_fx error: %s", e)
        return _err("remove_serum_fx error: %s" % e)


@mcp.tool()
def reorder_serum_fx(
    ctx: Context,
    track_index: int,
    rack: int,
    from_index: int,
    to_index: int = 0,
    bypass: bool = None,
    device_index: int = 0,
    reload: bool = True,
) -> str:
    """Move an FX within a Serum rack (0-2), or toggle its bypass state.

    If bypass is None (default), moves the FX at from_index to to_index within
    the rack. If bypass is provided, instead toggles the FX at from_index:
    bypass=True disables it (kParamEnable=0), bypass=False re-enables it.
    State authoring (not a live LOM knob); patches the .als and reloads the set.

    Parameters:
    - track_index: track holding the Serum 2 instance.
    - rack: FX rack index (0, 1, or 2).
    - from_index: source slot (or slot to bypass when bypass is not None).
    - to_index: destination slot for reorder (ignored when bypass is provided).
    - bypass: if not None, enable/disable the FX instead of reordering.
    - device_index: which VST/AU plugin device on the track (0 = first plugin), not chain position.
    - reload: reload the set in Live after patching (default True).

    Returns JSON {ok, data:{reloaded, set_path}}."""
    try:
        get_ableton_connection()
        def mutate_fn(catalog, tree):
            if bypass is not None:
                _sfx.set_fx_enabled(tree, rack, from_index, not bypass)
            else:
                _sfx.reorder_fx(tree, rack, from_index, to_index)
        result = _serum_fx_mutate_impl(
            track_index, device_index, mutate_fn, reload=reload,
            save_impl=lambda: _save_set_impl(name=""),
            reload_impl=lambda p, n: _reload_set(p, n))
        if not result.get("ok"):
            return _err(result.get("error", "reorder_serum_fx failed"))
        return _ok(result)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("reorder_serum_fx error: %s", e)
        return _err("reorder_serum_fx error: %s" % e)


@mcp.tool()
def get_serum_patch(ctx: Context, track_index: int, device_index: int = 0) -> str:
    """Read a Serum 2 instance's full instrument state (read-only).

    Saves the set, decodes the device's ProcessorState from disk (no reload), and
    returns a per-module summary. State authoring view - not LOM knobs.

    Parameters:
    - track_index: track holding the Serum 2 instance.
    - device_index: which VST/AU plugin device on the track (0 = first plugin).

    Returns JSON {ok, data:{set_path, oscillators, filters, envelopes, lfos, macros}}."""
    try:
        get_ableton_connection()
        result = _serum_fx_read_impl(
            track_index, device_index,
            save_impl=lambda: _save_set_impl(name=""),
            project_fn=lambda tree: _spu.summarize(_spcat.load_catalog(), tree))
        if not result.get("ok"):
            return _err(result.get("error", "get_serum_patch failed"))
        return _ok(result)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("get_serum_patch error: %s", e)
        return _err("get_serum_patch error: %s" % e)


@mcp.tool()
def set_serum_oscillator(ctx: Context, track_index: int, osc: int,
                         params: dict = None, mode: str = None,
                         device_index: int = 0, reload: bool = True) -> str:
    """Set Serum oscillator params (native units) and/or its mode.

    Patches plugin state in the .als and reloads in place. params keys are friendly
    names or raw kParam* keys; values are native, range-validated against the
    catalog. mode (when given) selects the oscillator engine: 'wavetable' (default),
    'multisample', 'sample', 'granular', 'spectral'.

    Parameters:
    - track_index: track holding the Serum 2 instance.
    - osc: oscillator index (0-4).
    - params: {name: native_value} dict (optional).
    - mode: oscillator mode name (optional).
    - device_index: which VST/AU plugin device on the track (0 = first plugin).
    - reload: reload the set after patching (default True).

    Returns JSON {ok, data:{reloaded, set_path}}."""
    try:
        get_ableton_connection()
        def mutate_fn(catalog, tree):
            if mode is not None:
                _spu.set_oscillator_mode(catalog, tree, osc, mode)
            if params:
                _spu.set_module_params(catalog, tree, "oscillator", osc, params)
        result = _serum_fx_mutate_impl(
            track_index, device_index, mutate_fn, reload=reload,
            catalog_loader=_spcat.load_catalog,
            save_impl=lambda: _save_set_impl(name=""),
            reload_impl=lambda p, n: _reload_set(p, n))
        if not result.get("ok"):
            return _err(result.get("error", "set_serum_oscillator failed"))
        return _ok(result)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("set_serum_oscillator error: %s", e)
        return _err("set_serum_oscillator error: %s" % e)


@mcp.tool()
def set_serum_filter(ctx: Context, track_index: int, filt: int,
                     params: dict = None,
                     device_index: int = 0, reload: bool = True) -> str:
    """Set Serum filter params (native units).

    Patches plugin state in the .als and reloads in place. params keys are friendly
    names or raw kParam* keys; values are native, range-validated against the
    catalog.

    Parameters:
    - track_index: track holding the Serum 2 instance.
    - filt: filter index.
    - params: {name: native_value} dict (optional).
    - device_index: which VST/AU plugin device on the track (0 = first plugin).
    - reload: reload the set after patching (default True).

    Returns JSON {ok, data:{reloaded, set_path}}."""
    try:
        get_ableton_connection()
        def mutate_fn(catalog, tree):
            if params:
                _spu.set_module_params(catalog, tree, "filter", filt, params)
        result = _serum_fx_mutate_impl(
            track_index, device_index, mutate_fn, reload=reload,
            catalog_loader=_spcat.load_catalog,
            save_impl=lambda: _save_set_impl(name=""),
            reload_impl=lambda p, n: _reload_set(p, n))
        if not result.get("ok"):
            return _err(result.get("error", "set_serum_filter failed"))
        return _ok(result)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("set_serum_filter error: %s", e)
        return _err("set_serum_filter error: %s" % e)


@mcp.tool()
def set_serum_envelope(ctx: Context, track_index: int, env: int,
                       params: dict = None,
                       device_index: int = 0, reload: bool = True) -> str:
    """Set Serum envelope params (native units).

    Patches plugin state in the .als and reloads in place. params keys are friendly
    names or raw kParam* keys; values are native, range-validated against the
    catalog.

    Parameters:
    - track_index: track holding the Serum 2 instance.
    - env: envelope index.
    - params: {name: native_value} dict (optional).
    - device_index: which VST/AU plugin device on the track (0 = first plugin).
    - reload: reload the set after patching (default True).

    Returns JSON {ok, data:{reloaded, set_path}}."""
    try:
        get_ableton_connection()
        def mutate_fn(catalog, tree):
            if params:
                _spu.set_module_params(catalog, tree, "envelope", env, params)
        result = _serum_fx_mutate_impl(
            track_index, device_index, mutate_fn, reload=reload,
            catalog_loader=_spcat.load_catalog,
            save_impl=lambda: _save_set_impl(name=""),
            reload_impl=lambda p, n: _reload_set(p, n))
        if not result.get("ok"):
            return _err(result.get("error", "set_serum_envelope failed"))
        return _ok(result)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("set_serum_envelope error: %s", e)
        return _err("set_serum_envelope error: %s" % e)


@mcp.tool()
def set_serum_lfo(ctx: Context, track_index: int, lfo: int,
                  params: dict = None,
                  device_index: int = 0, reload: bool = True) -> str:
    """Set Serum LFO params (native units).

    Patches plugin state in the .als and reloads in place. params keys are friendly
    names or raw kParam* keys; values are native, range-validated against the
    catalog.

    Parameters:
    - track_index: track holding the Serum 2 instance.
    - lfo: LFO index.
    - params: {name: native_value} dict (optional).
    - device_index: which VST/AU plugin device on the track (0 = first plugin).
    - reload: reload the set after patching (default True).

    Returns JSON {ok, data:{reloaded, set_path}}."""
    try:
        get_ableton_connection()
        def mutate_fn(catalog, tree):
            if params:
                _spu.set_module_params(catalog, tree, "lfo", lfo, params)
        result = _serum_fx_mutate_impl(
            track_index, device_index, mutate_fn, reload=reload,
            catalog_loader=_spcat.load_catalog,
            save_impl=lambda: _save_set_impl(name=""),
            reload_impl=lambda p, n: _reload_set(p, n))
        if not result.get("ok"):
            return _err(result.get("error", "set_serum_lfo failed"))
        return _ok(result)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("set_serum_lfo error: %s", e)
        return _err("set_serum_lfo error: %s" % e)


@mcp.tool()
def set_serum_macro(ctx: Context, track_index: int, macro: int, value: float,
                    name: str = None, device_index: int = 0, reload: bool = True) -> str:
    """Set a Serum macro value (0-100) and optionally its name.

    Parameters:
    - track_index: track holding the Serum 2 instance.
    - macro: macro index (0-7).
    - value: macro value 0-100.
    - name: optional macro label.
    - device_index: which VST/AU plugin device on the track (0 = first plugin).
    - reload: reload the set after patching (default True).

    Returns JSON {ok, data:{reloaded, set_path}}."""
    try:
        get_ableton_connection()
        def mutate_fn(catalog, tree):
            _spu.set_macro(catalog, tree, macro, value, name=name)
        result = _serum_fx_mutate_impl(
            track_index, device_index, mutate_fn, reload=reload,
            catalog_loader=_spcat.load_catalog,
            save_impl=lambda: _save_set_impl(name=""),
            reload_impl=lambda p, n: _reload_set(p, n))
        if not result.get("ok"):
            return _err(result.get("error", "set_serum_macro failed"))
        return _ok(result)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("set_serum_macro error: %s", e)
        return _err("set_serum_macro error: %s" % e)


@mcp.tool()
def set_serum_wavetable(ctx: Context, track_index: int, osc: int, table: str,
                        device_index: int = 0, reload: bool = True) -> str:
    """Point a Serum oscillator at a wavetable file and put it in WaveTable mode.

    Writes the table path into Oscillator{osc}.WTOsc{osc}.relativePathToWT (relative
    to Serum's table library, e.g. 'S2 Tables/Default Shapes.wav') and clears the
    oscillator mode to WaveTable (the default). Serum loads + recomputes the table on
    reload. State authoring - the table must exist in Serum's library.

    Parameters:
    - track_index: track holding the Serum 2 instance.
    - osc: oscillator index (0-4).
    - table: wavetable path relative to Serum's table library.
    - device_index: which VST/AU plugin device on the track (0 = first plugin).
    - reload: reload the set after patching (default True).

    Returns JSON {ok, data:{reloaded, set_path}}."""
    try:
        get_ableton_connection()
        def mutate_fn(catalog, tree):
            _spu.set_wavetable(catalog, tree, osc, table)
        result = _serum_fx_mutate_impl(
            track_index, device_index, mutate_fn, reload=reload,
            catalog_loader=_spcat.load_catalog,
            save_impl=lambda: _save_set_impl(name=""),
            reload_impl=lambda p, n: _reload_set(p, n))
        if not result.get("ok"):
            return _err(result.get("error", "set_serum_wavetable failed"))
        return _ok(result)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("set_serum_wavetable error: %s", e)
        return _err("set_serum_wavetable error: %s" % e)


@mcp.tool()
def add_serum_mod_route(ctx: Context, track_index: int, source, dest_module: str,
                        dest_index: int, dest_param: str, amount: float,
                        device_index: int = 0, reload: bool = True) -> str:
    """Add a Serum mod-matrix route into a free ModSlot.

    source is a raw integer mod-source id OR a configured friendly name from the
    catalog mod_sources table (36 mapped via the live GUI oracle): env1-env4,
    lfo1-lfo4, macro1-macro8, plus modwheel, aftertouch, polyaftertouch, pitchbend,
    fixed, velocity, note, releasevelo, activevoices, voiceindex, voicemod1,
    voicemod2, noteonrand1, noteonrand2, noteonranddiscrete, noteonalt, noteonalt2,
    and the MPE sources mpex/mpey/mpez. Any unmapped source still works by raw int
    id. dest is
    structural: dest_module ('oscillator'|'filter'|'envelope'|
    'lfo'|'wt'|'macro'|'global'), dest_index (instance), dest_param (friendly or
    kParam*). amount is native (typically 0-100). Patches state + reloads in place.

    Parameters:
    - track_index: track holding the Serum 2 instance.
    - source: int source id (or friendly name once configured).
    - dest_module: destination module type.
    - dest_index: destination instance index.
    - dest_param: destination parameter (friendly or kParam*).
    - amount: modulation amount (native).
    - device_index: which VST/AU plugin device on the track (0 = first plugin).
    - reload: reload the set after patching (default True).

    Returns JSON {ok, data:{reloaded, set_path}}."""
    try:
        get_ableton_connection()
        def mutate_fn(catalog, tree):
            _spu.add_mod_route(catalog, tree, source, dest_module, dest_index, dest_param, amount)
        result = _serum_fx_mutate_impl(
            track_index, device_index, mutate_fn, reload=reload,
            catalog_loader=_spcat.load_catalog,
            save_impl=lambda: _save_set_impl(name=""),
            reload_impl=lambda p, n: _reload_set(p, n))
        if not result.get("ok"):
            return _err(result.get("error", "add_serum_mod_route failed"))
        return _ok(result)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("add_serum_mod_route error: %s", e)
        return _err("add_serum_mod_route error: %s" % e)


@mcp.tool()
def clear_serum_mod_route(ctx: Context, track_index: int, dest_module: str,
                          dest_index: int, dest_param: str,
                          device_index: int = 0, reload: bool = True) -> str:
    """Clear an existing Serum mod-matrix route targeting a destination param.

    dest is structural: dest_module ('oscillator'|'filter'|'envelope'|'lfo'|'wt'|
    'macro'|'global'), dest_index (instance), dest_param (friendly or kParam*).
    Patches state + reloads in place.

    Parameters:
    - track_index: track holding the Serum 2 instance.
    - dest_module: destination module type.
    - dest_index: destination instance index.
    - dest_param: destination parameter (friendly or kParam*).
    - device_index: which VST/AU plugin device on the track (0 = first plugin).
    - reload: reload the set after patching (default True).

    Returns JSON {ok, data:{reloaded, set_path}}."""
    try:
        get_ableton_connection()
        def mutate_fn(catalog, tree):
            _spu.clear_mod_route(catalog, tree, dest_module, dest_index, dest_param)
        result = _serum_fx_mutate_impl(
            track_index, device_index, mutate_fn, reload=reload,
            catalog_loader=_spcat.load_catalog,
            save_impl=lambda: _save_set_impl(name=""),
            reload_impl=lambda p, n: _reload_set(p, n))
        if not result.get("ok"):
            return _err(result.get("error", "clear_serum_mod_route failed"))
        return _ok(result)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("clear_serum_mod_route error: %s", e)
        return _err("clear_serum_mod_route error: %s" % e)


@mcp.tool()
def create_serum_patch(ctx: Context, track_index: int, spec: dict,
                       device_index: int = 0, reload: bool = True) -> str:
    """Build a Serum 2 patch from a single declarative spec in one reload.

    spec sections (all optional; absent = untouched):
      oscillators: [{index, mode?, params?}]   filters:   [{index, params}]
      envelopes:   [{index, params}]           lfos:      [{index, params}]
      macros:      [{index, value, name?}]     wavetables:[{index, table}]
      mod_routes:  [{source, dest_module, dest_index, dest_param, amount}]
      fx:          [{rack, slot, kparam, value}]   (Serum FX setters)
    Params are native, range-validated. Applies everything to one decoded tree then
    reloads once.

    Parameters:
    - track_index: track holding the Serum 2 instance.
    - spec: the patch description dict.
    - device_index: which VST/AU plugin device on the track (0 = first plugin).
    - reload: reload the set after patching (default True).

    Returns JSON {ok, data:{reloaded, set_path, applied}}."""
    try:
        get_ableton_connection()
        applied = {"oscillators": 0, "filters": 0, "envelopes": 0, "lfos": 0,
                   "macros": 0, "wavetables": 0, "mod_routes": 0, "fx": 0}
        def mutate_fn(catalog, tree):
            for o in spec.get("oscillators", []):
                if o.get("mode") is not None:
                    _spu.set_oscillator_mode(catalog, tree, o["index"], o["mode"])
                if o.get("params"):
                    _spu.set_module_params(catalog, tree, "oscillator", o["index"], o["params"])
                applied["oscillators"] += 1
            for mtype, key in (("filter", "filters"), ("envelope", "envelopes"), ("lfo", "lfos")):
                for m in spec.get(key, []):
                    _spu.set_module_params(catalog, tree, mtype, m["index"], m.get("params", {}))
                    applied[key] += 1
            for mc in spec.get("macros", []):
                _spu.set_macro(catalog, tree, mc["index"], mc["value"], name=mc.get("name"))
                applied["macros"] += 1
            for w in spec.get("wavetables", []):
                _spu.set_wavetable(catalog, tree, w["index"], w["table"])
                applied["wavetables"] += 1
            for r in spec.get("mod_routes", []):
                _spu.add_mod_route(catalog, tree, r["source"], r["dest_module"],
                                   r["dest_index"], r["dest_param"], r["amount"])
                applied["mod_routes"] += 1
            if spec.get("fx"):
                fxcat = _sfxcat.load_catalog()
                for f in spec["fx"]:
                    _sfx.set_fx_param(fxcat, tree, f["rack"], f["slot"], f["kparam"], f["value"])
                    applied["fx"] += 1
        result = _serum_fx_mutate_impl(
            track_index, device_index, mutate_fn, reload=reload,
            catalog_loader=_spcat.load_catalog,
            save_impl=lambda: _save_set_impl(name=""),
            reload_impl=lambda p, n: _reload_set(p, n))
        if not result.get("ok"):
            return _err(result.get("error", "create_serum_patch failed"))
        result["applied"] = applied
        return _ok(result)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        return _err(str(e))
    except Exception as e:
        logger.error("create_serum_patch error: %s", e)
        return _err("create_serum_patch error: %s" % e)


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
def swing_clip(
    ctx: Context, track_index: int, clip_index: int,
    amount: Union[float, int, str], grid: str = "1/16",
) -> str:
    """Apply swing (shuffle) to a clip by delaying off-beat notes. Bakes a real,
    non-faked swung feel into already-generated notes; reversible with `undo`.

    Parameters:
    - track_index / clip_index: locate the clip
    - amount: swing strength. A fraction 0.0-1.0 (0 = straight, 1 = max), OR an
      MPC-style percent (50 = straight, 66 ~ triplet, 75 = max) passed as a
      number > 1 or a string like "66%".
    - grid: swing grid, "1/8" or "1/16" (default "1/16"). Off-beat steps on this
      grid are delayed; on-beats are left in place.

    Works best on grid-quantized parts (generated basslines, drums, melodies).
    """
    try:
        fraction = groove.resolve_swing(amount)
        step = groove.grid_to_step(grid)
        count = _transform_clip(
            track_index, clip_index,
            lambda ns: groove.swing_notes(ns, step, fraction))
        return _ok({"notes": count, "grid": grid, "swing_fraction": fraction})
    except Exception as e:
        logger.error("Error swinging clip: %s", e)
        return _err("Error swinging clip: %s" % e)


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
def set_song_scale(ctx: Context, key: str, scale: str = "major") -> str:
    """Set the song's global scale - the "Scale" indicator in Live's control
    bar (root note + scale name). Aligns Live's scale-aware features (Scale
    highlight, scale-snapping MIDI tools) to the intended key. This does NOT
    move any existing notes - use quantize_clip_to_scale for that.

    Parameters:
    - key: root note name (C, C#, Db, D, ... B)
    - scale: a Live scale name or alias (e.g. major, minor, Dorian, Minor Blues,
      Harmonic Minor, Whole Tone); defaults to major

    Note: Song.root_note/scale_name lag their own read-back, so the confirmation
    is taken from a separate follow-up read of the song scale.
    """
    try:
        root, scale_name = comp.resolve_song_scale(key, scale)
        ableton = get_ableton_connection()
        ableton.send_command(
            "set_song_scale", {"root_note": root, "scale_name": scale_name})
        # Song-property writes lag their own read-back; verify via a separate read.
        confirmed = _song_scale() or {}
        return _ok({
            "root_note": confirmed.get("root_note", root),
            "scale_name": confirmed.get("scale_name", scale_name),
            "requested": {"root_note": root, "scale_name": scale_name},
        })
    except Exception as e:
        logger.error("Error setting song scale: %s", e)
        return _err("Error setting song scale: %s" % e)


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
def get_groove_pool(ctx: Context) -> str:
    """List the grooves currently in Live's Groove Pool.

    Returns each groove's pool index + name. Use an index or name with
    `assign_groove_to_clip`. The pool is populated by dragging grooves (or a
    .agr file) into the Groove Pool in Live; there is no LOM/MCP path to load a
    factory groove into the pool, so an empty pool means none have been added.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_groove_pool", {})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error getting groove pool: {str(e)}")
        return _err(f"Error getting groove pool: {str(e)}")


def _groove_search_roots(sources):
    """(root, label) pairs to walk for .agr grooves. 'factory' = running Live's
    Core Library/Grooves; 'user' = the configured User Library. Missing skipped."""
    roots = []
    if "factory" in sources:
        core = _app_core()
        if core:
            fac = os.path.join(core, "Grooves")
            if os.path.isdir(fac):
                roots.append((fac, "factory"))
    if "user" in sources:
        lib = _user_library_dir()
        if lib and os.path.isdir(lib):
            roots.append((lib, "user"))
    return roots


def _search_grooves_live(query, limit, sources):
    """Live filesystem walk fallback for search_grooves."""
    roots = _groove_search_roots(sources)
    rows = groovep.list_grooves(roots, query=query, limit=limit)
    return _ok({"count": len(rows), "returned": len(rows), "items": rows})


@mcp.tool()
def search_grooves(ctx: Context, query: str = "", limit: int = 50,
                   sources: list = None) -> str:
    """Search Live's groove library (.agr files) by name and category.

    There is no LOM/browser path to LIST grooves, so this filesystem-walks the
    running Live's factory Core Library/Grooves and/or the User Library. Use a
    returned `name` with `load_groove_to_pool` to add it to the Groove Pool.

    Parameters:
    - query: space-separated terms (OR) matched against name + folder. Empty
      string matches everything.
    - limit: max results (default 50).
    - sources: which trees to walk: ["factory","user"] (default both).

    Returns JSON {ok, data:{count, returned, items:[{name, file, category,
    path, source, loadable}]}}. `loadable` is False for the ~half of factory
    grooves stored in a binary .agr format that `load_groove_to_pool` cannot
    add (drag those in by hand); True grooves load fine.
    """
    sources = sources or ["factory", "user"]
    try:
        conn = _catalog_conn()
        _ensure_catalog_fresh(conn, ["groove"])
        res = _cat_query.search_catalog(conn, query, domains=["groove"],
                                        sources=sources, limit=limit)
        if res["count"] > 0:
            items = catalog_adapt.rows_to_groove_items(res["items"])
            if items:
                return _ok({"count": len(items), "returned": len(items),
                            "items": items})
    except Exception as e:
        logger.error("search_grooves catalog path failed, falling back: %s", e)
    try:
        return _search_grooves_live(query, limit, sources)
    except Exception as e:
        logger.error("Error searching grooves: %s", e)
        return _err("Error searching grooves: %s" % e)


def _factory_clip_wrapper():
    """A factory .alc (running Live's bundle) to use as a carrier wrapper. Its
    header MinorVersion already matches the running Live, so no version munging
    is needed. Returns decompressed XML or raises."""
    core = _app_core()
    hits = sorted(glob.glob("%s/MIDI Clips/**/*.alc" % core, recursive=True)) if core else []
    if not hits:
        raise RuntimeError("no factory .alc wrapper found under %s/MIDI Clips" % core)
    with gzip.open(hits[0], "rt") as f:
        return f.read()


def _carrier_uri(clip_name, retries=12, delay=1.0):
    """The browser item uri for a just-written User Library clip, or None.

    Live's content index takes a few seconds (~5s observed) to pick up a
    newly-written file, so poll get_browser_items_at_path until the carrier
    appears or `retries` elapse (the carrier is deleted after each call, so a
    fresh write re-incurs this lag every time)."""
    target = "%s.alc" % clip_name
    for attempt in range(retries):
        res = get_ableton_connection().send_command(
            "get_browser_items_at_path", {"path": "user_library/Clips"})
        items = res.get("items", []) if isinstance(res, dict) else []
        for it in items:
            if it.get("name") == target:
                return it.get("uri")
        if attempt < retries - 1:
            time.sleep(delay)
    return None


@mcp.tool()
def load_groove_to_pool(ctx: Context, name_or_path: str) -> str:
    """Add a factory or User-Library groove (.agr) to Live's Groove Pool.

    Resolves `name_or_path` (a groove name from `search_grooves`, or a full
    .agr path), then loads it into the pool via a temporary carrier clip so
    `assign_groove_to_clip` has something to bind. Returns the groove's POOL
    name + index (the pool name is the .agr's internal name, which may differ
    from the filename).

    If a groove with that pool name is already present, this is a no-op
    (`already_present: true`) - Live offers no way to REMOVE a pool groove via
    the API, so duplicates are avoided rather than cleaned up. To remove a
    groove, right-click it in Live's Groove Pool -> Remove; unsaved sets drop
    added grooves on close.

    About half of Ableton's factory grooves are stored in a proprietary BINARY
    .agr format this backdoor cannot load; those return a clear error (drag them
    in by hand). `search_grooves` flags each groove's `loadable` so you can pick
    one that works. User-Library and ~half the factory grooves are plain XML and
    load fine.

    Parameters:
    - name_or_path: groove name (case-insensitive, from `search_grooves`) or an
      absolute .agr path.
    """
    dest = None
    before_count = None
    try:
        roots = _groove_search_roots(["factory", "user"])
        agr_path = groovep.resolve_groove_source(name_or_path, roots)
        agr_xml = groovep.read_groove_xml(agr_path)
        pool_name = groovep.groove_pool_name(agr_xml)

        ableton = get_ableton_connection()
        pool = ableton.send_command("get_groove_pool", {}).get("grooves", [])
        existing = groovep.pool_has_name(pool, pool_name)
        if existing is not None:
            return _ok({"already_present": True, "groove_name": pool_name,
                        "pool_index": existing, "pool_count": len(pool),
                        "source": agr_path})

        entry = groovep.agr_to_pool_groove(agr_xml, groove_id=0)
        carrier = groovep.build_carrier_alc(_factory_clip_wrapper(), entry, 0)
        clip_name = "_mcp_groove_load"
        dest = _write_user_clip(carrier, clip_name)

        uri = _carrier_uri(clip_name)
        if not uri:
            return _err("Carrier clip written but Live hasn't indexed it yet. "
                        "Refresh the browser (right-click User Library -> "
                        "Refresh) or relaunch Live, then retry.")

        # Loading the carrier .alc makes Live merge its embedded groove into the
        # project pool. The carrier is a full-track clip, so the load APPENDS its
        # own track (it ignores the target track_index); we delete exactly the
        # appended track(s) afterward. No scratch track is created.
        si = ableton.send_command("get_session_info", {})
        before_count = si.get("track_count", 0)
        load = ableton.send_command(
            "load_browser_item",
            {"track_index": max(0, before_count - 1), "item_uri": uri})
        if not load.get("loaded", False):
            return _err("load_browser_item did not confirm: %s"
                        % load.get("message", ""))

        pool2 = ableton.send_command("get_groove_pool", {}).get("grooves", [])
        idx = groovep.pool_has_name(pool2, pool_name)
        if idx is None:
            return _err("Carrier loaded but the groove did not appear in the "
                        "pool. Try again, or drag the .agr into the Groove Pool "
                        "by hand.")
        return _ok({"already_present": False, "groove_name": pool_name,
                    "pool_index": idx, "pool_count": len(pool2),
                    "source": agr_path})
    except Exception as e:
        logger.error(f"Error loading groove to pool: {str(e)}")
        return _err(f"Error loading groove to pool: {str(e)}")
    finally:
        # Delete the track(s) the carrier load appended, highest index first so
        # earlier indices don't shift. The user's original tracks (indices
        # 0..before_count-1) are never touched.
        try:
            if before_count is not None:
                after = get_ableton_connection().send_command(
                    "get_session_info", {}).get("track_count", before_count)
                for i in range(after - 1, before_count - 1, -1):
                    get_ableton_connection().send_command(
                        "delete_track", {"index": i})
        except Exception:
            pass
        try:
            if dest and os.path.exists(dest):
                os.remove(dest)
        except Exception:
            pass


@mcp.tool()
def assign_groove_to_clip(
    ctx: Context, track_index: int, clip_index: int,
    groove: Union[int, str],
) -> str:
    """Assign a groove from the Groove Pool to a clip (swings/shuffles playback).

    Unlike `swing_clip` (which bakes timing into the notes), this binds a Live
    groove to the clip so its feel is applied non-destructively at playback;
    `set_groove_amount` then scales how strongly it is applied.

    Parameters:
    - track_index / clip_index: locate the clip (regular tracks; MIDI or audio).
    - groove: which Groove-Pool groove to assign - a pool index (int, from
      `get_groove_pool`) or an exact groove name (str). A numeric string is
      treated as a name, not an index.

    The groove must already be in the Groove Pool (see `get_groove_pool`); drag
    one in first if the pool is empty. Reversible with `undo`. Clearing a clip's
    groove via this tool is not supported (Live's API rejects a null groove).
    """
    try:
        sel = normalize_groove_selector(groove)
        ableton = get_ableton_connection()
        result = ableton.send_command("assign_groove_to_clip", {
            "track_index": track_index, "clip_index": clip_index,
            "by": sel["by"], "value": sel["value"]})
        return _ok(result)
    except Exception as e:
        logger.error(f"Error assigning groove to clip: {str(e)}")
        return _err(f"Error assigning groove to clip: {str(e)}")
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
_APP_CORE = plat.core_library_glob(sys.platform)
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
    hits = sorted(glob.glob(plat.core_library_glob(sys.platform, major)))
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
            "Factory default %s/%s not found under %s. "
            "Is Ableton Live (11 or 12) Suite installed?"
            % (category, filename, _app_core())
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
    if IS_WINDOWS:
        cfgs = [os.path.join(d, "Library.cfg") for d in reversed(_win_pref_dirs())]
    else:
        cfgs = sorted(
            glob.glob(os.path.join(_prefs_base(), "Live *", "Library.cfg")),
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
        if IS_WINDOWS:            # Library.cfg stores 'C:/Users/...' (slashes)
            base = os.path.normpath(base)
        for cand in (os.path.join(base, "User Library"), base):
            if os.path.isdir(os.path.join(cand, "Presets")):
                return cand
    return plat.user_library_fallback(sys.platform, os.path.expanduser("~"))


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


def _write_user_clip(xml, name):
    """Gzip-write a carrier .alc to <UserLib>/Clips/<name>.alc. Returns the
    dest path. The browser indexes it under user_library/Clips."""
    lib = _user_library_dir()
    dest_dir = os.path.join(lib, "Clips")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "%s.alc" % name)
    with gzip.open(dest, "wt") as f:
        f.write(xml)
    return dest


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

def _ensure_local(sample_path, timeout=30):
    """Materialize an iCloud-dataless sample so its bytes are on disk.

    1. If the file already exists locally, return its path.
    2. Else if a '.<name>.icloud' placeholder stub exists, run `brctl download`
       and poll (synchronously) up to `timeout` seconds for the real file.
    3. On timeout, or if the path is simply missing, raise RuntimeError with
       user-facing guidance.

    Synchronous blocking poll by design -- this runs server-side, not in the
    Remote Script. Must be called by every loader BEFORE any header read
    (_read_audio_meta opens the file and would fail on a placeholder).
    """
    sample_path = os.path.expanduser(str(sample_path))
    if os.path.exists(sample_path):
        return sample_path

    stub = icloud_placeholder_path(sample_path)
    if stub is None:
        raise RuntimeError(
            "Sample not found and no iCloud placeholder present: %s" % sample_path)

    if not IS_WINDOWS:     # iCloud is macOS-only; OneDrive hydrates on read
        try:
            subprocess.run(["/usr/bin/brctl", "download", sample_path],
                           timeout=timeout, check=False)
        except Exception as e:
            logger.warning("brctl download failed for %s: %s", sample_path, e)

    deadline = time.monotonic() + max(1, timeout)
    while time.monotonic() < deadline:
        if os.path.exists(sample_path):
            return sample_path
        time.sleep(0.5)

    raise RuntimeError(
        "Sample is still an undownloaded iCloud placeholder after %ss: %s. "
        "Download it in Finder (or right-click -> Download Now) and retry."
        % (timeout, sample_path))


def _resolve_sample_uri(sample_path, category="samples"):
    """Resolve a sample file path to its Live browser URI via the Remote Script.

    The LOM browser exposes a sample's name + uri but not its filesystem path,
    so the loaders (which hold the path from a filesystem walk) resolve the uri
    here by base name. Matches the first browser item with that name (a
    duplicate name across packs resolves to the first match). Raises
    RuntimeError if the sample is not indexed in the browser.
    """
    name = os.path.basename(sample_path)
    ableton = get_ableton_connection()
    res = ableton.send_command("find_sample_uri", {"name": name, "category": category})
    uri = (res or {}).get("uri")
    if not uri:
        raise RuntimeError(
            "Could not resolve '%s' to a browser item. Live may not have indexed "
            "it yet (refresh the browser or relaunch Live), or it is in a category "
            "other than '%s'." % (name, category))
    return uri


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

# Audio sample file extensions enumerated by search_samples. Preset extensions
# (.adv/.adg) are also enumerated so kits/instruments surface.
_SAMPLE_EXTS = (".wav", ".aif", ".aiff", ".aifc", ".flac", ".mp3", ".ogg",
                ".adv", ".adg")


def _sample_search_roots(sources):
    """Resolve (root_dir, source_label) pairs to walk for the given sources.

    'user'   -> the configured User Library (iCloud-backed).
    'factory'-> the running Live's Core Library Samples tree (per Task 1 spike).
    Missing roots are skipped. Seam: monkeypatched in tests.
    """
    roots = []
    if "user" in sources:
        lib = _user_library_dir()
        if lib and os.path.isdir(lib):
            roots.append((lib, "user"))
    if "factory" in sources:
        core = _app_core()
        if core:
            fac = os.path.join(core, "Samples")
            if os.path.isdir(fac):
                roots.append((fac, "factory"))
    return roots


def _search_samples_live(query, kinds, limit, sources):
    """Live filesystem walk fallback for search_samples."""
    kind_set = set(kinds)
    hits = []
    for root, source in _sample_search_roots(sources):
        for dirpath, _dirs, filenames in os.walk(root):
            for fn in filenames:
                # iCloud stubs are hidden ".<name>.icloud" files; recover the
                # real sample name + path from the stub so placeholders surface.
                is_stub = fn.startswith(".") and fn.endswith(".icloud")
                if is_stub:
                    real_name = fn[1:-len(".icloud")]
                else:
                    real_name = fn
                ext = os.path.splitext(real_name)[1].lower()
                if ext not in _SAMPLE_EXTS:
                    continue
                real_path = os.path.join(dirpath, real_name)
                rel_folder = os.path.relpath(dirpath, root)
                matched, score = name_match(query, real_name, rel_folder)
                if not matched:
                    continue
                kind = classify_sample(real_name, os.path.join(rel_folder, real_name))
                if kind not in kind_set:
                    continue
                hits.append({
                    "name": real_name,
                    "path": real_path,
                    "uri": None,
                    "kind": kind,
                    "source": source,
                    "folder": rel_folder,
                    "is_icloud_placeholder": icloud_placeholder_path(real_path) is not None,
                    "_score": score,
                })

    hits.sort(key=lambda h: h["_score"], reverse=True)
    total = len(hits)
    shown = hits[:limit] if limit and limit > 0 else hits
    for h in shown:
        h.pop("_score", None)
    for h in hits[len(shown):]:
        h.pop("_score", None)
    return _ok({
        "count": total,
        "returned": len(shown),
        "truncated": len(shown) < total,
        "items": shown,
    })


@mcp.tool()
def search_samples(
    ctx: Context,
    query: str,
    kinds: list = None,
    limit: int = 40,
    sources: list = None,
) -> str:
    """Search Live's sample library by name and return classified, ranked hits.

    Filesystem-walks the User Library and/or factory Core Library sample trees,
    matching `query` (space-separated terms, OR) against each file's name and
    folder, classifying each hit (loop / one_shot / kit / instrument), and
    returning the top `limit` by match score. READ-only: it never downloads --
    it only FLAGS files that are undownloaded iCloud placeholders so a later
    load knows to materialize them.

    Parameters:
    - query: space-separated search terms (OR). Empty string matches everything.
    - kinds: restrict to these classifications (default all four:
      ["loop","one_shot","kit","instrument"]).
    - limit: max results to return (default 40).
    - sources: which trees to walk: ["factory","user"] (default both).

    Returns JSON {ok, data:{count, returned, truncated, items:[{name, path,
    uri, kind, source, folder, is_icloud_placeholder}]}}. `count` is total
    matches; `items` holds at most `limit`, highest score first. `uri` is None
    (loaders take `sample_path`, not a browser URI).
    """
    kinds = kinds or ["loop", "one_shot", "kit", "instrument"]
    sources = sources or ["factory", "user"]
    try:
        conn = _catalog_conn()
        _ensure_catalog_fresh(conn, ["sample"])
        res = _cat_query.search_catalog(conn, query, domains=["sample"],
                                        kinds=kinds, sources=sources, limit=limit)
        if res["count"] > 0:
            items = catalog_adapt.rows_to_sample_items(res["items"])
            return _ok({"count": res["count"], "returned": len(items),
                        "truncated": res["truncated"], "items": items})
    except Exception as e:
        logger.error("search_samples catalog path failed, falling back: %s", e)
    try:
        return _search_samples_live(query, kinds, limit, sources)
    except Exception as e:
        logger.error("Error searching samples: %s", e)
        return _err("Error searching samples: %s" % e)


# ---------------------------------------------------------------------------
# Stem separation helpers (host-side subprocess runners + layout)
# ---------------------------------------------------------------------------

_BREW_PY = "/opt/homebrew/bin/python3"


def _analysis_python():
    """Command prefix for the interpreter that runs the librosa scripts, or
    None. ABLETON_MCP_ANALYSIS_PYTHON overrides; otherwise brew python on
    macOS and the `py -3` launcher on Windows. An interpreter without librosa
    just makes the script fail, which the callers already degrade on."""
    override = os.environ.get("ABLETON_MCP_ANALYSIS_PYTHON")
    if override:
        return [override] if os.path.exists(override) else None
    if IS_WINDOWS:
        launcher = shutil.which("py")
        return [launcher, "-3"] if launcher else None
    return [_BREW_PY] if os.path.exists(_BREW_PY) else None


_ANALYZE_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts", "analyze_audio.py")


def _run_demucs(audio_path, model, out_dir, device, timeout=1200):
    """Run the Demucs CLI. Returns (ok, message). Raises nothing."""
    cmd = stem_utils.build_demucs_cmd(audio_path, model, out_dir, device)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return (False, "demucs CLI not found on PATH. Install it: "
                       "pip3 install --break-system-packages demucs")
    except subprocess.TimeoutExpired:
        return (False, "demucs timed out after %ds" % timeout)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-5:]
        return (False, "demucs failed (exit %d): %s"
                % (proc.returncode, " | ".join(tail)))
    return (True, "ok")


def _run_analysis(audio_path, timeout=120):
    """Run analyze_audio.py under brew python. Returns (tempo, key, scale).

    Degrades gracefully: any failure (no brew python, librosa missing, decode
    error) yields (None, None, None) so the caller keeps the default tempo.
    """
    py = _analysis_python()
    if not py:
        return (None, None, None)
    try:
        proc = subprocess.run(
            py + [_ANALYZE_SCRIPT, audio_path],
            capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return (None, None, None)
    if proc.returncode != 0 or not proc.stdout.strip():
        return (None, None, None)
    return stem_utils.parse_analysis(proc.stdout.strip().splitlines()[-1])


_CHROMA_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts",
                              "chroma_profile.py")


def _run_chroma(items, timeout=180):
    """Run scripts/chroma_profile.py under brew python on a list of
    {path, transpose} dicts. Returns {profile, analyzed, skipped} or None on any
    failure (so the caller degrades to MIDI-only)."""
    py = _analysis_python()
    if not items or not py:
        return None
    try:
        proc = subprocess.run(
            py + [_CHROMA_SCRIPT], input=json.dumps(items),
            capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        out = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        return None
    if "error" in out or "profile" not in out:
        return None
    return out


def _stem_uri(browser_folder, stem_filename, retries=12, delay=1.0):
    """Browser uri for a just-written User Library stem file, or None.

    Live's content index takes a few seconds to pick up a newly-written file,
    so poll get_browser_items_at_path on the stem's SPECIFIC folder (fast, and
    unambiguous - no deep name walk, no cross-song basename collision) until the
    file appears or `retries` elapse. browser_folder is a get_browser_items_at_path
    path like "user_library/Samples/Stems/htdemucs/<basename>".
    """
    for attempt in range(retries):
        res = get_ableton_connection().send_command(
            "get_browser_items_at_path", {"path": browser_folder})
        items = res.get("items", []) if isinstance(res, dict) else []
        for it in items:
            if it.get("name") == stem_filename and it.get("uri"):
                return it.get("uri")
        if attempt < retries - 1:
            time.sleep(delay)
    return None


def _lay_stem_on_track(ableton, track_index, stem_name, uri, sample_path):
    """Load a resolved stem uri into session slot 0, warp off + name it,
    duplicate to arrangement at bar 1, then delete the session staging clip.

    Returns dict {name, track_index, path, loaded}.
    """
    ableton.send_command("set_highlighted_clip_slot",
                         {"track_index": track_index, "scene_index": 0})
    res = ableton.send_command("load_browser_item", {
        "track_index": track_index, "item_uri": uri, "track_type": "regular"})
    loaded = bool((res or {}).get("loaded", False))
    if not loaded:
        return {"name": stem_name, "track_index": track_index,
                "path": sample_path, "loaded": False}
    # Name on the SESSION clip; the arrangement copy inherits it. Do NOT unwarp
    # the session clip here - leaving it warped lets the arrangement-clip
    # normalize below (warp off, fresh) extend end_marker to the full sample.
    # Pre-unwarping the session clip puts it in a state the normalize can't
    # extend (the placed clip stays truncated to the warp-derived beat count).
    ableton.send_command("set_clip_name", {
        "track_index": track_index, "clip_index": 0, "name": stem_name})
    ableton.send_command("set_track_name", {
        "track_index": track_index, "name": stem_name})
    # Live auto-warps the loaded sample, which truncates the placed clip to the
    # warp-derived beat count. Normalize the placed arrangement clip: warp off +
    # end_marker to the full sample length (seconds) so the whole stem plays.
    _size, frames, rate = _read_audio_meta(sample_path)
    clip_seconds = float(frames) / rate if rate else 0.0
    ableton.send_command("duplicate_clip_to_arrangement", {
        "track_index": track_index, "source_slot_index": 0,
        "destination_time": 0.0,
        "warp_off": True, "clip_seconds": clip_seconds})
    ableton.send_command("delete_clip", {
        "track_index": track_index, "clip_index": 0})
    return {"name": stem_name, "track_index": track_index,
            "path": sample_path, "loaded": True}


@mcp.tool()
def separate_stems_to_arrangement(
    ctx: Context,
    audio_path: str,
    model: str = "htdemucs",
    fresh: bool = False,
    detect_tempo: bool = True,
    detect_key: bool = True,
    device: str = "auto",
) -> str:
    """Split an audio file into stems and lay each onto its own Arrangement track.

    Uses the Demucs CLI to separate `audio_path` into stems, optionally detects
    the source tempo + key (librosa, via scripts/analyze_audio.py) and applies
    them to the open set, then creates one audio track per stem and places each
    stem at bar 1 of the Arrangement timeline (Warp OFF, so full-song stems stay
    phase-locked). Session view is used only as transient staging; the end state
    has empty session slots.

    Stems are written under the Live User Library (Samples/Stems/<model>/<name>)
    so Live's browser indexes them and they can be loaded; they persist there
    (the Arrangement clips reference these files on disk).

    Prerequisites: the `demucs` CLI on PATH and (for tempo/key) librosa in brew
    Python. See the README "Stem separation" prerequisites; a clear error is
    returned when demucs is missing and analysis degrades gracefully without
    librosa.

    Parameters:
    - audio_path: absolute path to the mixed audio file.
    - model: "htdemucs" (4-stem, default), "htdemucs_6s" (6-stem), or "two_stems".
    - fresh: when True, bounce Live to a blank set FIRST (discards the open set).
      The CALLER must confirm with the user before passing fresh=True.
    - detect_tempo / detect_key: analyze the source and set tempo / song scale.
    - device: "auto" (mps on Apple Silicon, else cpu), "cpu", or "mps".

    Returns JSON {ok, data:{audio, model, device, tempo, key, scale,
    tempo_detected, key_detected, fresh, stems:[{name, track_index, path,
    loaded}]}}.
    """
    try:
        try:
            spec = stem_utils.validate_model(model)
        except ValueError as e:
            return _err(str(e))

        local_src = _ensure_local(audio_path)
        if not os.path.isfile(local_src):
            return _err("Audio file not found: %s" % audio_path)

        resolved_device = stem_utils.resolve_device(device, platform.machine())
        # Write stems under the User Library so Live's browser indexes them.
        out_dir = os.path.join(_user_library_dir(), "Samples", "Stems")
        os.makedirs(out_dir, exist_ok=True)

        ok, msg = _run_demucs(local_src, model, out_dir, resolved_device)
        if not ok:
            return _err(msg)

        basename = os.path.splitext(os.path.basename(local_src))[0]
        stem_paths = stem_utils.expected_stem_paths(out_dir, model, basename)
        missing = [p for _, p in stem_paths if not os.path.isfile(p)]
        if missing:
            return _err("Demucs produced no output for: %s" % ", ".join(missing))

        browser_folder = "user_library/Samples/Stems/%s/%s" % (
            spec["demucs_model"], basename)

        tempo, key, scale = (None, None, None)
        if detect_tempo or detect_key:
            tempo, key, scale = _run_analysis(local_src)

        ableton = get_ableton_connection()

        if fresh:
            try:
                restart_result = _restart_live_impl(save="discard")
                if not restart_result.get("quit"):
                    return _err(
                        "fresh=True could not bounce Live to a blank set: %s. "
                        "Save / name the open set by hand first (save_set_as), "
                        "then retry." % restart_result.get(
                            "error", "Live did not quit cleanly"))
                ableton = get_ableton_connection()
            except Exception as e:
                return _err("fresh=True could not reach a blank set (%s). Save / "
                            "name the open set by hand first, then retry." % e)

        if detect_tempo and tempo:
            ableton.send_command("set_tempo", {"tempo": tempo})
        if detect_key and key:
            root, scale_name = comp.resolve_song_scale(key, scale or "major")
            ableton.send_command(
                "set_song_scale", {"root_note": root, "scale_name": scale_name})

        info = ableton.send_command("get_session_info") or {}
        next_index = int(info.get("track_count", 0))

        stems_out = []
        for stem_name, path in stem_paths:
            ableton.send_command("create_audio_track", {"index": -1})
            uri = _stem_uri(browser_folder, os.path.basename(path))
            if not uri:
                stems_out.append({"name": stem_name, "track_index": next_index,
                                  "path": path, "loaded": False})
            else:
                stems_out.append(
                    _lay_stem_on_track(ableton, next_index, stem_name, uri, path))
            next_index += 1

        return _ok({
            "audio": local_src,
            "model": spec["demucs_model"],
            "device": resolved_device,
            "tempo": tempo,
            "key": key,
            "scale": scale,
            "tempo_detected": bool(detect_tempo and tempo),
            "key_detected": bool(detect_key and key),
            "fresh": fresh,
            "stems": stems_out,
        })
    except Exception as e:
        logger.error("Error in separate_stems_to_arrangement: %s", e)
        return _err("Error in separate_stems_to_arrangement: %s" % e)


@mcp.tool()
def load_audio_clip(
    ctx: Context,
    track_index: int,
    clip_index: int,
    sample_path: str,
    track_type: str = "regular",
) -> str:
    """Load an audio sample (typically a loop) into an audio clip slot.

    Materializes the file from iCloud if needed, resolves its browser URI, selects
    the target slot, and loads it (Live creates an audio clip in that slot). Reads
    the file header to report the clip's refined kind (a long one-shot is reported
    as a loop).

    Parameters:
    - track_index: index of the audio track.
    - clip_index: clip slot index on that track.
    - sample_path: absolute path to the sample (as returned by search_samples).
    - track_type: "regular" (default). Audio clips are a regular-track concept.

    Returns JSON {ok, data:{track_index, clip_index, sample, uri, frames,
    sample_rate, kind, loaded}}.
    """
    try:
        local = _ensure_local(sample_path)
        size, frames, rate = _read_audio_meta(local)
        uri = _resolve_sample_uri(local, "samples")
        ableton = get_ableton_connection()
        tempo = 120.0
        try:
            tempo = float(ableton.send_command("get_transport").get("tempo", 120.0))
        except Exception:
            pass
        ableton.send_command("set_highlighted_clip_slot",
                             {"track_index": track_index, "scene_index": clip_index})
        result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": uri,
            "track_type": track_type,
        })
        loaded = bool(result.get("loaded", False))
        if not loaded:
            return _err("Failed to load audio clip from %s (load_browser_item did "
                        "not confirm)." % os.path.basename(local))
        kind = refine_kind_by_length(
            classify_sample(os.path.basename(local), local), frames, rate, tempo)
        return _ok({
            "track_index": track_index,
            "clip_index": clip_index,
            "sample": local,
            "uri": uri,
            "frames": frames,
            "sample_rate": rate,
            "kind": kind,
            "loaded": True,
        })
    except RuntimeError as e:
        return _err("Error: %s" % e)
    except Exception as e:
        logger.error("Error loading audio clip: %s", e)
        return _err("Error loading audio clip: %s" % e)


@mcp.tool()
def load_sample_to_drum_pad(
    ctx: Context,
    track_index: int,
    pad_note: int,
    sample_path: str,
) -> str:
    """Load a one-shot sample onto a single Drum Rack pad.

    Materializes the file from iCloud if needed, resolves its browser URI, selects
    the pad for `pad_note` (MIDI note, e.g. 36 = C1) on the track's Drum Rack, and
    loads the sample so it lands on that pad.

    Parameters:
    - track_index: index of the track holding the Drum Rack.
    - pad_note: MIDI note number of the target pad.
    - sample_path: absolute path to the one-shot (as returned by search_samples).

    Returns JSON {ok, data:{track_index, pad_note, sample, uri, loaded}}.
    """
    try:
        local = _ensure_local(sample_path)
        uri = _resolve_sample_uri(local, "samples")
        ableton = get_ableton_connection()
        sel = ableton.send_command(
            "select_drum_pad", {"track_index": track_index, "pad_note": pad_note})
        if not (sel or {}).get("selected", False):
            return _err("Could not select pad %s on track %s: %s"
                        % (pad_note, track_index, (sel or {}).get("error", "unknown")))
        result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": uri,
        })
        loaded = bool(result.get("loaded", False))
        if not loaded:
            return _err("Failed to load %s onto pad %s of track %s."
                        % (os.path.basename(local), pad_note, track_index))
        return _ok({
            "track_index": track_index,
            "pad_note": pad_note,
            "sample": local,
            "uri": uri,
            "loaded": True,
        })
    except RuntimeError as e:
        return _err("Error: %s" % e)
    except Exception as e:
        logger.error("Error loading sample to drum pad: %s", e)
        return _err("Error loading sample to drum pad: %s" % e)


@mcp.tool()
def populate_drum_rack(
    ctx: Context,
    track_index: int,
    mapping: list,
) -> str:
    """Load many one-shot samples onto many Drum Rack pads in one call.

    Loops load_sample_to_drum_pad over `mapping`. Does NOT abort on the first
    failure -- each entry's result is reported so partial failures are visible.

    Parameters:
    - track_index: index of the track holding the Drum Rack.
    - mapping: list of {pad_note, sample_path}.

    Returns JSON {ok, data:{track_index, loaded_count, results:[{pad_note,
    sample_path, status:"loaded"|"error", error?}]}}.
    """
    try:
        if not isinstance(mapping, list) or not mapping:
            return _err("mapping must be a non-empty list of {pad_note, sample_path}.")
        results = []
        loaded_count = 0
        for entry in mapping:
            if not isinstance(entry, dict) or "pad_note" not in entry \
                    or "sample_path" not in entry:
                return _err("Each mapping entry needs 'pad_note' and 'sample_path'; "
                            "got %r." % (entry,))
            pad_note = entry["pad_note"]
            sample_path = entry["sample_path"]
            raw = load_sample_to_drum_pad(
                ctx, track_index=track_index, pad_note=pad_note,
                sample_path=sample_path)
            res = json.loads(raw)
            if res.get("ok"):
                loaded_count += 1
                results.append({"pad_note": pad_note, "sample_path": sample_path,
                                "status": "loaded"})
            else:
                results.append({"pad_note": pad_note, "sample_path": sample_path,
                                "status": "error",
                                "error": res.get("error", "unknown error")})
        return _ok({
            "track_index": track_index,
            "loaded_count": loaded_count,
            "results": results,
        })
    except Exception as e:
        logger.error("Error populating drum rack: %s", e)
        return _err("Error populating drum rack: %s" % e)


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


@mcp.tool()
def detect_key(ctx: Context, source: str = "auto",
               audio_weight: float = 0.5, top_n: int = 5) -> str:
    """Detect the most likely musical key from the open set's combined content
    (MIDI notes + offline audio files), independent of Live's configured scale.

    Parameters:
    - source: "auto" (MIDI + audio files; default), "midi", or "audio".
      ("tap" is not yet supported.)
    - audio_weight: 0..1 blend of the audio histogram vs MIDI (default 0.5).
    - top_n: number of ranked candidates to return (default 5).

    Returns {ok, data} where data has detected_key, confidence, candidates,
    relative_key, pitch_class_histogram, sources, live_scale, matches_live.
    """
    if source == "tap":
        return _err("tap source not yet supported")
    if source not in ("auto", "midi", "audio"):
        return _err("source must be one of: auto, midi, audio")
    top_n = max(1, int(top_n))
    try:
        ableton = get_ableton_connection()
        contents = ableton.send_command("get_clip_contents", {})
        clips = (contents or {}).get("clips", [])

        midi_hist = [0.0] * 12
        midi_clips = midi_notes = 0
        if source in ("auto", "midi"):
            for c in clips:
                if not c.get("is_midi"):
                    continue
                res = ableton.send_command("get_clip_notes", {
                    "track_index": c["track_index"],
                    "clip_index": c["clip_index"],
                    "from_time": 0.0, "time_span": -1.0,
                    "from_pitch": 0, "pitch_span": 128})
                notes = (res or {}).get("notes", [])
                if not notes:
                    continue
                ch = kd.histogram_from_notes(notes, int(c.get("pitch_coarse", 0)))
                midi_hist = [midi_hist[i] + ch[i] for i in range(12)]
                midi_clips += 1
                midi_notes += len(notes)

        audio_hist = [0.0] * 12
        audio_info = {"clips": 0, "analyzed": 0, "skipped": 0, "mode": "offline"}
        if source in ("auto", "audio"):
            items = []
            for c in clips:
                if c.get("is_midi") or not c.get("file_path"):
                    continue
                audio_info["clips"] += 1
                try:
                    local = _ensure_local(c["file_path"])
                except Exception:
                    audio_info["skipped"] += 1
                    continue
                items.append({"path": local,
                              "transpose": int(c.get("pitch_coarse", 0))})
            chroma = _run_chroma(items) if items else None
            if chroma is None:
                if items:
                    audio_info["mode"] = "unavailable"
                    audio_info["skipped"] += len(items)
            else:
                audio_hist = kd.histogram_from_chroma(chroma["profile"], 0)
                audio_info["analyzed"] = chroma.get("analyzed", 0)
                audio_info["skipped"] += chroma.get("skipped", 0)

        combined = kd.combine(midi_hist, audio_hist, audio_weight)
        if sum(combined) <= 0:
            return _err("no usable MIDI notes or audio content to analyze")

        candidates = kd.detect_key(combined, top_n=top_n)
        best = candidates[0]
        rel_pc, rel_mode = kd.relative_key(best["root_pc"], best["mode"])

        live = _song_scale()
        matches = None
        if live is not None and live.get("root_note") is not None:
            root_name = kd.PITCH_NAMES[int(live["root_note"]) % 12]
            live_name = "%s %s" % (root_name,
                                   "major" if str(live.get("scale_name", "")
                                                  ).lower().startswith("maj")
                                   else "minor")
            matches = (live_name.lower() == best["key"].lower())

        total = sum(combined) or 1.0
        data = {
            "detected_key": best["key"],
            "confidence": best["confidence"],
            "candidates": candidates,
            "relative_key": kd.key_name(rel_pc, rel_mode),
            "pitch_class_histogram": [round(x / total, 4) for x in combined],
            "sources": {
                "midi": {"clips": midi_clips, "notes": midi_notes},
                "audio": audio_info,
                "audio_weight": audio_weight,
            },
            "live_scale": live,
            "matches_live": matches,
        }
        return _ok(data)
    except Exception as e:
        logger.error("Error detecting key: %s", e)
        return _err("Error detecting key: %s" % e)


# --- Local catalog -------------------------------------------------------
_catalog_db_conn = None
_catalog_checked = {}
_CATALOG_THROTTLE_S = 60
_catalog_device_indexed = False
_catalog_live_disconnected = False


def _catalog_conn():
    global _catalog_db_conn
    if _catalog_db_conn is None:
        _catalog_db_conn = _cat_db.open_db()
    return _catalog_db_conn


def _serum_roots():
    return [(path, label) for path, label in plat.serum_preset_roots(
                sys.platform, os.path.expanduser("~"), _documents_dir())
            if os.path.isdir(path)]


def _browser_reader(path):
    return get_ableton_connection().send_command(
        "get_browser_presets", {"path": path, "max_depth": 6})


def _ensure_device_index(conn, force=False):
    """Index device presets once per session (or force). Sets
    _catalog_live_disconnected when Live is unreachable. Never raises."""
    global _catalog_device_indexed, _catalog_live_disconnected
    if _catalog_device_indexed and not force:
        return
    try:
        _cat_index.index_device_presets(
            conn, _browser_reader, ["instruments", "audio_effects"])
        _catalog_device_indexed = True
        _catalog_live_disconnected = False
    except _cat_index.DeviceLiveUnavailable:
        _catalog_live_disconnected = True
    except Exception as e:
        _catalog_live_disconnected = True
        logger.error("device-preset auto-index failed: %s", e)


def _ensure_catalog_fresh(conn, domains):
    """Reindex any changed roots for the given domains, honoring a per-root
    in-process throttle. Never raises - freshness is best-effort."""
    now = time.time()
    try:
        if "serum" in domains:
            for root, src in _serum_roots():
                key = ("serum", root, src)
                if now - _catalog_checked.get(key, 0) < _CATALOG_THROTTLE_S:
                    continue
                _catalog_checked[key] = now
                if _cat_index.root_changed(conn, root, "serum", src):
                    _cat_index.index_serum(conn, [(root, src)])
        if "sample" in domains:
            for root, src in _sample_search_roots(["factory", "user"]):
                key = ("sample", root, src)
                if now - _catalog_checked.get(key, 0) < _CATALOG_THROTTLE_S:
                    continue
                _catalog_checked[key] = now
                if _cat_index.root_changed(conn, root, "sample", src):
                    _cat_index.index_samples(conn, [(root, src)])
        if "groove" in domains:
            for root, src in _groove_search_roots(["factory", "user"]):
                key = ("groove", root, src)
                if now - _catalog_checked.get(key, 0) < _CATALOG_THROTTLE_S:
                    continue
                _catalog_checked[key] = now
                if _cat_index.root_changed(conn, root, "groove", src):
                    _cat_index.index_grooves(conn, [(root, src)])
    except Exception as e:
        logger.error("catalog freshness check failed: %s", e)


@mcp.tool()
def search_catalog(ctx: Context, query: str, domains: list = None,
                   kinds: list = None, sources: list = None,
                   limit: int = 50) -> str:
    """Search the local content catalog (Serum presets, samples, grooves, device
    presets) by name/folder/tags. Fast persistent index; auto-refreshes changed
    filesystem roots. Returns {ok, data:{count, returned, truncated, items}}."""
    try:
        conn = _catalog_conn()
        want = domains or ["serum", "sample", "groove", "device_preset"]
        _ensure_catalog_fresh(conn, [d for d in want
                                     if d in ("serum", "sample", "groove")])
        if domains is None or "device_preset" in domains:
            _ensure_device_index(conn)
        data = _cat_query.search_catalog(conn, query, domains=domains,
                                         kinds=kinds, sources=sources, limit=limit)
        if domains is None or "device_preset" in domains:
            data["live_disconnected"] = _catalog_live_disconnected
        return _ok(data)
    except Exception as e:
        logger.error("search_catalog error: %s", e)
        return _err("search_catalog error: %s" % e)


@mcp.tool()
def catalog_stats(ctx: Context) -> str:
    """Counts and freshness for the local catalog by domain/source/kind, plus
    per-root last-indexed times. Returns {ok, data:{total, by_domain, by_source,
    by_kind, roots, device_presets_last_indexed}}."""
    try:
        conn = _catalog_conn()
        return _ok(_cat_query.catalog_stats(conn))
    except Exception as e:
        logger.error("catalog_stats error: %s", e)
        return _err("catalog_stats error: %s" % e)


@mcp.tool()
def find_similar(ctx: Context, intent: str, domain: str, limit: int = 10) -> str:
    """Rank catalog assets in one domain by lexical similarity to an intent
    string, with scores. domain in serum|sample|groove|device_preset. Returns
    {ok, data:{items:[{name, path, uri, source, folder, kind, score}]}}."""
    try:
        conn = _catalog_conn()
        if domain in ("serum", "sample", "groove"):
            _ensure_catalog_fresh(conn, [domain])
        if domain == "device_preset":
            _ensure_device_index(conn)
        hits = _cat_query.find_similar(conn, intent, domain, limit=limit)
        data = {"count": len(hits), "items": hits}
        if domain == "device_preset":
            data["live_disconnected"] = _catalog_live_disconnected
        return _ok(data)
    except Exception as e:
        logger.error("find_similar error: %s", e)
        return _err("find_similar error: %s" % e)


@mcp.tool()
def reindex_catalog(ctx: Context, domains: list = None,
                    full: bool = False) -> str:
    """Rebuild the catalog. domains defaults to all. full=True drops and rebuilds
    from scratch. Device presets reindex only when Live is connected. Returns
    {ok, data:{indexed:{domain:count}, errors:[...]}}."""
    try:
        conn = _catalog_conn()
        want = domains or ["serum", "sample", "groove", "device_preset"]
        if full:
            _cat_db.rebuild(conn)
            _catalog_checked.clear()
        indexed, errors = {}, []
        if "serum" in want:
            indexed["serum"] = _cat_index.index_serum(conn, _serum_roots())
        if "sample" in want:
            indexed["sample"] = _cat_index.index_samples(
                conn, _sample_search_roots(["factory", "user"]))
        if "groove" in want:
            indexed["groove"] = _cat_index.index_grooves(
                conn, _groove_search_roots(["factory", "user"]))
        if "device_preset" in want:
            global _catalog_device_indexed, _catalog_live_disconnected
            try:
                indexed["device_preset"] = _cat_index.index_device_presets(
                    conn, _browser_reader, ["instruments", "audio_effects"])
                _catalog_device_indexed = True
                _catalog_live_disconnected = False
            except _cat_index.DeviceLiveUnavailable as e:
                _catalog_live_disconnected = True
                errors.append("device_preset: %s" % e)
            except Exception as e:
                errors.append("device_preset: %s" % e)
        return _ok({"indexed": indexed, "errors": errors})
    except Exception as e:
        logger.error("reindex_catalog error: %s", e)
        return _err("reindex_catalog error: %s" % e)


def _user_serum_presets_dir():
    """Where serum_clone writes new presets. Prefer Serum's own User preset
    folder (~/Music/Serum/Presets/User on macOS, <Documents>\\Xfer\\Serum 2
    Presets\\Presets\\User on Windows) if the Serum tree exists; else the User
    Library."""
    dest = plat.serum_user_preset_dir(sys.platform, os.path.expanduser("~"),
                                      _documents_dir(), isdir=os.path.isdir)
    return dest or os.path.join(_user_library_dir(), "Serum Presets")


def _serum_clone_impl(base_preset, name, fx_edits=None):
    if not base_preset or not os.path.isfile(base_preset):
        raise FileNotFoundError("base preset not found: %r" % base_preset)
    out_dir = _user_serum_presets_dir()
    os.makedirs(out_dir, exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|]', "_", name or "Untitled").strip() or "Untitled"
    dest = os.path.join(out_dir, safe + ".SerumPreset")
    blob = open(base_preset, "rb").read()
    applied = 0
    if fx_edits:
        catalog = _sfxcat.load_catalog()
        state = _ssc.decode(blob)
        tree = state.tree
        for e in fx_edits:
            _sfx.set_fx_param(catalog, tree, e["rack"], e["slot"],
                              e["kparam"], e["native"])
            applied += 1
        blob = _ssc.encode(state, tree)
    with open(dest, "wb") as f:
        f.write(blob)
    return {"written": True, "path": dest, "base": base_preset,
            "fx_edits_applied": applied}


@mcp.tool()
def recommend_asset(ctx: Context, intent: str, domain: str) -> str:
    """Propose reuse-vs-create for a described asset. domain in
    serum|sample|groove|device_preset|wavetable|simpler. Returns {ok, data:
    {decision, top_matches, create_plan, reason}}. PROPOSE ONLY - never writes;
    pass create_plan to create_from_plan(confirm=True) to act on a 'create'."""
    try:
        conn = _catalog_conn()
        qd = domain if domain in ("serum", "sample", "groove",
                                  "device_preset") else "device_preset"
        if qd in ("serum", "sample", "groove"):
            _ensure_catalog_fresh(conn, [qd])
        if qd == "device_preset":
            _ensure_device_index(conn)
        result = _cat_decide.recommend(conn, intent, domain)
        if qd == "device_preset":
            result["live_disconnected"] = _catalog_live_disconnected
        return _ok(result)
    except Exception as e:
        logger.error("recommend_asset error: %s", e)
        return _err("recommend_asset error: %s" % e)


@mcp.tool()
def create_from_plan(ctx: Context, plan: dict, confirm: bool = False) -> str:
    """Execute a create_plan from recommend_asset. confirm=False (default)
    returns a dry-run describing what would be created and writes nothing.
    confirm=True invokes the matching creator (Wavetable, Simpler, or a Serum
    base-preset clone). Returns {ok, data:{...}}."""
    try:
        dispatch = _cat_decide.resolve_dispatch(plan)
    except ValueError as e:
        return _err("invalid plan: %s" % e)
    creator, kwargs = dispatch["creator"], dispatch["kwargs"]
    if not confirm:
        return _ok({"dry_run": True, "would_call": creator, "kwargs": kwargs})
    try:
        if creator == "create_wavetable_preset":
            return create_wavetable_preset(ctx, **kwargs)
        if creator == "create_simpler_instrument":
            return create_simpler_instrument(ctx, **kwargs)
        if creator == "serum_clone":
            res = _serum_clone_impl(kwargs.get("base_preset"),
                                    kwargs.get("name"),
                                    fx_edits=kwargs.get("fx_edits"))
            return _ok(res)
        return _err("unhandled creator: %s" % creator)
    except Exception as e:
        logger.error("create_from_plan error: %s", e)
        return _err("create_from_plan error: %s" % e)


def _resolve_instrument_env(prefer_native):
    """Resolve the live signals recommend_instrument scores against. Degrades to
    filesystem-only + intent-only scoring when Live is disconnected."""
    installed = instrument_select.serum_installed()
    try:
        conn = get_ableton_connection()
        info = conn.send_command("get_session_info")
        n = int(info.get("track_count", 0))
        tracks_devices = []
        for i in range(n):
            ti = conn.send_command("get_track_info", {"track_index": i})
            tracks_devices.append(ti.get("devices", []))
        env = instrument_select.summarize_environment(tracks_devices, installed,
                                                      prefer_native)
        env["live_connected"] = True
        return env
    except Exception as e:
        logger.warning("recommend_instrument env fallback: %s", e)
        return {"serum_installed": installed, "serum_instances": 0,
                "prefer_native": bool(prefer_native) if prefer_native is not None
                else False, "live_connected": False}


def _is_master_preset(row):
    """Best-effort filter: catalog rows that look like a master/Ozone preset."""
    hay = ("%s %s" % (row.get("name", ""), row.get("path", ""))).lower()
    return "ozone" in hay or "master" in hay


@mcp.tool()
def recommend_master(ctx: Context, intent: str, target: float = None,
                     true_peak: float = -1.0, prefer_reuse: bool = True) -> str:
    """Propose an Ozone 12 mastering chain from a free-text intent + loudness
    target. Picks a character bucket (transparent/warm/loud_club/punchy/bright)
    and resolves the LUFS target (explicit arg > platform keyword like
    spotify/apple/club > default -14). Returns a chain dict in set_ozone_state's
    shape. Best-effort: if a saved master/Ozone preset in the catalog matches,
    proposes reuse instead. PROPOSE ONLY - pass the returned chain to
    apply_master to write it. Returns {ok, data:{intent, parsed, target,
    true_peak, chain, decision, top_matches, reason, next}}."""
    try:
        result = _msel.recommend(intent, target=target, true_peak=true_peak)
        top_matches = []
        try:
            conn = _catalog_conn()
            _ensure_device_index(conn)
            rows = catalog_query.find_similar(conn, intent, "device_preset",
                                              limit=5)
            top_matches = [r for r in rows if _is_master_preset(r)]
            if (prefer_reuse and top_matches
                    and top_matches[0].get("score", 0) >= _msel.REUSE_MIN_SCORE):
                result["decision"] = "reuse"
                result["reason"] += " Catalog match available (reuse)."
        except Exception as e:
            logger.warning("recommend_master catalog fallback: %s", e)
        result["top_matches"] = top_matches
        result["next"] = "Pass chain to apply_master to write it."
        return _ok(result)
    except Exception as e:
        logger.error("recommend_master error: %s", e)
        return _err("recommend_master error: %s" % e)


@mcp.tool()
def apply_master(ctx: Context, chain: dict, track_index: int = 0,
                 device_index: int = 0, track_type: str = "master",
                 deploy_tap: bool = True) -> str:
    """Apply a mastering chain (from recommend_master) to an Ozone 12 instance in
    one shot, then set up the live trim loop. Writes the chain via set_ozone_state
    (one reload, un-clamped native values), exposes the Maximizer so the skill can
    nudge ceiling/gain without further reloads, and deploys a master tap so
    measure_loudness has post-fader audio. Errors clearly if the target device is
    not Ozone 12. Returns {ok, data:{applied, skipped, reloaded, exposed, tap,
    next}}. deploy_tap=False skips the tap (loop then runs un-metered)."""
    try:
        get_ableton_connection()  # fail fast if Live is unreachable
        # 1. Write the chain (this also detects non-Ozone via set_ozone_state).
        sos = json.loads(set_ozone_state(ctx, track_index, chain, device_index,
                                         track_type, reload=True))
        if not sos.get("ok"):
            return _err(sos.get("error", "apply_master: chain write failed"))
        wrote = sos["data"]
        # 2. Expose the Maximizer for the reload-free live trim loop.
        exp = json.loads(expose_ozone_modules(ctx, track_index, ["MAX"],
                                              device_index, track_type))
        exposed = exp.get("data") if exp.get("ok") else {"error": exp.get("error")}
        # 3. Deploy a master tap (non-fatal on failure).
        tap = {"status": "skipped"}
        if deploy_tap:
            td = json.loads(deploy_taps(ctx, track_indices=[-1]))
            d = td.get("data", {}) if td.get("ok") else {}
            if d.get("deployed"):
                status = "deployed"
            elif d.get("already_present"):
                status = "present"      # master already tapped - reuse it
            else:
                status = "failed"
            tap = {"status": status, "detail": td.get("data", td.get("error"))}
        return _ok({"applied": wrote.get("applied"), "skipped": wrote.get("skipped"),
                    "reloaded": wrote.get("reloaded"), "exposed": exposed,
                    "tap": tap,
                    "next": ("run the trim loop: play the densest section, "
                             "measure_loudness, nudge set_ozone_maximizer toward "
                             "target")})
    except Exception as e:
        logger.error("apply_master error: %s", e)
        return _err("apply_master error: %s" % e)


def _enumerate_master_devices(ctx, track_index, track_type, limit=64):
    """Walk device indices until one is absent; return [{index,name,is_on}].
    Out-of-range returns ok:false (normal end); a raised error propagates to
    the caller's handler rather than silently truncating the list."""
    devices = []
    for di in range(limit):
        raw = json.loads(get_device_info(ctx, track_index, di, track_type))
        if not raw.get("ok"):
            break
        d = raw["data"]
        devices.append({"index": di, "name": d.get("name"),
                        "is_on": d.get("is_on")})
    return devices


def _master_blob_ready(ctx, track_index, target_index, track_type,
                       attempts=5):
    """Save-with-retry, then probe get_ozone_state. Works around the racy
    empty-title / stale-.als-path window right after a structural change.
    Returns (ready: bool, last_error: str|None)."""
    last = None
    for _ in range(attempts):
        saved = json.loads(save_set(ctx, "")).get("data", {})
        if not saved.get("saved") or saved.get("untitled"):
            last = saved.get("error") or "save did not land (transient title)"
            time.sleep(0.6)
            continue
        probe = json.loads(get_ozone_state(ctx, track_index, target_index,
                                           track_type, None))
        if probe.get("ok"):
            return True, None
        last = probe.get("error")
        time.sleep(0.6)
    return False, last


@mcp.tool()
def ensure_ozone_master(ctx: Context, track_index: int = 0,
                        track_type: str = "master") -> str:
    """Prepare the master for mastering: guarantee exactly one enabled Ozone 12,
    with older Ozone versions (9/10/11) disabled (never deleted), and confirm the
    instance's state blob is authorable before returning. Reuses an existing
    Ozone 12 (re-enabling it if off; lowest index if several), else loads one onto
    the master (appends - existing master devices are untouched). Detection is
    exact-name so the single-module 'Ozone 12 <Module>' component plugins are
    ignored. The set must already be saved to a file (an untitled set errors).
    Hand data.device_index straight to apply_master. Returns {ok, data:{
    device_index, action: reused|reused_reenabled|loaded, disabled_indices,
    blob_ready}}."""
    try:
        get_ableton_connection()  # fail fast if Live is unreachable
        # Precondition: window is settled pre-change, so this read is reliable.
        pre = json.loads(save_set(ctx, "")).get("data", {})
        if pre.get("untitled"):
            return _err("Save the set to a file first (it is untitled), then retry.")
        before = _enumerate_master_devices(ctx, track_index, track_type)
        plan = master_ozone_utils.plan_master_ozone(before)
        for di in plan["disable_indices"]:
            set_device_on(ctx, track_index, di, False, track_type)
        if plan["load_required"]:
            loaded = json.loads(load_instrument_or_effect(
                ctx, track_index, master_ozone_utils.OZONE_12_URI, track_type))
            if not loaded.get("ok"):
                return _err("ensure_ozone_master: load failed: %s"
                            % loaded.get("error"))
            after = _enumerate_master_devices(ctx, track_index, track_type)
            target = master_ozone_utils.pick_loaded_target(before, after)
            if target is None:
                return _err("ensure_ozone_master: Ozone 12 did not appear after load.")
        else:
            target = plan["target_index"]
            if plan["action"] == "reused_reenabled":
                set_device_on(ctx, track_index, target, True, track_type)
        ready, err = _master_blob_ready(ctx, track_index, target, track_type)
        if not ready:
            return _err("ensure_ozone_master: master prepared (action=%s, "
                        "device_index=%s) but the Ozone blob was not authorable "
                        "after retries: %s" % (plan["action"], target, err))
        return _ok({"device_index": target, "action": plan["action"],
                    "disabled_indices": plan["disable_indices"],
                    "blob_ready": True})
    except Exception as e:
        logger.error("ensure_ozone_master error: %s", e)
        return _err("ensure_ozone_master error: %s" % e)


@mcp.tool()
def recommend_instrument(ctx: Context, intent: str,
                         prefer_native: bool = None) -> str:
    """Choose which instrument engine to reach for from a free-text intent
    (e.g. 'gritty evolving reese bass for dnb'). Ranks Serum vs native Wavetable,
    Operator, Analog, Simpler/Sampler, and Drum Rack against a capability matrix,
    biased toward native engines so Serum is used only when it earns it. Applies
    live signals when connected: Serum-installed (drops Serum if absent), Serum
    instance count (busy penalty), and portability (prefer_native). Set
    prefer_native=True to force native-only weighting; leave None to auto-detect
    (native-preferred only when the set has no 3rd-party plugin). PROPOSE ONLY -
    pass the returned top.domain to recommend_asset to pick reuse-vs-create.
    Returns {ok, data:{intent, parsed, ranked, top, reason, environment, next}}."""
    try:
        env = _resolve_instrument_env(prefer_native)
        result = instrument_select.recommend(intent, env)
        result["environment"] = env
        top = result.get("top")
        result["next"] = (("Pass domain=%r to recommend_asset to pick "
                           "reuse-vs-create." % top["domain"]) if top
                          else "No engine matched.")
        return _ok(result)
    except FileNotFoundError as e:
        return _err("instrument profiles missing: %s" % e)
    except Exception as e:
        logger.error("recommend_instrument error: %s", e)
        return _err("recommend_instrument error: %s" % e)


# Main execution
def main():
    """Run the MCP server"""
    mcp.run()

if __name__ == "__main__":
    main()
