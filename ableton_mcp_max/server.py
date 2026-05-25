# ableton_mcp_server.py
from mcp.server.fastmcp import FastMCP, Context
import socket
import json
import logging
from dataclasses import dataclass
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any, List, Union

from ableton_mcp_max.param_utils import resolve_parameter_index
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

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AbletonMCPServer")

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

    def send_command(self, command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Send a command to Ableton and return the response"""
        if not self.sock and not self.connect():
            raise ConnectionError("Not connected to Ableton")
        
        command = {
            "type": command_type,
            "params": params or {}
        }
        
        # Check if this is a state-modifying command
        is_modifying_command = command_type in [
            "create_midi_track", "create_audio_track", "set_track_name",
            "create_clip", "add_notes_to_clip", "set_clip_name",
            "set_tempo", "fire_clip", "stop_clip", "set_device_parameter",
            "start_playback", "stop_playback", "load_instrument_or_effect",
            "replace_clip_notes", "remove_clip_notes", "set_clip_property",
            "set_clip_loop", "quantize_clip", "duplicate_clip", "delete_clip",
            "modify_clip_notes",
            "delete_device", "set_device_on", "set_rack_macro",
            "set_chain_property",
            "fire_scene", "create_scene", "delete_scene", "duplicate_scene",
            "set_scene_name", "set_scene_property", "continue_playback",
            "set_metronome", "set_arrangement_record", "set_session_record",
            "set_punch", "set_song_position", "jump_by", "set_arrangement_loop",
            "jump_to_cue", "back_to_arrangement", "re_enable_automation"
        ]
        
        try:
            logger.info(f"Sending command: {command_type} with params: {params}")
            
            # Send the command
            self.sock.sendall(json.dumps(command).encode('utf-8'))
            logger.info(f"Command sent, waiting for response...")
            
            # For state-modifying commands, add a small delay to give Ableton time to process
            if is_modifying_command:
                import time
                time.sleep(0.1)  # 100ms delay
            
            # Set timeout based on command type
            timeout = 15.0 if is_modifying_command else 10.0
            self.sock.settimeout(timeout)
            
            # Receive the response
            response_data = self.receive_full_response(self.sock)
            logger.info(f"Received {len(response_data)} bytes of data")
            
            # Parse the response
            response = json.loads(response_data.decode('utf-8'))
            logger.info(f"Response parsed, status: {response.get('status', 'unknown')}")
            
            if response.get("status") == "error":
                logger.error(f"Ableton error: {response.get('message')}")
                raise Exception(response.get("message", "Unknown error from Ableton"))
            
            # For state-modifying commands, add another small delay after receiving response
            if is_modifying_command:
                import time
                time.sleep(0.1)  # 100ms delay
            
            return response.get("result", {})
        except socket.timeout:
            logger.error("Socket timeout while waiting for response from Ableton")
            self.sock = None
            raise Exception("Timeout waiting for Ableton response")
        except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
            logger.error(f"Socket connection error: {str(e)}")
            self.sock = None
            raise Exception(f"Connection to Ableton lost: {str(e)}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON response from Ableton: {str(e)}")
            if 'response_data' in locals() and response_data:
                logger.error(f"Raw response (first 200 bytes): {response_data[:200]}")
            self.sock = None
            raise Exception(f"Invalid response from Ableton: {str(e)}")
        except Exception as e:
            logger.error(f"Error communicating with Ableton: {str(e)}")
            self.sock = None
            raise Exception(f"Communication error with Ableton: {str(e)}")

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
    
    if _ableton_connection is not None:
        try:
            # Test the connection with a simple ping
            # We'll try to send an empty message, which should fail if the connection is dead
            # but won't affect Ableton if it's alive
            _ableton_connection.sock.settimeout(1.0)
            _ableton_connection.sock.sendall(b'')
            return _ableton_connection
        except Exception as e:
            logger.warning(f"Existing connection is no longer valid: {str(e)}")
            try:
                _ableton_connection.disconnect()
            except:
                pass
            _ableton_connection = None
    
    # Connection doesn't exist or is invalid, create a new one
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


# Core Tool endpoints

@mcp.tool()
def get_session_info(ctx: Context) -> str:
    """Get detailed information about the current Ableton session"""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_session_info")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting session info from Ableton: {str(e)}")
        return f"Error getting session info: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting track info from Ableton: {str(e)}")
        return f"Error getting track info: {str(e)}"

@mcp.tool()
def get_device_parameters(ctx: Context, track_index: int, device_index: int) -> str:
    """
    List all automatable parameters of a device on a track, with current
    value, min, max, whether it's quantized, and (for quantized params) the
    list of selectable value items.

    Parameters:
    - track_index: index of the track
    - device_index: index of the device on that track (0 = first device)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command(
            "get_device_parameters",
            {"track_index": track_index, "device_index": device_index},
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting device parameters: {str(e)}")
        return f"Error getting device parameters: {str(e)}"

@mcp.tool()
def set_device_parameter(
    ctx: Context,
    track_index: int,
    device_index: int,
    parameter: Union[int, str],
    value: float,
) -> str:
    """
    Set a single device/instrument parameter.

    Parameters:
    - track_index: index of the track
    - device_index: index of the device on that track
    - parameter: parameter index (int) OR parameter name (str, case-insensitive)
    - value: target value (clamped to the parameter's min/max). For quantized
      parameters, pass the integer index of the desired value item.
    """
    try:
        ableton = get_ableton_connection()
        # Fetch the parameter list to resolve name->index and validate.
        info = ableton.send_command(
            "get_device_parameters",
            {"track_index": track_index, "device_index": device_index},
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
            },
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting device parameter: {str(e)}")
        return f"Error setting device parameter: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting device info: {str(e)}")
        return f"Error getting device info: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error deleting device: {str(e)}")
        return f"Error deleting device: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting device on/off: {str(e)}")
        return f"Error setting device on/off: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting rack macros: {str(e)}")
        return f"Error getting rack macros: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting rack macro: {str(e)}")
        return f"Error setting rack macro: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting rack chains: {str(e)}")
        return f"Error getting rack chains: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting chain property: {str(e)}")
        return f"Error setting chain property: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting mixer state: {str(e)}")
        return f"Error getting mixer state: {str(e)}"

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
            return "Error: property 'send' requires send_index >= 0"
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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting mixer property: {str(e)}")
        return f"Error setting mixer property: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting routing: {str(e)}")
        return f"Error getting routing: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting routing: {str(e)}")
        return f"Error setting routing: {str(e)}"

@mcp.tool()
def create_midi_track(ctx: Context, index: int = -1) -> str:
    """
    Create a new MIDI track in the Ableton session.
    
    Parameters:
    - index: The index to insert the track at (-1 = end of list)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_midi_track", {"index": index})
        return f"Created new MIDI track: {result.get('name', 'unknown')}"
    except Exception as e:
        logger.error(f"Error creating MIDI track: {str(e)}")
        return f"Error creating MIDI track: {str(e)}"


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
        return f"Renamed track to: {result.get('name', name)}"
    except Exception as e:
        logger.error(f"Error setting track name: {str(e)}")
        return f"Error setting track name: {str(e)}"

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
        return f"Created new clip at track {track_index}, slot {clip_index} with length {length} beats"
    except Exception as e:
        logger.error(f"Error creating clip: {str(e)}")
        return f"Error creating clip: {str(e)}"

@mcp.tool()
def add_notes_to_clip(
    ctx: Context, 
    track_index: int, 
    clip_index: int, 
    notes: List[Dict[str, Union[int, float, bool]]]
) -> str:
    """
    Add MIDI notes to a clip (MIDI clips only). Uses Live 11's extended note
    API (no editor dialog).

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - notes: List of note dictionaries. Required-ish fields: pitch, start_time,
      duration, velocity, mute. Optional Live 11 fields (sensible defaults):
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
        return f"Added {len(notes)} notes to clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error adding notes to clip: {str(e)}")
        return f"Error adding notes to clip: {str(e)}"

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
        return f"Renamed clip at track {track_index}, slot {clip_index} to '{name}'"
    except Exception as e:
        logger.error(f"Error setting clip name: {str(e)}")
        return f"Error setting clip name: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting clip info: {str(e)}")
        return f"Error getting clip info: {str(e)}"

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
    Read MIDI notes from a clip (MIDI clips only). Uses Live 11's extended note
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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting clip notes: {str(e)}")
        return f"Error getting clip notes: {str(e)}"

@mcp.tool()
def replace_clip_notes(
    ctx: Context,
    track_index: int,
    clip_index: int,
    notes: List[Dict[str, Union[int, float, bool]]],
) -> str:
    """
    Replace ALL notes in a MIDI clip with the given notes (clears existing notes
    first, then adds these). MIDI clips only. Uses Live 11's extended note API.

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error replacing clip notes: {str(e)}")
        return f"Error replacing clip notes: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error removing clip notes: {str(e)}")
        return f"Error removing clip notes: {str(e)}"

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
                return "Error: every note must include a note_id (see get_clip_notes)"
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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error modifying clip notes: {str(e)}")
        return f"Error modifying clip notes: {str(e)}"

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
      pitch_coarse, pitch_fine (aliases accepted: loop, pitch, detune, warp, ...)
    - value: bools take 0/1/true/false; gain is 0.0-1.0 (clamped); pitch_coarse
      is -48..48 semitones, pitch_fine -50..50 cents (clamped); others are
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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting clip property: {str(e)}")
        return f"Error setting clip property: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting clip loop: {str(e)}")
        return f"Error setting clip loop: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error quantizing clip: {str(e)}")
        return f"Error quantizing clip: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error duplicating clip: {str(e)}")
        return f"Error duplicating clip: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error deleting clip: {str(e)}")
        return f"Error deleting clip: {str(e)}"

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
        return f"Set tempo to {tempo} BPM"
    except Exception as e:
        logger.error(f"Error setting tempo: {str(e)}")
        return f"Error setting tempo: {str(e)}"


@mcp.tool()
def load_instrument_or_effect(ctx: Context, track_index: int, uri: str) -> str:
    """
    Load an instrument or effect onto a track using its URI.
    
    Parameters:
    - track_index: The index of the track to load the instrument on
    - uri: The URI of the instrument or effect to load (e.g., 'query:Synths#Instrument%20Rack:Bass:FileId_5116')
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": uri
        })
        
        # Check if the instrument was loaded successfully
        if result.get("loaded", False):
            new_devices = result.get("new_devices", [])
            if new_devices:
                return f"Loaded instrument with URI '{uri}' on track {track_index}. New devices: {', '.join(new_devices)}"
            else:
                devices = result.get("devices_after", [])
                return f"Loaded instrument with URI '{uri}' on track {track_index}. Devices on track: {', '.join(devices)}"
        else:
            return f"Failed to load instrument with URI '{uri}'"
    except Exception as e:
        logger.error(f"Error loading instrument by URI: {str(e)}")
        return f"Error loading instrument by URI: {str(e)}"

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
        return f"Started playing clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error firing clip: {str(e)}")
        return f"Error firing clip: {str(e)}"

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
        return f"Stopped clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error stopping clip: {str(e)}")
        return f"Error stopping clip: {str(e)}"

@mcp.tool()
def start_playback(ctx: Context) -> str:
    """Start playing the Ableton session."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("start_playback")
        return "Started playback"
    except Exception as e:
        logger.error(f"Error starting playback: {str(e)}")
        return f"Error starting playback: {str(e)}"

@mcp.tool()
def stop_playback(ctx: Context) -> str:
    """Stop playing the Ableton session."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("stop_playback")
        return "Stopped playback"
    except Exception as e:
        logger.error(f"Error stopping playback: {str(e)}")
        return f"Error stopping playback: {str(e)}"

# === Scenes ===============================================================

@mcp.tool()
def get_scenes(ctx: Context) -> str:
    """List all scenes in the session (index, name, color, tempo, time signature,
    is_empty, is_triggered)."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_scenes")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting scenes: {str(e)}")
        return f"Error getting scenes: {str(e)}"

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
        return f"Fired scene {scene_index}"
    except Exception as e:
        logger.error(f"Error firing scene: {str(e)}")
        return f"Error firing scene: {str(e)}"

@mcp.tool()
def create_scene(ctx: Context, index: int = -1) -> str:
    """
    Create a new scene.

    Parameters:
    - index: Position to insert at; -1 (default) appends at the end
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_scene", {"index": index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error creating scene: {str(e)}")
        return f"Error creating scene: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error deleting scene: {str(e)}")
        return f"Error deleting scene: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error duplicating scene: {str(e)}")
        return f"Error duplicating scene: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting scene name: {str(e)}")
        return f"Error setting scene name: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting scene property: {str(e)}")
        return f"Error setting scene property: {str(e)}"

# === Transport ============================================================

@mcp.tool()
def get_transport(ctx: Context) -> str:
    """Get transport / arrangement state: is_playing, current_song_time, tempo,
    time signature, metronome, arrangement loop (on/start/length), record_mode,
    session_record, punch_in/out."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_transport")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting transport: {str(e)}")
        return f"Error getting transport: {str(e)}"

@mcp.tool()
def continue_playback(ctx: Context) -> str:
    """Resume playback from the current position (unlike start_playback, which
    restarts from the top)."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("continue_playback")
        return "Continued playback"
    except Exception as e:
        logger.error(f"Error continuing playback: {str(e)}")
        return f"Error continuing playback: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting metronome: {str(e)}")
        return f"Error setting metronome: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting arrangement record: {str(e)}")
        return f"Error setting arrangement record: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting session record: {str(e)}")
        return f"Error setting session record: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting punch: {str(e)}")
        return f"Error setting punch: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting song position: {str(e)}")
        return f"Error setting song position: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error jumping by beats: {str(e)}")
        return f"Error jumping by beats: {str(e)}"

# === Arrangement ==========================================================

@mcp.tool()
def get_cue_points(ctx: Context) -> str:
    """List arrangement cue points / locators (index, name, time)."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_cue_points")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting cue points: {str(e)}")
        return f"Error getting cue points: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting arrangement loop: {str(e)}")
        return f"Error setting arrangement loop: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error jumping to cue: {str(e)}")
        return f"Error jumping to cue: {str(e)}"

@mcp.tool()
def back_to_arrangement(ctx: Context) -> str:
    """Re-engage the arrangement timeline after launching session clips (clears
    the 'back to arrangement' override)."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("back_to_arrangement")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error returning to arrangement: {str(e)}")
        return f"Error returning to arrangement: {str(e)}"

@mcp.tool()
def re_enable_automation(ctx: Context) -> str:
    """Re-enable automation that was overridden by manual control changes."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("re_enable_automation")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error re-enabling automation: {str(e)}")
        return f"Error re-enabling automation: {str(e)}"

@mcp.tool()
def get_browser_tree(ctx: Context, category_type: str = "all") -> str:
    """
    Get a hierarchical tree of browser categories from Ableton.
    
    Parameters:
    - category_type: Type of categories to get ('all', 'instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects')
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_browser_tree", {
            "category_type": category_type
        })
        
        # Check if we got any categories
        if "available_categories" in result and len(result.get("categories", [])) == 0:
            available_cats = result.get("available_categories", [])
            return (f"No categories found for '{category_type}'. "
                   f"Available browser categories: {', '.join(available_cats)}")
        
        # Format the tree in a more readable way
        total_folders = result.get("total_folders", 0)
        formatted_output = f"Browser tree for '{category_type}' (showing {total_folders} folders):\n\n"
        
        def format_tree(item, indent=0):
            output = ""
            if item:
                prefix = "  " * indent
                name = item.get("name", "Unknown")
                path = item.get("path", "")
                has_more = item.get("has_more", False)
                
                # Add this item
                output += f"{prefix}• {name}"
                if path:
                    output += f" (path: {path})"
                if has_more:
                    output += " [...]"
                output += "\n"
                
                # Add children
                for child in item.get("children", []):
                    output += format_tree(child, indent + 1)
            return output
        
        # Format each category
        for category in result.get("categories", []):
            formatted_output += format_tree(category)
            formatted_output += "\n"
        
        return formatted_output
    except Exception as e:
        error_msg = str(e)
        if "Browser is not available" in error_msg:
            logger.error(f"Browser is not available in Ableton: {error_msg}")
            return f"Error: The Ableton browser is not available. Make sure Ableton Live is fully loaded and try again."
        elif "Could not access Live application" in error_msg:
            logger.error(f"Could not access Live application: {error_msg}")
            return f"Error: Could not access the Ableton Live application. Make sure Ableton Live is running and the Remote Script is loaded."
        else:
            logger.error(f"Error getting browser tree: {error_msg}")
            return f"Error getting browser tree: {error_msg}"

@mcp.tool()
def get_browser_items_at_path(ctx: Context, path: str) -> str:
    """
    Get browser items at a specific path in Ableton's browser.
    
    Parameters:
    - path: Path in the format "category/folder/subfolder"
            where category is one of the available browser categories in Ableton
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
            return (f"Error: {error}\n"
                   f"Available browser categories: {', '.join(available_cats)}")
        
        return json.dumps(result, indent=2)
    except Exception as e:
        error_msg = str(e)
        if "Browser is not available" in error_msg:
            logger.error(f"Browser is not available in Ableton: {error_msg}")
            return f"Error: The Ableton browser is not available. Make sure Ableton Live is fully loaded and try again."
        elif "Could not access Live application" in error_msg:
            logger.error(f"Could not access Live application: {error_msg}")
            return f"Error: Could not access the Ableton Live application. Make sure Ableton Live is running and the Remote Script is loaded."
        elif "Unknown or unavailable category" in error_msg:
            logger.error(f"Invalid browser category: {error_msg}")
            return f"Error: {error_msg}. Please check the available categories using get_browser_tree."
        elif "Path part" in error_msg and "not found" in error_msg:
            logger.error(f"Path not found: {error_msg}")
            return f"Error: {error_msg}. Please check the path and try again."
        else:
            logger.error(f"Error getting browser items at path: {error_msg}")
            return f"Error getting browser items at path: {error_msg}"

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
            return f"Failed to load drum rack with URI '{rack_uri}'"
        
        # Step 2: Get the drum kit items at the specified path
        kit_result = ableton.send_command("get_browser_items_at_path", {
            "path": kit_path
        })
        
        if "error" in kit_result:
            return f"Loaded drum rack but failed to find drum kit: {kit_result.get('error')}"
        
        # Step 3: Find a loadable drum kit
        kit_items = kit_result.get("items", [])
        loadable_kits = [item for item in kit_items if item.get("is_loadable", False)]
        
        if not loadable_kits:
            return f"Loaded drum rack but no loadable drum kits found at '{kit_path}'"
        
        # Step 4: Load the first loadable kit
        kit_uri = loadable_kits[0].get("uri")
        load_result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": kit_uri
        })
        
        return f"Loaded drum rack and kit '{loadable_kits[0].get('name')}' on track {track_index}"
    except Exception as e:
        logger.error(f"Error loading drum kit: {str(e)}")
        return f"Error loading drum kit: {str(e)}"

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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error reading automation: {str(e)}")
        return f"Error reading automation: {str(e)}"


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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting automation: {str(e)}")
        return f"Error setting automation: {str(e)}"


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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error clearing automation: {str(e)}")
        return f"Error clearing automation: {str(e)}"


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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error creating automation envelope: {str(e)}")
        return f"Error creating automation envelope: {str(e)}"


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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error clearing all automation: {str(e)}")
        return f"Error clearing all automation: {str(e)}"


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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error registering listener: {str(e)}")
        return f"Error registering listener: {str(e)}"


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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error polling changes: {str(e)}")
        return f"Error polling changes: {str(e)}"


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
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error unregistering listener: {str(e)}")
        return f"Error unregistering listener: {str(e)}"


@mcp.tool()
def list_listeners(ctx: Context) -> str:
    """
    List active change listeners with each one's target plus its buffer's
    pending and dropped event counts.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("list_listeners")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error listing listeners: {str(e)}")
        return f"Error listing listeners: {str(e)}"


# Main execution
def main():
    """Run the MCP server"""
    mcp.run()

if __name__ == "__main__":
    main()