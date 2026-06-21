# AbletonMCP/init.py
from __future__ import absolute_import, print_function, unicode_literals

from _Framework.ControlSurface import ControlSurface
import Live
import socket
import json
import threading
import time
import traceback
import collections

# Change queue import for Python 2
try:
    import Queue as queue  # Python 2
except ImportError:
    import queue  # Python 3

# Constants for socket communication
DEFAULT_PORT = 9877
HOST = "localhost"

# Max buffered change-events per listener (Phase 7). Oldest are evicted on
# overflow and counted in the listener's `dropped` total.
LISTENER_BUFFER_MAX = 512

def create_instance(c_instance):
    """Create and return the AbletonMCP script instance"""
    return AbletonMCP(c_instance)

class AbletonMCP(ControlSurface):
    """AbletonMCP Remote Script for Ableton Live"""
    
    def __init__(self, c_instance):
        """Initialize the control surface"""
        ControlSurface.__init__(self, c_instance)
        self.log_message("AbletonMCP Remote Script initializing...")
        
        # Socket server for communication
        self.server = None
        self.client_threads = []
        self.server_thread = None
        self.running = False
        
        # Cache the song reference for easier access
        self._song = self.song()

        # Phase 7: change-listener registry. Live's observer callbacks fire on
        # the main thread and append events here; poll_changes drains them.
        self._listeners = {}
        self._listener_lock = threading.Lock()
        self._listener_seq = 0          # monotonic event sequence
        self._listener_id_counter = 0   # monotonic listener id

        # Start the socket server
        self.start_server()
        
        self.log_message("AbletonMCP initialized")
        
        # Show a message in Ableton
        self.show_message("AbletonMCP: Listening for commands on port " + str(DEFAULT_PORT))
    
    def disconnect(self):
        """Called when Ableton closes or the control surface is removed"""
        self.log_message("AbletonMCP disconnecting...")
        self.running = False

        # Phase 7: detach any active change listeners so no callbacks dangle.
        try:
            self._unregister_listener(None)
        except Exception as e:
            self.log_message("Error detaching listeners on disconnect: " + str(e))

        # Stop the server
        if self.server:
            try:
                self.server.close()
            except:
                pass
        
        # Wait for the server thread to exit
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(1.0)
            
        # Clean up any client threads
        for client_thread in self.client_threads[:]:
            if client_thread.is_alive():
                # We don't join them as they might be stuck
                self.log_message("Client thread still alive during disconnect")
        
        ControlSurface.disconnect(self)
        self.log_message("AbletonMCP disconnected")
    
    def start_server(self):
        """Start the socket server in a separate thread"""
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.bind((HOST, DEFAULT_PORT))
            self.server.listen(5)  # Allow up to 5 pending connections
            
            self.running = True
            self.server_thread = threading.Thread(target=self._server_thread)
            self.server_thread.daemon = True
            self.server_thread.start()
            
            self.log_message("Server started on port " + str(DEFAULT_PORT))
        except Exception as e:
            self.log_message("Error starting server: " + str(e))
            self.show_message("AbletonMCP: Error starting server - " + str(e))
    
    def _server_thread(self):
        """Server thread implementation - handles client connections"""
        try:
            self.log_message("Server thread started")
            # Set a timeout to allow regular checking of running flag
            self.server.settimeout(1.0)
            
            while self.running:
                try:
                    # Accept connections with timeout
                    client, address = self.server.accept()
                    self.log_message("Connection accepted from " + str(address))
                    self.show_message("AbletonMCP: Client connected")
                    
                    # Handle client in a separate thread
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client,)
                    )
                    client_thread.daemon = True
                    client_thread.start()
                    
                    # Keep track of client threads
                    self.client_threads.append(client_thread)
                    
                    # Clean up finished client threads
                    self.client_threads = [t for t in self.client_threads if t.is_alive()]
                    
                except socket.timeout:
                    # No connection yet, just continue
                    continue
                except Exception as e:
                    if self.running:  # Only log if still running
                        self.log_message("Server accept error: " + str(e))
                    time.sleep(0.5)
            
            self.log_message("Server thread stopped")
        except Exception as e:
            self.log_message("Server thread error: " + str(e))
    
    def _handle_client(self, client):
        """Handle communication with a connected client"""
        self.log_message("Client handler started")
        client.settimeout(None)  # No timeout for client socket
        buffer = ''  # Changed from b'' to '' for Python 2
        
        try:
            while self.running:
                try:
                    # Receive data
                    data = client.recv(8192)
                    
                    if not data:
                        # Client disconnected
                        self.log_message("Client disconnected")
                        break
                    
                    # Accumulate data in buffer with explicit encoding/decoding
                    try:
                        # Python 3: data is bytes, decode to string
                        buffer += data.decode('utf-8')
                    except AttributeError:
                        # Python 2: data is already string
                        buffer += data
                    
                    try:
                        # Try to parse command from buffer
                        command = json.loads(buffer)  # Removed decode('utf-8')
                        buffer = ''  # Clear buffer after successful parse
                        
                        self.log_message("Received command: " + str(command.get("type", "unknown")))
                        
                        # Process the command and get response
                        response = self._process_command(command)
                        
                        # Send the response with explicit encoding
                        try:
                            # Python 3: encode string to bytes
                            client.sendall(json.dumps(response).encode('utf-8'))
                        except AttributeError:
                            # Python 2: string is already bytes
                            client.sendall(json.dumps(response))
                    except ValueError:
                        # Incomplete data, wait for more
                        continue
                        
                except Exception as e:
                    self.log_message("Error handling client data: " + str(e))
                    self.log_message(traceback.format_exc())
                    
                    # Send error response if possible
                    error_response = {
                        "status": "error",
                        "message": str(e)
                    }
                    try:
                        # Python 3: encode string to bytes
                        client.sendall(json.dumps(error_response).encode('utf-8'))
                    except AttributeError:
                        # Python 2: string is already bytes
                        client.sendall(json.dumps(error_response))
                    except:
                        # If we can't send the error, the connection is probably dead
                        break
                    
                    # For serious errors, break the loop
                    if not isinstance(e, ValueError):
                        break
        except Exception as e:
            self.log_message("Error in client handler: " + str(e))
        finally:
            try:
                client.close()
            except:
                pass
            self.log_message("Client handler stopped")
    
    def _dispatch_main_thread(self, command_type, params):
        """Dispatch one mutating command on Live's main thread and return
        its result. Shared by the single-command path and the batch executor
        so the two dispatch tables never drift."""
        result = None
        if command_type == "create_midi_track":
            index = params.get("index", -1)
            result = self._create_midi_track(index)
        elif command_type == "set_track_name":
            track_index = params.get("track_index", 0)
            name = params.get("name", "")
            result = self._set_track_name(track_index, name)
        elif command_type == "create_clip":
            track_index = params.get("track_index", 0)
            clip_index = params.get("clip_index", 0)
            length = params.get("length", 4.0)
            result = self._create_clip(track_index, clip_index, length)
        elif command_type == "add_notes_to_clip":
            track_index = params.get("track_index", 0)
            clip_index = params.get("clip_index", 0)
            notes = params.get("notes", [])
            result = self._add_notes_to_clip(track_index, clip_index, notes)
        elif command_type == "set_clip_name":
            track_index = params.get("track_index", 0)
            clip_index = params.get("clip_index", 0)
            name = params.get("name", "")
            result = self._set_clip_name(track_index, clip_index, name)
        elif command_type == "set_tempo":
            tempo = params.get("tempo", 120.0)
            result = self._set_tempo(tempo)
        elif command_type == "fire_clip":
            track_index = params.get("track_index", 0)
            clip_index = params.get("clip_index", 0)
            result = self._fire_clip(track_index, clip_index)
        elif command_type == "stop_clip":
            track_index = params.get("track_index", 0)
            clip_index = params.get("clip_index", 0)
            result = self._stop_clip(track_index, clip_index)
        elif command_type == "start_playback":
            result = self._start_playback()
        elif command_type == "stop_playback":
            result = self._stop_playback()
        elif command_type == "load_instrument_or_effect":
            track_index = params.get("track_index", 0)
            uri = params.get("uri", "")
            result = self._load_instrument_or_effect(track_index, uri)
        elif command_type == "load_browser_item":
            track_index = params.get("track_index", 0)
            item_uri = params.get("item_uri", "")
            track_type = params.get("track_type", "regular")
            result = self._load_browser_item(track_index, item_uri, track_type)
        elif command_type == "set_device_parameter":
            track_index = params.get("track_index", 0)
            device_index = params.get("device_index", 0)
            parameter_index = params.get("parameter_index", 0)
            value = params.get("value", 0.0)
            track_type = params.get("track_type", "regular")
            result = self._set_device_parameter(
                track_index, device_index, parameter_index, value, track_type)
        elif command_type == "set_mixer_property":
            track_index = params.get("track_index", 0)
            track_type = params.get("track_type", "regular")
            prop = params.get("property", "")
            value = params.get("value", 0.0)
            send_index = params.get("send_index", -1)
            result = self._set_mixer_property(
                track_index, track_type, prop, value, send_index)
        elif command_type == "set_routing":
            track_index = params.get("track_index", 0)
            track_type = params.get("track_type", "regular")
            prop = params.get("property", "")
            value = params.get("value", None)
            result = self._set_routing(
                track_index, track_type, prop, value)
        elif command_type == "replace_clip_notes":
            track_index = params.get("track_index", 0)
            clip_index = params.get("clip_index", 0)
            notes = params.get("notes", [])
            result = self._replace_clip_notes(
                track_index, clip_index, notes)
        elif command_type == "remove_clip_notes":
            track_index = params.get("track_index", 0)
            clip_index = params.get("clip_index", 0)
            from_time = params.get("from_time", 0.0)
            time_span = params.get("time_span", -1.0)
            from_pitch = params.get("from_pitch", 0)
            pitch_span = params.get("pitch_span", 128)
            result = self._remove_clip_notes(
                track_index, clip_index, from_time,
                time_span, from_pitch, pitch_span)
        elif command_type == "set_clip_property":
            track_index = params.get("track_index", 0)
            clip_index = params.get("clip_index", 0)
            prop = params.get("property", "")
            value = params.get("value", None)
            result = self._set_clip_property(
                track_index, clip_index, prop, value)
        elif command_type == "set_clip_loop":
            track_index = params.get("track_index", 0)
            clip_index = params.get("clip_index", 0)
            loop_start = params.get("loop_start", 0.0)
            loop_end = params.get("loop_end", 0.0)
            looping = params.get("looping", -1)
            result = self._set_clip_loop(
                track_index, clip_index, loop_start,
                loop_end, looping)
        elif command_type == "quantize_clip":
            track_index = params.get("track_index", 0)
            clip_index = params.get("clip_index", 0)
            grid = params.get("grid", 0)
            amount = params.get("amount", 1.0)
            result = self._quantize_clip(
                track_index, clip_index, grid, amount)
        elif command_type == "duplicate_clip":
            track_index = params.get("track_index", 0)
            clip_index = params.get("clip_index", 0)
            target_clip_index = params.get("target_clip_index", -1)
            result = self._duplicate_clip(
                track_index, clip_index, target_clip_index)
        elif command_type == "delete_clip":
            track_index = params.get("track_index", 0)
            clip_index = params.get("clip_index", 0)
            result = self._delete_clip(track_index, clip_index)
        elif command_type == "modify_clip_notes":
            track_index = params.get("track_index", 0)
            clip_index = params.get("clip_index", 0)
            notes = params.get("notes", [])
            result = self._modify_clip_notes(
                track_index, clip_index, notes)
        elif command_type == "delete_device":
            track_index = params.get("track_index", 0)
            device_index = params.get("device_index", 0)
            track_type = params.get("track_type", "regular")
            result = self._delete_device(
                track_index, device_index, track_type)
        elif command_type == "set_device_on":
            track_index = params.get("track_index", 0)
            device_index = params.get("device_index", 0)
            on = params.get("on", True)
            track_type = params.get("track_type", "regular")
            result = self._set_device_on(
                track_index, device_index, on, track_type)
        elif command_type == "set_rack_macro":
            track_index = params.get("track_index", 0)
            device_index = params.get("device_index", 0)
            parameter_index = params.get("parameter_index", 0)
            value = params.get("value", 0.0)
            track_type = params.get("track_type", "regular")
            result = self._set_rack_macro(
                track_index, device_index, parameter_index,
                value, track_type)
        elif command_type == "set_chain_property":
            track_index = params.get("track_index", 0)
            device_index = params.get("device_index", 0)
            chain_index = params.get("chain_index", 0)
            prop = params.get("property", "")
            value = params.get("value", None)
            track_type = params.get("track_type", "regular")
            result = self._set_chain_property(
                track_index, device_index, chain_index,
                prop, value, track_type)
        elif command_type == "fire_scene":
            scene_index = params.get("scene_index", 0)
            result = self._fire_scene(scene_index)
        elif command_type == "create_scene":
            index = params.get("index", -1)
            result = self._create_scene(index)
        elif command_type == "delete_scene":
            scene_index = params.get("scene_index", 0)
            result = self._delete_scene(scene_index)
        elif command_type == "duplicate_scene":
            scene_index = params.get("scene_index", 0)
            result = self._duplicate_scene(scene_index)
        elif command_type == "set_scene_name":
            scene_index = params.get("scene_index", 0)
            name = params.get("name", "")
            result = self._set_scene_name(scene_index, name)
        elif command_type == "set_scene_property":
            scene_index = params.get("scene_index", 0)
            prop = params.get("property", "")
            value = params.get("value", None)
            result = self._set_scene_property(
                scene_index, prop, value)
        elif command_type == "continue_playback":
            result = self._continue_playback()
        elif command_type == "set_metronome":
            on = params.get("on", True)
            result = self._set_metronome(on)
        elif command_type == "set_arrangement_record":
            on = params.get("on", True)
            result = self._set_arrangement_record(on)
        elif command_type == "set_session_record":
            on = params.get("on", True)
            result = self._set_session_record(on)
        elif command_type == "set_punch":
            punch_in = params.get("punch_in", None)
            punch_out = params.get("punch_out", None)
            result = self._set_punch(punch_in, punch_out)
        elif command_type == "set_song_position":
            time_beats = params.get("time_beats", 0.0)
            result = self._set_song_position(time_beats)
        elif command_type == "jump_by":
            beats = params.get("beats", 0.0)
            result = self._jump_by(beats)
        elif command_type == "set_arrangement_loop":
            enabled = params.get("enabled", None)
            start = params.get("start", None)
            length = params.get("length", None)
            result = self._set_arrangement_loop(
                enabled, start, length)
        elif command_type == "jump_to_cue":
            direction = params.get("direction", "next")
            result = self._jump_to_cue(direction)
        elif command_type == "back_to_arrangement":
            result = self._back_to_arrangement()
        elif command_type == "re_enable_automation":
            result = self._re_enable_automation()
        elif command_type == "set_automation":
            result = self._set_automation(
                params.get("track_index", 0),
                params.get("clip_index", 0),
                params.get("clip_location", "session"),
                params.get("target_type", "device"),
                params.get("device_index", 0),
                params.get("parameter_index", 0),
                params.get("mixer_property", ""),
                params.get("send_index", -1),
                params.get("breakpoints", []))
        elif command_type == "clear_automation":
            result = self._clear_automation(
                params.get("track_index", 0),
                params.get("clip_index", 0),
                params.get("clip_location", "session"),
                params.get("target_type", "device"),
                params.get("device_index", 0),
                params.get("parameter_index", 0),
                params.get("mixer_property", ""),
                params.get("send_index", -1),
                params.get("from_time", None),
                params.get("time_span", None))
        elif command_type == "create_automation_envelope":
            result = self._create_automation_envelope(
                params.get("track_index", 0),
                params.get("clip_index", 0),
                params.get("clip_location", "session"),
                params.get("target_type", "device"),
                params.get("device_index", 0),
                params.get("parameter_index", 0),
                params.get("mixer_property", ""),
                params.get("send_index", -1))
        elif command_type == "clear_all_automation":
            result = self._clear_all_automation(
                params.get("track_index", 0),
                params.get("clip_index", 0),
                params.get("clip_location", "session"))
        elif command_type == "register_listener":
            result = self._register_listener(
                params.get("descriptor", {}))
        elif command_type == "unregister_listener":
            result = self._unregister_listener(
                params.get("listener_id", None))
        elif command_type == "create_cue_at_playhead":
            result = self._create_cue_at_playhead()
        elif command_type == "delete_cue_at_playhead":
            result = self._delete_cue_at_playhead()
        elif command_type == "duplicate_clip_to_arrangement":
            track_index = params.get("track_index", 0)
            source_slot_index = params.get("source_slot_index", 0)
            destination_time = params.get("destination_time", 0.0)
            result = self._duplicate_clip_to_arrangement(
                track_index, source_slot_index, destination_time)
        elif command_type == "delete_arrangement_clip":
            track_index = params.get("track_index", 0)
            clip_index = params.get("clip_index", 0)
            result = self._delete_arrangement_clip(
                track_index, clip_index)
        elif command_type == "create_audio_track":
            index = params.get("index", -1)
            result = self._create_audio_track(index)
        elif command_type == "create_return_track":
            result = self._create_return_track()
        elif command_type == "delete_track":
            index = params.get("index", 0)
            result = self._delete_track(index)
        elif command_type == "delete_return_track":
            index = params.get("index", 0)
            result = self._delete_return_track(index)
        elif command_type == "duplicate_track":
            index = params.get("index", 0)
            result = self._duplicate_track(index)
        elif command_type == "undo":
            result = self._undo()
        elif command_type == "redo":
            result = self._redo()
        elif command_type == "set_groove_amount":
            result = self._set_groove_amount(params.get("value", 0.0))
        elif command_type == "assign_groove_to_clip":
            result = self._assign_groove_to_clip(params)
        elif command_type == "set_swing_amount":
            result = self._set_swing_amount(params.get("value", 0.0))
        elif command_type == "set_clip_trigger_quantization":
            result = self._set_clip_trigger_quantization(
                params.get("value", 0))
        elif command_type == "set_midi_recording_quantization":
            result = self._set_midi_recording_quantization(
                params.get("value", 0))
        elif command_type == "set_nudge":
            result = self._set_nudge(
                params.get("direction", "up"),
                params.get("active", False))
        elif command_type == "set_selected_track":
            result = self._set_selected_track(
                params.get("track_index", 0),
                params.get("track_type", "regular"))
        elif command_type == "set_selected_scene":
            result = self._set_selected_scene(
                params.get("scene_index", 0))
        elif command_type == "set_detail_clip":
            result = self._set_detail_clip(
                params.get("track_index", 0),
                params.get("clip_slot_index", 0))
        elif command_type == "set_highlighted_clip_slot":
            result = self._set_highlighted_clip_slot(
                params.get("track_index", 0),
                params.get("scene_index", 0))
        elif command_type == "set_track_fold":
            result = self._set_track_fold(
                params.get("track_index", 0),
                params.get("folded", False))
        elif command_type == "capture_midi":
            result = self._capture_midi(
                params.get("destination", "auto"))
        elif command_type == "capture_and_insert_scene":
            result = self._capture_and_insert_scene(
                params.get("mode", "all"))
        elif command_type == "trigger_session_record":
            result = self._trigger_session_record(
                params.get("record_length", None))
        elif command_type == "stop_all_clips":
            result = self._stop_all_clips(
                params.get("track_index", None),
                params.get("quantized", True))
        elif command_type == "tap_tempo":
            result = self._tap_tempo()
        elif command_type == "select_drum_pad":
            result = self._select_drum_pad(
                params.get("track_index", 0),
                params.get("pad_note", 36))
        else:
            raise Exception("Unknown command type: " + command_type)
        return result

    def _process_command(self, command):
        """Process a command from the client and return a response"""
        command_type = command.get("type", "")
        params = command.get("params", {})
        
        # Initialize response
        response = {
            "status": "success",
            "result": {}
        }
        
        try:
            # Route the command to the appropriate handler
            if command_type == "get_session_info":
                response["result"] = self._get_session_info()
            elif command_type == "get_track_info":
                track_index = params.get("track_index", 0)
                response["result"] = self._get_track_info(track_index)
            elif command_type == "get_analysis_snapshot":
                response["result"] = self._get_analysis_snapshot()
            elif command_type == "get_output_meters":
                response["result"] = self._get_output_meters()
            elif command_type == "get_application_version":
                response["result"] = self._get_application_version()
            elif command_type == "get_song_scale":
                response["result"] = self._get_song_scale()
            elif command_type == "batch":
                members = params.get("commands", [])
                stop_on_error = params.get("stop_on_error", True)
                response_queue = queue.Queue()
                def batch_task():
                    results = []
                    failed_index = -1
                    for i in range(len(members)):
                        member = members[i]
                        m_type = member.get("type", "")
                        m_params = member.get("params", {})
                        try:
                            r = self._dispatch_main_thread(m_type, m_params)
                            results.append({"status": "success", "result": r})
                        except Exception as e:
                            self.log_message("Error in batch member %d (%s): %s" % (i, m_type, str(e)))
                            self.log_message(traceback.format_exc())
                            results.append({"status": "error", "message": str(e)})
                            failed_index = i
                            if stop_on_error:
                                break
                    response_queue.put({"results": results, "failed_index": failed_index})
                try:
                    self.schedule_message(0, batch_task)
                except AssertionError:
                    batch_task()
                try:
                    batch_timeout = 10.0 + 2.0 * len(members)
                    task_response = response_queue.get(timeout=batch_timeout)
                    results = task_response.get("results", [])
                    completed = len([r for r in results if r.get("status") == "success"])
                    response["result"] = {
                        "count": len(members),
                        "completed": completed,
                        "failed_index": task_response.get("failed_index", -1),
                        "results": results,
                    }
                except queue.Empty:
                    response["status"] = "error"
                    response["message"] = "Timeout waiting for batch to complete"
            # Commands that modify Live's state should be scheduled on the main thread
            elif command_type in ["create_midi_track", "set_track_name",
                                 "create_clip", "add_notes_to_clip", "set_clip_name",
                                 "set_tempo", "fire_clip", "stop_clip",
                                 "start_playback", "stop_playback", "load_browser_item",
                                 "set_device_parameter", "set_mixer_property",
                                 "set_routing", "replace_clip_notes",
                                 "remove_clip_notes", "set_clip_property",
                                 "set_clip_loop", "quantize_clip",
                                 "duplicate_clip", "delete_clip",
                                 "modify_clip_notes",
                                 "delete_device", "set_device_on",
                                 "set_rack_macro", "set_chain_property",
                                 "fire_scene", "create_scene", "delete_scene",
                                 "duplicate_scene", "set_scene_name",
                                 "set_scene_property", "continue_playback",
                                 "set_metronome", "set_arrangement_record",
                                 "set_session_record", "set_punch",
                                 "set_song_position", "jump_by",
                                 "set_arrangement_loop", "jump_to_cue",
                                 "back_to_arrangement", "re_enable_automation",
                                 "set_automation", "clear_automation",
                                 "create_automation_envelope",
                                 "clear_all_automation",
                                 "register_listener", "unregister_listener",
                                 "create_cue_at_playhead",
                                 "delete_cue_at_playhead",
                                 "duplicate_clip_to_arrangement",
                                 "delete_arrangement_clip",
                                 "create_audio_track", "create_return_track",
                                 "delete_track", "delete_return_track",
                                 "duplicate_track", "undo", "redo",
                                 "set_groove_amount", "set_swing_amount",
                                 "set_clip_trigger_quantization",
                                 "set_midi_recording_quantization", "set_nudge",
                                 "set_selected_track", "set_selected_scene",
                                 "set_detail_clip", "set_highlighted_clip_slot",
                                 "set_track_fold",
                                 "capture_midi", "capture_and_insert_scene",
                                 "trigger_session_record", "stop_all_clips",
                                 "tap_tempo", "select_drum_pad",
                                 "assign_groove_to_clip"]:
                # Use a thread-safe approach with a response queue
                response_queue = queue.Queue()
                
                # Define a function to execute on the main thread
                def main_thread_task():
                    try:
                        result = self._dispatch_main_thread(command_type, params)
                        response_queue.put({"status": "success", "result": result})
                    except Exception as e:
                        self.log_message("Error in main thread task: " + str(e))
                        self.log_message(traceback.format_exc())
                        response_queue.put({"status": "error", "message": str(e)})
                
                # Schedule the task to run on the main thread
                try:
                    self.schedule_message(0, main_thread_task)
                except AssertionError:
                    # If we're already on the main thread, execute directly
                    main_thread_task()
                
                # Wait for the response with a timeout
                try:
                    task_response = response_queue.get(timeout=10.0)
                    if task_response.get("status") == "error":
                        response["status"] = "error"
                        response["message"] = task_response.get("message", "Unknown error")
                    else:
                        response["result"] = task_response.get("result", {})
                except queue.Empty:
                    response["status"] = "error"
                    response["message"] = "Timeout waiting for operation to complete"
            elif command_type == "get_browser_item":
                uri = params.get("uri", None)
                path = params.get("path", None)
                response["result"] = self._get_browser_item(uri, path)
            elif command_type == "get_browser_categories":
                category_type = params.get("category_type", "all")
                response["result"] = self._get_browser_categories(category_type)
            elif command_type == "get_browser_items":
                path = params.get("path", "")
                item_type = params.get("item_type", "all")
                response["result"] = self._get_browser_items(path, item_type)
            # Add the new browser commands
            elif command_type == "get_browser_tree":
                category_type = params.get("category_type", "all")
                response["result"] = self.get_browser_tree(category_type)
            elif command_type == "get_browser_items_at_path":
                path = params.get("path", "")
                response["result"] = self.get_browser_items_at_path(path)
            elif command_type == "get_browser_presets":
                path = params.get("path", "")
                max_depth = params.get("max_depth", 6)
                response["result"] = self.get_browser_presets(path, max_depth)
            elif command_type == "find_sample_uri":
                name = params.get("name", "")
                category = params.get("category", "samples")
                response["result"] = self.find_sample_uri(name, category)
            elif command_type == "get_device_parameters":
                track_index = params.get("track_index", 0)
                device_index = params.get("device_index", 0)
                track_type = params.get("track_type", "regular")
                response["result"] = self._get_device_parameters(
                    track_index, device_index, track_type)
            elif command_type == "get_device_info":
                track_index = params.get("track_index", 0)
                device_index = params.get("device_index", 0)
                track_type = params.get("track_type", "regular")
                response["result"] = self._get_device_info(
                    track_index, device_index, track_type)
            elif command_type == "get_rack_macros":
                track_index = params.get("track_index", 0)
                device_index = params.get("device_index", 0)
                track_type = params.get("track_type", "regular")
                response["result"] = self._get_rack_macros(
                    track_index, device_index, track_type)
            elif command_type == "get_rack_chains":
                track_index = params.get("track_index", 0)
                device_index = params.get("device_index", 0)
                track_type = params.get("track_type", "regular")
                response["result"] = self._get_rack_chains(
                    track_index, device_index, track_type)
            elif command_type == "get_mixer":
                track_index = params.get("track_index", 0)
                track_type = params.get("track_type", "regular")
                response["result"] = self._get_mixer(track_index, track_type)
            elif command_type == "get_routing":
                track_index = params.get("track_index", 0)
                track_type = params.get("track_type", "regular")
                response["result"] = self._get_routing(track_index, track_type)
            elif command_type == "get_clip_info":
                track_index = params.get("track_index", 0)
                clip_index = params.get("clip_index", 0)
                response["result"] = self._get_clip_info(track_index, clip_index)
            elif command_type == "get_clip_notes":
                track_index = params.get("track_index", 0)
                clip_index = params.get("clip_index", 0)
                from_time = params.get("from_time", 0.0)
                time_span = params.get("time_span", -1.0)
                from_pitch = params.get("from_pitch", 0)
                pitch_span = params.get("pitch_span", 128)
                response["result"] = self._get_clip_notes(
                    track_index, clip_index, from_time, time_span,
                    from_pitch, pitch_span)
            elif command_type == "get_scenes":
                response["result"] = self._get_scenes()
            elif command_type == "get_transport":
                response["result"] = self._get_transport()
            elif command_type == "get_view_selection":
                response["result"] = self._get_view_selection()
            elif command_type == "get_cue_points":
                response["result"] = self._get_cue_points()
            elif command_type == "get_groove_pool":
                response["result"] = self._get_groove_pool(params)
            elif command_type == "get_arrangement_clips":
                response["result"] = self._get_arrangement_clips(
                    params.get("track_index", 0))
            elif command_type == "get_automation":
                response["result"] = self._get_automation(
                    params.get("track_index", 0),
                    params.get("clip_index", 0),
                    params.get("clip_location", "session"),
                    params.get("target_type", "device"),
                    params.get("device_index", 0),
                    params.get("parameter_index", 0),
                    params.get("mixer_property", ""),
                    params.get("send_index", -1),
                    params.get("from_time", 0.0),
                    params.get("time_span", -1.0),
                    params.get("resolution", 16),
                )
            elif command_type == "poll_changes":
                response["result"] = self._poll_changes(
                    params.get("listener_id", None),
                    params.get("max_events", None))
            elif command_type == "list_listeners":
                response["result"] = self._list_listeners()
            else:
                response["status"] = "error"
                response["message"] = "Unknown command: " + command_type
        except Exception as e:
            self.log_message("Error processing command: " + str(e))
            self.log_message(traceback.format_exc())
            response["status"] = "error"
            response["message"] = str(e)
        
        return response
    
    # Command implementations

    def _get_application_version(self):
        """Report the running Live version (read-only). Lets the host pick
        factory assets matching the Live the user is actually running."""
        app = self.application()
        return {
            "major": app.get_major_version(),
            "minor": app.get_minor_version(),
            "bugfix": app.get_bugfix_version(),
        }

    def _get_song_scale(self):
        """Report the set's current key/scale for control surfaces (read-only).
        scale_intervals is a list of semitone offsets from the root (e.g. Major
        -> [0,2,4,5,7,9,11]). Guarded: older Live or missing endpoints degrade to
        defaults rather than raising."""
        song = self._song
        result = {"scale_name": None, "root_note": 0, "scale_intervals": []}
        try:
            result["scale_name"] = song.scale_name
        except Exception:
            pass
        try:
            result["root_note"] = int(song.root_note)
        except Exception:
            pass
        try:
            result["scale_intervals"] = [int(i) for i in song.scale_intervals]
        except Exception:
            pass
        return result

    def _get_session_info(self):
        """Get information about the current session"""
        try:
            result = {
                "tempo": self._song.tempo,
                "signature_numerator": self._song.signature_numerator,
                "signature_denominator": self._song.signature_denominator,
                "track_count": len(self._song.tracks),
                "return_track_count": len(self._song.return_tracks),
                "master_track": {
                    "name": "Master",
                    "volume": self._song.master_track.mixer_device.volume.value,
                    "panning": self._song.master_track.mixer_device.panning.value
                }
            }
            return result
        except Exception as e:
            self.log_message("Error getting session info: " + str(e))
            raise
    
    def _get_track_info(self, track_index):
        """Get information about a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            # Get clip slots
            clip_slots = []
            for slot_index, slot in enumerate(track.clip_slots):
                clip_info = None
                if slot.has_clip:
                    clip = slot.clip
                    clip_info = {
                        "name": clip.name,
                        "length": clip.length,
                        "is_playing": clip.is_playing,
                        "is_recording": clip.is_recording
                    }
                
                clip_slots.append({
                    "index": slot_index,
                    "has_clip": slot.has_clip,
                    "clip": clip_info
                })
            
            # Get devices
            devices = []
            for device_index, device in enumerate(track.devices):
                devices.append({
                    "index": device_index,
                    "name": device.name,
                    "class_name": device.class_name,
                    "type": self._get_device_type(device)
                })
            
            result = {
                "index": track_index,
                "name": track.name,
                "is_audio_track": track.has_audio_input,
                "is_midi_track": track.has_midi_input,
                "mute": track.mute,
                "solo": track.solo,
                "volume": track.mixer_device.volume.value,
                "panning": track.mixer_device.panning.value,
                "clip_slots": clip_slots,
                "devices": devices
            }
            # arm is regular-track-only: group tracks (like return/master) raise
            # "Master and Return Tracks have no 'Arm' state!" — read defensively.
            try:
                result["arm"] = track.arm
            except Exception:
                pass
            # Phase 10: group-track folding state (probed defensively).
            for attr in ("is_foldable", "is_grouped", "fold_state"):
                try:
                    result[attr] = getattr(track, attr)
                except Exception:
                    pass
            return result
        except Exception as e:
            self.log_message("Error getting track info: " + str(e))
            raise

    def _device_summary(self, device):
        try:
            idx = list(device.canonical_parent.devices).index(device)
        except Exception:
            idx = None
        try:
            is_instr = device.type == Live.Device.DeviceType.instrument
        except Exception:
            is_instr = False
        info = {
            "index": idx,
            "name": device.name,
            "class_name": device.class_name,
            "on": True,
            "is_instrument": is_instr,
        }
        try:
            info["on"] = bool(device.parameters[0].value) if device.parameters else True
        except Exception:
            pass
        return info

    def _clip_summary(self, track):
        count = named = warped = empty = 0
        try:
            for slot in track.clip_slots:
                if slot.has_clip:
                    count += 1
                    clip = slot.clip
                    if clip.name:
                        named += 1
                    try:
                        if clip.warping:
                            warped += 1
                    except Exception:
                        pass
                else:
                    empty += 1
        except Exception:
            pass
        return {"count": count, "named": named, "warped": warped, "empty_slots": empty}

    def _track_summary(self, track, track_type):
        devices = []
        try:
            for d in track.devices:
                devices.append(self._device_summary(d))
        except Exception:
            pass
        has_instrument = any(d.get("is_instrument") for d in devices)
        info = {
            "name": track.name,
            "type": track_type,
            "volume": track.mixer_device.volume.value,
            "panning": track.mixer_device.panning.value,
            "mute": track.mute,
            "solo": track.solo,
            "has_instrument": has_instrument,
            "devices": devices,
            "clips": self._clip_summary(track),
        }
        try:
            info["sends"] = [s.value for s in track.mixer_device.sends]
        except Exception:
            info["sends"] = []
        # arm is regular-track-only; group/return/master raise.
        try:
            info["arm"] = track.arm
        except Exception:
            info["arm"] = False
        for attr in ("is_grouped",):
            try:
                info[attr] = getattr(track, attr)
            except Exception:
                pass
        try:
            info["routing"] = {
                "audio_to": track.output_routing_type.display_name,
                "audio_from": track.input_routing_type.display_name,
            }
        except Exception:
            info["routing"] = {}
        return info

    def _track_type(self, track):
        try:
            if track.is_foldable:
                return "group"
        except Exception:
            pass
        if track.has_midi_input:
            return "midi"
        return "audio"

    def _get_analysis_snapshot(self):
        """One-shot read of the whole set for analysis. Reads only -- no mutation."""
        try:
            song = self._song
            tracks = []
            for i, t in enumerate(song.tracks):
                info = self._track_summary(t, self._track_type(t))
                info["index"] = i
                tracks.append(info)
            returns = []
            for i, t in enumerate(song.return_tracks):
                info = self._track_summary(t, "return")
                info["index"] = i
                returns.append(info)
            master = song.master_track
            master_devices = []
            try:
                for d in master.devices:
                    master_devices.append(self._device_summary(d))
            except Exception:
                pass
            return {
                "transport": {
                    "tempo": song.tempo,
                    "is_playing": song.is_playing,
                    "signature_numerator": song.signature_numerator,
                    "signature_denominator": song.signature_denominator,
                },
                "tracks": tracks,
                "returns": returns,
                "master": {
                    "name": "Master",
                    "volume": master.mixer_device.volume.value,
                    "panning": master.mixer_device.panning.value,
                    "devices": master_devices,
                },
            }
        except Exception as e:
            self.log_message("Error building analysis snapshot: " + str(e))
            raise

    def _meter_peak(self, track):
        """Instantaneous output-meter peak for a track: max(L, R) in [0..1].

        Live's output meters are post-fader/post-pan and only meaningful while
        the transport plays; the server polls this repeatedly and holds the max
        (peak-hold) over a window. Returns 0.0 if the track exposes no meter."""
        try:
            return max(track.output_meter_left, track.output_meter_right)
        except Exception:
            return 0.0

    def _get_output_meters(self):
        """One-shot read of every track/return/master output-meter peak.

        Returns {tracks:[{index, name, peak}], returns:[...], master:{peak}}
        where peak is the instantaneous linear max(L,R). A read-only snapshot;
        the server drives the peak-hold loop during a playback pass."""
        song = self._song
        tracks = [{"index": i, "name": t.name, "peak": self._meter_peak(t)}
                  for i, t in enumerate(song.tracks)]
        returns = [{"index": i, "name": t.name, "peak": self._meter_peak(t)}
                   for i, t in enumerate(song.return_tracks)]
        master = {"peak": self._meter_peak(song.master_track)}
        return {"tracks": tracks, "returns": returns, "master": master}

    def _resolve_track(self, track_index, track_type):
        """Return the Live track object for a (track_index, track_type)."""
        if track_type == "master":
            return self._song.master_track
        if track_type == "return":
            tracks = self._song.return_tracks
        elif track_type == "regular":
            tracks = self._song.tracks
        else:
            raise ValueError("Unknown track_type: " + str(track_type))
        if track_index < 0 or track_index >= len(tracks):
            raise IndexError("Track index out of range for " + track_type)
        return tracks[track_index]

    def _param_dict(self, p):
        return {"value": p.value, "min": p.min, "max": p.max}

    def _get_mixer(self, track_index, track_type):
        """Read mixer state for a regular/return/master track."""
        track = self._resolve_track(track_index, track_type)
        md = track.mixer_device
        result = {
            "track_type": track_type,
            "track_index": track_index,
            "name": track.name,
            "volume": self._param_dict(md.volume),
            "panning": self._param_dict(md.panning),
        }
        # mute/solo: regular + return; arm: regular only; none on master.
        if track_type in ("regular", "return"):
            result["mute"] = track.mute
            result["solo"] = track.solo
            result["crossfade_assign"] = md.crossfade_assign
        if track_type == "regular":
            result["arm"] = track.arm
        # sends: regular + return, parallel to return_tracks.
        if track_type in ("regular", "return"):
            sends = []
            for i, send in enumerate(md.sends):
                if i < len(self._song.return_tracks):
                    return_name = self._song.return_tracks[i].name
                else:
                    return_name = ""
                d = self._param_dict(send)
                d["index"] = i
                d["return_name"] = return_name
                sends.append(d)
            result["sends"] = sends
        return result

    def _clamp_param(self, param, value):
        v = float(value)
        if v < param.min:
            v = param.min
        if v > param.max:
            v = param.max
        param.value = v
        return param.value

    def _set_mixer_property(self, track_index, track_type, prop, value, send_index):
        """Set one mixer property. `prop` is a canonical name (server
        normalizes/validates via mixer_utils before sending)."""
        track = self._resolve_track(track_index, track_type)
        md = track.mixer_device
        out = {"track_type": track_type, "track_index": track_index, "property": prop}

        if prop == "volume":
            out["value"] = self._clamp_param(md.volume, value)
        elif prop == "pan":
            out["value"] = self._clamp_param(md.panning, value)
        elif prop == "send":
            if send_index < 0 or send_index >= len(md.sends):
                raise IndexError("send_index out of range")
            out["value"] = self._clamp_param(md.sends[send_index], value)
            out["send_index"] = send_index
        elif prop == "mute":
            track.mute = bool(value)
            out["value"] = track.mute
        elif prop == "solo":
            track.solo = bool(value)
            out["value"] = track.solo
        elif prop == "arm":
            track.arm = bool(value)
            out["value"] = track.arm
        elif prop == "crossfade_assign":
            md.crossfade_assign = int(value)
            out["value"] = md.crossfade_assign
        else:
            raise ValueError("Unsupported mixer property: " + str(prop))
        return out

    def _routing_endpoint(self, track, current_attr, available_attr):
        """Return {current, available:[display_name,...]} for a routing endpoint,
        or None if the track lacks it. Uses try/except (not hasattr) because
        Live raises RuntimeError -- not AttributeError -- for unsupported
        endpoints, which hasattr would propagate rather than swallow."""
        try:
            current = getattr(track, current_attr)
            current_name = current.display_name if current is not None else None
            available = [c.display_name for c in getattr(track, available_attr)]
            return {"current": current_name, "available": available}
        except Exception:
            return None

    def _get_routing(self, track_index, track_type):
        """Read input/output routing + monitoring for a track."""
        track = self._resolve_track(track_index, track_type)
        result = {"track_type": track_type, "track_index": track_index, "name": track.name}
        it = self._routing_endpoint(track, "input_routing_type", "available_input_routing_types")
        ic = self._routing_endpoint(track, "input_routing_channel", "available_input_routing_channels")
        ot = self._routing_endpoint(track, "output_routing_type", "available_output_routing_types")
        oc = self._routing_endpoint(track, "output_routing_channel", "available_output_routing_channels")
        if it is not None:
            result["input_type"] = it
        if ic is not None:
            result["input_channel"] = ic
        if ot is not None:
            result["output_type"] = ot
        if oc is not None:
            result["output_channel"] = oc
        # Live raises RuntimeError on return/master monitoring access; guard with try.
        try:
            result["monitoring_state"] = track.current_monitoring_state
        except Exception:
            pass
        return result

    def _assign_routing(self, track, current_attr, available_attr, value):
        """Match value (display_name or identifier) against the available list
        and assign the matching object to current_attr. Returns display_name."""
        available = list(getattr(track, available_attr))
        chosen = None
        is_num = isinstance(value, int) or (
            isinstance(value, str) and value.lstrip("-").isdigit())
        if is_num:
            ident = int(value)
            for c in available:
                if c.identifier == ident:
                    chosen = c
                    break
        else:
            lowered = str(value).strip().lower()
            for c in available:
                if c.display_name.lower() == lowered:
                    chosen = c
                    break
        if chosen is None:
            names = ", ".join(c.display_name for c in available)
            raise ValueError("Routing choice '%s' not found. Available: %s"
                             % (value, names))
        setattr(track, current_attr, chosen)
        return chosen.display_name

    def _set_routing(self, track_index, track_type, prop, value):
        """Set one routing endpoint or monitoring state. `prop` is canonical
        (server normalizes/validates via routing_utils before sending)."""
        track = self._resolve_track(track_index, track_type)
        out = {"track_type": track_type, "track_index": track_index, "property": prop}
        if prop == "input_type":
            out["value"] = self._assign_routing(
                track, "input_routing_type", "available_input_routing_types", value)
        elif prop == "input_channel":
            out["value"] = self._assign_routing(
                track, "input_routing_channel", "available_input_routing_channels", value)
        elif prop == "output_type":
            out["value"] = self._assign_routing(
                track, "output_routing_type", "available_output_routing_types", value)
        elif prop == "output_channel":
            out["value"] = self._assign_routing(
                track, "output_routing_channel", "available_output_routing_channels", value)
        elif prop == "monitor":
            track.current_monitoring_state = int(value)
            out["value"] = track.current_monitoring_state
        else:
            raise ValueError("Unsupported routing property: " + str(prop))
        return out

    def _get_device_parameters(self, track_index, device_index, track_type="regular"):
        """List all automatable parameters of a device on a track."""
        track, device = self._resolve_device(track_index, device_index, track_type)

        parameters = []
        for p_index, param in enumerate(device.parameters):
            info = {
                "index": p_index,
                "name": param.name,
                "value": param.value,
                "min": param.min,
                "max": param.max,
                "is_quantized": param.is_quantized,
                "is_enabled": param.is_enabled,
            }
            if param.is_quantized and hasattr(param, "value_items"):
                try:
                    info["value_items"] = [str(v) for v in param.value_items]
                except Exception:
                    pass
            parameters.append(info)

        return {
            "track_index": track_index,
            "track_type": track_type,
            "device_index": device_index,
            "device_name": device.name,
            "parameter_count": len(parameters),
            "parameters": parameters,
        }

    def _set_device_parameter(self, track_index, device_index, parameter_index, value,
                              track_type="regular"):
        """Set one device parameter by integer index, clamped to its range."""
        track, device = self._resolve_device(track_index, device_index, track_type)
        if parameter_index < 0 or parameter_index >= len(device.parameters):
            raise IndexError("Parameter index out of range")
        param = device.parameters[parameter_index]
        if not param.is_enabled:
            raise RuntimeError("Parameter '%s' is not settable (disabled)" % param.name)

        v = float(value)
        if v < param.min:
            v = param.min
        if v > param.max:
            v = param.max
        param.value = v

        return {
            "track_index": track_index,
            "track_type": track_type,
            "device_index": device_index,
            "parameter_index": parameter_index,
            "name": param.name,
            "value": param.value,
        }

    # ---- Phase 4: devices & racks -------------------------------------

    def _resolve_device(self, track_index, device_index, track_type):
        """Return (track, device) for a (track_index, device_index, track_type)."""
        track = self._resolve_track(track_index, track_type)
        if device_index < 0 or device_index >= len(track.devices):
            raise IndexError("Device index out of range")
        return track, track.devices[device_index]

    def _rack_macros(self, device):
        """Return list of {index, macro_number, name, value, min, max} for a
        rack's macro params.

        Macros are the device parameters between 'Device On' (index 0) and
        'Chain Selector' (when present) — identified by POSITION, not name,
        because macros may carry custom labels (e.g. 'Filter Cutoff') rather
        than 'Macro N'.
        """
        macros = []
        macro_number = 0
        for p_index, param in enumerate(device.parameters):
            name = str(param.name)
            if name == "Device On":
                continue
            if name == "Chain Selector":
                continue
            macro_number += 1
            macros.append({
                "index": p_index,
                "macro_number": macro_number,
                "name": param.name,
                "value": param.value,
                "min": param.min,
                "max": param.max,
            })
        return macros

    def _get_device_info(self, track_index, device_index, track_type):
        """Detailed info about a device, including rack macro/chain summary."""
        track, device = self._resolve_device(track_index, device_index, track_type)
        is_rack = bool(device.can_have_chains)
        info = {
            "track_index": track_index,
            "track_type": track_type,
            "device_index": device_index,
            "name": device.name,
            "class_name": device.class_name,
            "type": self._get_device_type(device),
            "is_active": device.is_active,
            "can_have_chains": is_rack,
            "can_have_drum_pads": bool(device.can_have_drum_pads),
            "parameter_count": len(device.parameters),
        }
        # "Device On" is parameters[0] for standard devices.
        try:
            if len(device.parameters) > 0 and device.parameters[0].name == "Device On":
                info["is_on"] = device.parameters[0].value >= 0.5
        except Exception:
            pass
        if is_rack:
            info["macro_count"] = len(self._rack_macros(device))
            try:
                info["chain_count"] = len(device.chains)
            except Exception:
                info["chain_count"] = 0
        return info

    def _delete_device(self, track_index, device_index, track_type):
        """Delete a device from a track; remaining devices re-index."""
        track, device = self._resolve_device(track_index, device_index, track_type)
        name = device.name
        track.delete_device(device_index)
        return {
            "track_index": track_index,
            "track_type": track_type,
            "deleted_device_index": device_index,
            "deleted_device_name": name,
            "device_count": len(track.devices),
        }

    def _set_device_on(self, track_index, device_index, on, track_type):
        """Enable/disable a device via its 'Device On' parameter."""
        track, device = self._resolve_device(track_index, device_index, track_type)
        if len(device.parameters) == 0 or device.parameters[0].name != "Device On":
            raise RuntimeError(
                "Device '%s' has no 'Device On' parameter" % device.name)
        param = device.parameters[0]
        param.value = 1.0 if on else 0.0
        return {
            "track_index": track_index,
            "track_type": track_type,
            "device_index": device_index,
            "name": device.name,
            "is_on": param.value >= 0.5,
        }

    def _get_rack_macros(self, track_index, device_index, track_type):
        """List macro controls of a rack device."""
        track, device = self._resolve_device(track_index, device_index, track_type)
        if not device.can_have_chains:
            raise RuntimeError("Device '%s' is not a rack" % device.name)
        return {
            "track_index": track_index,
            "track_type": track_type,
            "device_index": device_index,
            "device_name": device.name,
            "macros": self._rack_macros(device),
        }

    def _set_rack_macro(self, track_index, device_index, parameter_index, value, track_type):
        """Set a rack macro by its resolved device-parameter index, clamped."""
        track, device = self._resolve_device(track_index, device_index, track_type)
        if not device.can_have_chains:
            raise RuntimeError("Device '%s' is not a rack" % device.name)
        if parameter_index < 0 or parameter_index >= len(device.parameters):
            raise IndexError("Macro parameter index out of range")
        param = device.parameters[parameter_index]
        v = float(value)
        if v < param.min:
            v = param.min
        if v > param.max:
            v = param.max
        param.value = v
        return {
            "track_index": track_index,
            "track_type": track_type,
            "device_index": device_index,
            "parameter_index": parameter_index,
            "name": param.name,
            "value": param.value,
        }

    def _get_rack_chains(self, track_index, device_index, track_type):
        """List chains of a rack device with mute/solo + contained devices."""
        track, device = self._resolve_device(track_index, device_index, track_type)
        if not device.can_have_chains:
            raise RuntimeError("Device '%s' is not a rack" % device.name)
        chains = []
        for c_index, chain in enumerate(device.chains):
            chain_devices = []
            try:
                for d_index, d in enumerate(chain.devices):
                    chain_devices.append({
                        "index": d_index,
                        "name": d.name,
                        "type": self._get_device_type(d),
                    })
            except Exception:
                pass
            entry = {
                "index": c_index,
                "name": chain.name,
            }
            for attr in ("mute", "solo"):
                try:
                    entry[attr] = getattr(chain, attr)
                except Exception:
                    pass
            try:
                md = chain.mixer_device
                entry["volume"] = md.volume.value
                entry["panning"] = md.panning.value
            except Exception:
                pass
            entry["devices"] = chain_devices
            chains.append(entry)
        return {
            "track_index": track_index,
            "track_type": track_type,
            "device_index": device_index,
            "device_name": device.name,
            "chain_count": len(chains),
            "chains": chains,
        }

    def _set_chain_property(self, track_index, device_index, chain_index, prop, value, track_type):
        """Set mute/solo (bool) or volume/panning (clamped float) on a rack chain."""
        track, device = self._resolve_device(track_index, device_index, track_type)
        if not device.can_have_chains:
            raise RuntimeError("Device '%s' is not a rack" % device.name)
        if chain_index < 0 or chain_index >= len(device.chains):
            raise IndexError("Chain index out of range")
        chain = device.chains[chain_index]
        if prop in ("mute", "solo"):
            setattr(chain, prop, bool(value))
            applied = getattr(chain, prop)
        elif prop in ("volume", "panning"):
            md = chain.mixer_device
            param = md.volume if prop == "volume" else md.panning
            if not param.is_enabled:
                raise RuntimeError(
                    "Chain '%s' %s is not settable (disabled by Live for this chain)"
                    % (chain.name, prop))
            v = float(value)
            if v < param.min:
                v = param.min
            if v > param.max:
                v = param.max
            param.value = v
            applied = param.value
        else:
            raise ValueError("Unsupported chain property: " + str(prop))
        return {
            "track_index": track_index,
            "track_type": track_type,
            "device_index": device_index,
            "chain_index": chain_index,
            "chain_name": chain.name,
            "property": prop,
            "value": applied,
        }

    def _create_midi_track(self, index):
        """Create a new MIDI track at the specified index"""
        try:
            # Create the track
            self._song.create_midi_track(index)
            
            # Get the new track
            new_track_index = len(self._song.tracks) - 1 if index == -1 else index
            new_track = self._song.tracks[new_track_index]
            
            result = {
                "index": new_track_index,
                "name": new_track.name
            }
            return result
        except Exception as e:
            self.log_message("Error creating MIDI track: " + str(e))
            raise

    def _create_audio_track(self, index):
        """Create a new audio track at index (-1 = end)."""
        try:
            self._song.create_audio_track(index)
            new_index = len(self._song.tracks) - 1 if index == -1 else index
            new_track = self._song.tracks[new_index]
            return {"index": new_index, "name": new_track.name}
        except Exception as e:
            self.log_message("Error creating audio track: " + str(e))
            raise Exception("Could not create audio track (Live limit reached?): " + str(e))

    def _create_return_track(self):
        """Create a new return track at the end."""
        try:
            self._song.create_return_track()
            new_index = len(self._song.return_tracks) - 1
            new_track = self._song.return_tracks[new_index]
            return {"index": new_index, "name": new_track.name}
        except Exception as e:
            self.log_message("Error creating return track: " + str(e))
            raise Exception("Could not create return track (Live limit reached?): " + str(e))

    def _delete_track(self, index):
        """Delete the regular track at index; return remaining count."""
        if index < 0 or index >= len(self._song.tracks):
            raise Exception("Track index out of range (0..%d)" % (len(self._song.tracks) - 1,))
        self._song.delete_track(index)
        return {"deleted": True, "remaining_count": len(self._song.tracks)}

    def _delete_return_track(self, index):
        """Delete the return track at index; return remaining count."""
        if index < 0 or index >= len(self._song.return_tracks):
            raise Exception("Return track index out of range (0..%d)" % (len(self._song.return_tracks) - 1,))
        self._song.delete_return_track(index)
        return {"deleted": True, "remaining_count": len(self._song.return_tracks)}

    def _duplicate_track(self, index):
        """Duplicate the regular track at index; Live selects the new track."""
        if index < 0 or index >= len(self._song.tracks):
            raise Exception("Track index out of range (0..%d)" % (len(self._song.tracks) - 1,))
        self._song.duplicate_track(index)
        new_track = self._song.view.selected_track
        new_index = list(self._song.tracks).index(new_track)
        return {"new_index": new_index, "name": new_track.name}

    def _undo(self):
        """Undo the last action in Live's global undo stack (no-op if empty)."""
        if not self._song.can_undo:
            return {"undone": False, "reason": "nothing to undo",
                    "can_undo": False, "can_redo": self._song.can_redo}
        self._song.undo()
        return {"undone": True, "can_undo": self._song.can_undo,
                "can_redo": self._song.can_redo}

    def _redo(self):
        """Redo the last undone action (no-op if nothing to redo)."""
        if not self._song.can_redo:
            return {"redone": False, "reason": "nothing to redo",
                    "can_undo": self._song.can_undo, "can_redo": False}
        self._song.redo()
        return {"redone": True, "can_undo": self._song.can_undo,
                "can_redo": self._song.can_redo}


    def _set_track_name(self, track_index, name):
        """Set the name of a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            # Set the name
            track = self._song.tracks[track_index]
            track.name = name
            
            result = {
                "name": track.name
            }
            return result
        except Exception as e:
            self.log_message("Error setting track name: " + str(e))
            raise
    
    def _create_clip(self, track_index, clip_index, length):
        """Create a new MIDI clip in the specified track and clip slot"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            # Check if the clip slot already has a clip
            if clip_slot.has_clip:
                raise Exception("Clip slot already has a clip")
            
            # Create the clip
            clip_slot.create_clip(length)
            
            result = {
                "name": clip_slot.clip.name,
                "length": clip_slot.clip.length
            }
            return result
        except Exception as e:
            self.log_message("Error creating clip: " + str(e))
            raise
    
    def _build_note_spec(self, note):
        """Build a Live.Clip.MidiNoteSpecification from a fully-normalized note
        dict (server's clip_utils.normalize_note has already filled defaults)."""
        return Live.Clip.MidiNoteSpecification(
            pitch=int(note.get("pitch", 60)),
            start_time=float(note.get("start_time", 0.0)),
            duration=float(note.get("duration", 0.25)),
            velocity=float(note.get("velocity", 100)),
            mute=bool(note.get("mute", False)),
            probability=float(note.get("probability", 1.0)),
            velocity_deviation=float(note.get("velocity_deviation", 0.0)),
            release_velocity=float(note.get("release_velocity", 64.0)),
        )

    def _add_notes_to_clip(self, track_index, clip_index, notes):
        """Add MIDI notes to a clip via the Live 11 extended API (add_new_notes),
        which does not trigger the legacy-note-editor dialog."""
        try:
            clip = self._resolve_clip(track_index, clip_index)
            self._require_midi_clip(clip, "add_notes_to_clip")
            specs = [self._build_note_spec(n) for n in notes]
            clip.add_new_notes(tuple(specs))
            result = {
                "note_count": len(specs)
            }
            return result
        except Exception as e:
            self.log_message("Error adding notes to clip: " + str(e))
            raise
    
    def _set_clip_name(self, track_index, clip_index, name):
        """Set the name of a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip = clip_slot.clip
            clip.name = name
            
            result = {
                "name": clip.name
            }
            return result
        except Exception as e:
            self.log_message("Error setting clip name: " + str(e))
            raise
    
    def _set_tempo(self, tempo):
        """Set the tempo of the session"""
        try:
            self._song.tempo = tempo
            
            result = {
                "tempo": self._song.tempo
            }
            return result
        except Exception as e:
            self.log_message("Error setting tempo: " + str(e))
            raise
    
    def _fire_clip(self, track_index, clip_index):
        """Fire a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip_slot.fire()
            
            result = {
                "fired": True
            }
            return result
        except Exception as e:
            self.log_message("Error firing clip: " + str(e))
            raise
    
    def _stop_clip(self, track_index, clip_index):
        """Stop a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            clip_slot.stop()

            result = {
                "stopped": True
            }
            return result
        except Exception as e:
            self.log_message("Error stopping clip: " + str(e))
            raise

    # --- Phase 3: clip & MIDI editing ---

    def _resolve_clip(self, track_index, clip_index):
        """Return the Live clip object at (track_index, clip_index).
        Raises on out-of-range indices or an empty clip slot."""
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        if clip_index < 0 or clip_index >= len(track.clip_slots):
            raise IndexError("Clip index out of range")
        clip_slot = track.clip_slots[clip_index]
        if not clip_slot.has_clip:
            raise Exception("No clip in slot")
        return clip_slot.clip

    def _resolve_clip_loc(self, track_index, clip_index, clip_location):
        """Return the Live clip at (track_index, clip_index) in session or
        arrangement view. Raises on out-of-range / empty session slot."""
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        if clip_location == "arrangement":
            clips = track.arrangement_clips
            if clip_index < 0 or clip_index >= len(clips):
                raise IndexError("Arrangement clip index out of range")
            return clips[clip_index]
        # default: session
        if clip_index < 0 or clip_index >= len(track.clip_slots):
            raise IndexError("Clip index out of range")
        clip_slot = track.clip_slots[clip_index]
        if not clip_slot.has_clip:
            raise Exception("No clip in slot")
        return clip_slot.clip

    # --- Phase 7: change listeners --------------------------------------

    def _json_safe(self, v):
        """Coerce a property value to a JSON-serializable form."""
        if v is None or isinstance(v, (bool, int, float, str)):
            return v
        return str(v)

    def _listener_target_object(self, descriptor):
        """Navigate to the Live object the listener attaches to (per the
        canonical descriptor built server-side)."""
        kind = descriptor["target_kind"]
        sel = descriptor.get("selectors", {})
        ttype = sel.get("track_type", "regular")
        if kind == "song":
            return self._song
        if kind == "song_view":
            return self._song.view
        if kind == "track":
            return self._resolve_track(sel["track_index"], ttype)
        if kind == "track_mixer":
            track = self._resolve_track(sel["track_index"], ttype)
            sub = descriptor.get("mixer_sub")
            if sub == "volume":
                return track.mixer_device.volume
            if sub == "panning":
                return track.mixer_device.panning
            raise Exception("Unknown mixer_sub: " + str(sub))
        if kind in ("clip", "clip_slot"):
            track = self._resolve_track(sel["track_index"], ttype)
            ci = sel["clip_index"]
            if ci < 0 or ci >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            slot = track.clip_slots[ci]
            if kind == "clip_slot":
                return slot
            if not slot.has_clip:
                raise Exception("No clip in slot")
            return slot.clip
        if kind == "device_param":
            track = self._resolve_track(sel["track_index"], ttype)
            di = sel["device_index"]
            if di < 0 or di >= len(track.devices):
                raise IndexError("Device index out of range")
            device = track.devices[di]
            pi = sel["parameter_index"]
            if pi < 0 or pi >= len(device.parameters):
                raise IndexError("Parameter index out of range")
            return device.parameters[pi]
        raise Exception("Unknown target_kind: " + str(kind))

    def _listener_read_value(self, descriptor, target_obj):
        """Read the current value for a fired listener (callbacks take no args,
        so we read the live value here)."""
        if (descriptor["target_kind"] == "song_view"
                and descriptor["property"] == "selected_scene"):
            scenes = list(self._song.scenes)
            try:
                return scenes.index(self._song.view.selected_scene)
            except ValueError:
                return -1
        readback = descriptor.get("readback")
        if readback is None:
            return None
        return self._json_safe(getattr(target_obj, readback))

    def _listener_target_label(self, descriptor):
        """Short human label for a listener target."""
        sel = descriptor.get("selectors", {})
        scope = descriptor["scope"]
        prop = descriptor["property"]
        kind = descriptor["target_kind"]
        if kind in ("song", "song_view"):
            return scope + "." + prop
        if kind in ("track", "track_mixer"):
            return "%s[%s].%s" % (sel.get("track_type", "regular"),
                                  sel["track_index"], prop)
        if kind in ("clip", "clip_slot"):
            return "clip[%s/%s].%s" % (sel["track_index"], sel["clip_index"], prop)
        if kind == "device_param":
            return "device[%s/%s].param[%s]" % (
                sel["track_index"], sel["device_index"], sel["parameter_index"])
        return scope + "." + prop

    def _listener_emit(self, listener_id, value):
        """Append a change event to a listener's buffer (called from Live's
        main thread by the observer callback)."""
        with self._listener_lock:
            entry = self._listeners.get(listener_id)
            if entry is None:
                return
            self._listener_seq += 1
            buf = entry["events"]
            if buf.maxlen is not None and len(buf) == buf.maxlen:
                entry["dropped"] += 1  # deque evicts the oldest on append
            buf.append({
                "listener_id": listener_id,
                "target": entry["target"],
                "property": entry["descriptor"]["property"],
                "value": value,
                "seq": self._listener_seq,
            })

    def _make_listener_cb(self, listener_id, descriptor, target_obj):
        """Build a no-arg observer callback bound to one listener."""
        def _cb():
            try:
                value = self._listener_read_value(descriptor, target_obj)
            except Exception:
                value = None
            self._listener_emit(listener_id, value)
        return _cb

    def _register_listener(self, descriptor):
        """Attach a Live listener and start buffering its change events."""
        if not descriptor:
            raise Exception("Missing listener descriptor")
        target_obj = self._listener_target_object(descriptor)
        method = descriptor["listener_method"]
        if not hasattr(target_obj, method):
            raise Exception("Target object has no " + method)
        self._listener_id_counter += 1
        listener_id = "L%d" % self._listener_id_counter
        label = self._listener_target_label(descriptor)
        cb = self._make_listener_cb(listener_id, descriptor, target_obj)
        # Register the buffer BEFORE attaching so an immediate fire isn't lost.
        with self._listener_lock:
            self._listeners[listener_id] = {
                "descriptor": descriptor,
                "target": label,
                "target_obj": target_obj,
                "callback": cb,
                "events": collections.deque(maxlen=LISTENER_BUFFER_MAX),
                "dropped": 0,
            }
        getattr(target_obj, method)(cb)
        return {"listener_id": listener_id, "target": label,
                "property": descriptor["property"]}

    def _unregister_listener(self, listener_id):
        """Detach one listener (or all if listener_id is None) and drop its
        buffer. Runs on the main thread (Live remove_*_listener requirement)."""
        with self._listener_lock:
            ids = ([listener_id] if listener_id
                   else list(self._listeners.keys()))
        removed = []
        for lid in ids:
            entry = self._listeners.get(lid)
            if entry is None:
                continue
            try:
                getattr(entry["target_obj"],
                        entry["descriptor"]["remove_method"])(entry["callback"])
            except Exception as e:
                self.log_message("listener remove failed (" + str(lid) + "): "
                                 + str(e))
            with self._listener_lock:
                self._listeners.pop(lid, None)
            removed.append(lid)
        return {"removed": removed, "count": len(removed)}

    def _poll_changes(self, listener_id, max_events):
        """Drain buffered events (one listener or all). Called on a client
        thread; shares the lock with the main-thread emit."""
        events = []
        summary = []
        with self._listener_lock:
            ids = ([listener_id] if listener_id
                   else list(self._listeners.keys()))
            for lid in ids:
                entry = self._listeners.get(lid)
                if entry is None:
                    continue
                buf = entry["events"]
                n = len(buf) if max_events is None else min(int(max_events), len(buf))
                drained = [buf.popleft() for _ in range(n)]
                dropped = entry["dropped"]
                entry["dropped"] = 0
                events.extend(drained)
                summary.append({
                    "listener_id": lid,
                    "target": entry["target"],
                    "drained": len(drained),
                    "remaining": len(buf),
                    "dropped": dropped,
                })
        return {"events": events, "listeners": summary}

    def _list_listeners(self):
        """Report active listeners with pending/dropped counts."""
        with self._listener_lock:
            items = []
            for lid, entry in self._listeners.items():
                items.append({
                    "listener_id": lid,
                    "target": entry["target"],
                    "property": entry["descriptor"]["property"],
                    "pending": len(entry["events"]),
                    "dropped": entry["dropped"],
                })
        return {"listeners": items, "count": len(items)}

    def _resolve_auto_param(self, track_index, target_type, device_index,
                            parameter_index, mixer_property, send_index):
        """Return the DeviceParameter to automate (device param/macro or mixer
        volume/pan/send). `parameter_index` and `mixer_property` are already
        resolved/normalized by the server."""
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError("Track index out of range")
        track = self._song.tracks[track_index]
        if target_type == "mixer":
            md = track.mixer_device
            if mixer_property == "volume":
                return md.volume
            if mixer_property == "pan":
                return md.panning
            if mixer_property == "send":
                if send_index < 0 or send_index >= len(md.sends):
                    raise IndexError("send_index out of range")
                return md.sends[send_index]
            raise ValueError("Unsupported mixer_property: " + str(mixer_property))
        # default: device
        if device_index < 0 or device_index >= len(track.devices):
            raise IndexError("Device index out of range")
        device = track.devices[device_index]
        if parameter_index < 0 or parameter_index >= len(device.parameters):
            raise IndexError("Parameter index out of range")
        return device.parameters[parameter_index]

    def _get_automation(self, track_index, clip_index, clip_location,
                        target_type, device_index, parameter_index,
                        mixer_property, send_index, from_time, time_span,
                        resolution):
        """Sampled read of a parameter's automation envelope in a clip.
        No LOM API enumerates breakpoints, so we sample value_at_time."""
        clip = self._resolve_clip_loc(track_index, clip_index, clip_location)
        param = self._resolve_auto_param(
            track_index, target_type, device_index, parameter_index,
            mixer_property, send_index)
        env = clip.automation_envelope(param)
        result = {
            "clip_location": clip_location,
            "track_index": track_index,
            "clip_index": clip_index,
            "target": {"type": target_type, "name": param.name},
            "has_envelope": env is not None,
            "samples": [],
        }
        if env is None:
            return result
        start = float(from_time)
        span = float(time_span)
        if span < 0:
            span = clip.length
        n = int(resolution)
        if n < 1:
            n = 1
        samples = []
        if n == 1:
            samples.append({"time": start, "value": env.value_at_time(start)})
        else:
            step = span / float(n - 1)
            i = 0
            while i < n:
                t = start + step * i
                samples.append({"time": t, "value": env.value_at_time(t)})
                i = i + 1
        result["samples"] = samples
        return result

    def _set_automation(self, track_index, clip_index, clip_location,
                        target_type, device_index, parameter_index,
                        mixer_property, send_index, breakpoints):
        """Insert one or more breakpoints/steps into a parameter's envelope,
        creating the envelope if it does not yet exist. `breakpoints` is a
        server-validated list of {time, value, duration}."""
        clip = self._resolve_clip_loc(track_index, clip_index, clip_location)
        param = self._resolve_auto_param(
            track_index, target_type, device_index, parameter_index,
            mixer_property, send_index)
        env = clip.automation_envelope(param)
        if env is None:
            env = clip.create_automation_envelope(param)
        # insert_step writes a FLAT segment [time, time+duration); a 0 duration
        # is a no-op in Live. So auto-tile zero/negative durations: a point
        # holds until the next point's time (the last point fills to clip end).
        clip_len = clip.length
        ordered = sorted(breakpoints, key=lambda b: float(b["time"]))
        count = 0
        n = len(ordered)
        i = 0
        while i < n:
            bp = ordered[i]
            t = float(bp["time"])
            dur = float(bp["duration"])
            if dur <= 0:
                if i + 1 < n:
                    dur = float(ordered[i + 1]["time"]) - t
                else:
                    dur = clip_len - t
                if dur <= 0:
                    dur = 0.03125  # 1/32-beat fallback so the value registers
            env.insert_step(t, dur, float(bp["value"]))
            count = count + 1
            i = i + 1
        return {
            "clip_location": clip_location,
            "track_index": track_index,
            "clip_index": clip_index,
            "target": {"type": target_type, "name": param.name},
            "points_written": count,
        }

    def _clear_automation(self, track_index, clip_index, clip_location,
                         target_type, device_index, parameter_index,
                         mixer_property, send_index, from_time, time_span):
        """Clear a parameter's automation. With a range -> clear_range; without
        -> clear the whole envelope for that parameter."""
        clip = self._resolve_clip_loc(track_index, clip_index, clip_location)
        param = self._resolve_auto_param(
            track_index, target_type, device_index, parameter_index,
            mixer_property, send_index)
        out = {
            "clip_location": clip_location,
            "track_index": track_index,
            "clip_index": clip_index,
            "target": {"type": target_type, "name": param.name},
        }
        if from_time is not None and time_span is not None:
            env = clip.automation_envelope(param)
            if env is not None:
                env.clear_range(float(from_time), float(time_span))
            out["cleared"] = "range"
        else:
            clip.clear_envelope(param)
            out["cleared"] = "envelope"
        return out

    def _create_automation_envelope(self, track_index, clip_index,
                                    clip_location, target_type, device_index,
                                    parameter_index, mixer_property, send_index):
        """Explicitly create an empty envelope for a parameter. `created` is
        False if one already existed."""
        clip = self._resolve_clip_loc(track_index, clip_index, clip_location)
        param = self._resolve_auto_param(
            track_index, target_type, device_index, parameter_index,
            mixer_property, send_index)
        existed = clip.automation_envelope(param) is not None
        if not existed:
            clip.create_automation_envelope(param)
        return {
            "clip_location": clip_location,
            "track_index": track_index,
            "clip_index": clip_index,
            "target": {"type": target_type, "name": param.name},
            "created": (not existed),
        }

    def _clear_all_automation(self, track_index, clip_index, clip_location):
        """Remove every automation envelope in the clip."""
        clip = self._resolve_clip_loc(track_index, clip_index, clip_location)
        clip.clear_all_envelopes()
        return {
            "clip_location": clip_location,
            "track_index": track_index,
            "clip_index": clip_index,
            "cleared_all": True,
        }

    def _require_midi_clip(self, clip, action):
        if not clip.is_midi_clip:
            raise Exception("%s requires a MIDI clip" % action)

    def _note_dicts(self, midi_notes):
        """Serialize Live 11 MidiNote objects (from get_notes_extended) to dicts."""
        out = []
        for n in midi_notes:
            out.append({
                "note_id": n.note_id,
                "pitch": n.pitch,
                "start_time": n.start_time,
                "duration": n.duration,
                "velocity": n.velocity,
                "mute": n.mute,
                "probability": n.probability,
                "velocity_deviation": n.velocity_deviation,
                "release_velocity": n.release_velocity,
            })
        return out

    def _get_clip_info(self, track_index, clip_index):
        """Read clip properties. Audio-only fields are probed with try/except
        (Live raises RuntimeError -- not AttributeError -- on MIDI clips)."""
        try:
            clip = self._resolve_clip(track_index, clip_index)
            result = {
                "track_index": track_index,
                "clip_index": clip_index,
                "name": clip.name,
                "length": clip.length,
                "is_midi_clip": clip.is_midi_clip,
                "is_audio_clip": clip.is_audio_clip,
                "looping": clip.looping,
                "loop_start": clip.loop_start,
                "loop_end": clip.loop_end,
                "start_marker": clip.start_marker,
                "end_marker": clip.end_marker,
                "signature_numerator": clip.signature_numerator,
                "signature_denominator": clip.signature_denominator,
                "is_playing": clip.is_playing,
            }
            for attr in ("warping", "warp_mode", "gain", "gain_display_string",
                         "pitch_coarse", "pitch_fine",
                         # Phase 10 launch settings (valid on MIDI + audio).
                         "launch_mode", "launch_quantization", "legato",
                         "velocity_amount"):
                try:
                    result[attr] = getattr(clip, attr)
                except Exception:
                    pass
            return result
        except Exception as e:
            self.log_message("Error getting clip info: " + str(e))
            raise

    def _get_clip_notes(self, track_index, clip_index, from_time,
                        time_span, from_pitch, pitch_span):
        """Read MIDI notes within a window via the extended API. Note the
        extended arg order is (from_pitch, pitch_span, from_time, time_span) --
        pitch first, opposite the legacy get_notes."""
        try:
            clip = self._resolve_clip(track_index, clip_index)
            self._require_midi_clip(clip, "get_clip_notes")
            if time_span < 0:
                time_span = clip.length
            raw = clip.get_notes_extended(from_pitch, pitch_span, from_time, time_span)
            notes = self._note_dicts(raw)
            return {"note_count": len(notes), "notes": notes}
        except Exception as e:
            self.log_message("Error getting clip notes: " + str(e))
            raise

    def _replace_clip_notes(self, track_index, clip_index, notes):
        """Clear all notes then add the given notes, via the extended API (no
        legacy-note dialog)."""
        try:
            clip = self._resolve_clip(track_index, clip_index)
            self._require_midi_clip(clip, "replace_clip_notes")
            clip.remove_notes_extended(0, 128, 0.0, clip.length)
            specs = [self._build_note_spec(n) for n in notes]
            clip.add_new_notes(tuple(specs))
            return {"note_count": len(specs)}
        except Exception as e:
            self.log_message("Error replacing clip notes: " + str(e))
            raise

    def _remove_clip_notes(self, track_index, clip_index, from_time,
                           time_span, from_pitch, pitch_span):
        """Remove notes in a window via the extended API. Extended arg order:
        (from_pitch, pitch_span, from_time, time_span)."""
        try:
            clip = self._resolve_clip(track_index, clip_index)
            self._require_midi_clip(clip, "remove_clip_notes")
            if time_span < 0:
                time_span = clip.length
            clip.remove_notes_extended(from_pitch, pitch_span, from_time, time_span)
            return {"removed": True}
        except Exception as e:
            self.log_message("Error removing clip notes: " + str(e))
            raise

    def _modify_clip_notes(self, track_index, clip_index, notes):
        """Edit existing notes in place by note_id. Fetches the current notes,
        mutates the targeted MidiNote objects, and applies them back via
        apply_note_modifications -- untouched notes are preserved."""
        try:
            clip = self._resolve_clip(track_index, clip_index)
            self._require_midi_clip(clip, "modify_clip_notes")
            current = clip.get_notes_extended(0, 128, 0.0, clip.length)
            by_id = {}
            for n in current:
                by_id[n.note_id] = n
            modified = 0
            missing = []
            for spec in notes:
                nid = int(spec.get("note_id", -1))
                target = by_id.get(nid)
                if target is None:
                    missing.append(nid)
                    continue
                if "pitch" in spec:
                    target.pitch = int(spec["pitch"])
                if "start_time" in spec:
                    target.start_time = float(spec["start_time"])
                if "duration" in spec:
                    target.duration = float(spec["duration"])
                if "velocity" in spec:
                    target.velocity = float(spec["velocity"])
                if "mute" in spec:
                    target.mute = bool(spec["mute"])
                if "probability" in spec:
                    target.probability = float(spec["probability"])
                if "velocity_deviation" in spec:
                    target.velocity_deviation = float(spec["velocity_deviation"])
                if "release_velocity" in spec:
                    target.release_velocity = float(spec["release_velocity"])
                modified += 1
            if missing:
                raise Exception("note_id(s) not found in clip: %s" % missing)
            clip.apply_note_modifications(current)
            return {"modified": modified}
        except Exception as e:
            self.log_message("Error modifying clip notes: " + str(e))
            raise

    def _set_clip_property(self, track_index, clip_index, prop, value):
        """Set one clip property. `prop` is canonical (server normalizes/coerces
        first). Audio-only props on a MIDI clip raise a clear error."""
        try:
            clip = self._resolve_clip(track_index, clip_index)
            audio_only = ("warping", "warp_mode", "gain",
                          "pitch_coarse", "pitch_fine")
            if prop in audio_only and not clip.is_audio_clip:
                raise Exception(
                    "Property '%s' is audio-only; not valid on a MIDI clip" % prop)
            setattr(clip, prop, value)
            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "property": prop,
                "value": getattr(clip, prop),
            }
        except Exception as e:
            self.log_message("Error setting clip property: " + str(e))
            raise

    def _set_clip_loop(self, track_index, clip_index, loop_start,
                       loop_end, looping):
        """Set the loop window, writing edges in an order that never inverts
        the window. looping == -1 leaves looping unchanged."""
        try:
            clip = self._resolve_clip(track_index, clip_index)
            if loop_end <= loop_start:
                raise Exception(
                    "loop_end (%s) must be greater than loop_start (%s)"
                    % (loop_end, loop_start))
            if looping != -1:
                clip.looping = bool(looping)
            # Widen first: if the new window is to the right of the current one,
            # move the end before the start (and vice versa) to avoid an
            # invalid intermediate state.
            if loop_start >= clip.loop_end:
                clip.loop_end = loop_end
                clip.loop_start = loop_start
            else:
                clip.loop_start = loop_start
                clip.loop_end = loop_end
            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "loop_start": clip.loop_start,
                "loop_end": clip.loop_end,
                "looping": clip.looping,
            }
        except Exception as e:
            self.log_message("Error setting clip loop: " + str(e))
            raise

    def _quantize_clip(self, track_index, clip_index, grid, amount):
        """Quantize a MIDI clip's notes. `grid` is a RecordingQuantization int."""
        try:
            clip = self._resolve_clip(track_index, clip_index)
            self._require_midi_clip(clip, "quantize_clip")
            clip.quantize(grid, amount)
            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "grid": grid,
                "amount": amount,
            }
        except Exception as e:
            self.log_message("Error quantizing clip: " + str(e))
            raise

    def _duplicate_clip(self, track_index, clip_index, target_clip_index):
        """Duplicate a clip into another (empty) slot on the same track."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            source_slot = track.clip_slots[clip_index]
            if not source_slot.has_clip:
                raise Exception("No clip in slot")
            if target_clip_index < 0:
                target_clip_index = clip_index + 1
            if target_clip_index < 0 or target_clip_index >= len(track.clip_slots):
                raise IndexError("Target clip index out of range")
            target_slot = track.clip_slots[target_clip_index]
            if target_slot.has_clip:
                raise Exception("Target clip slot already has a clip")
            source_slot.duplicate_clip_to(target_slot)
            return {
                "track_index": track_index,
                "source_clip_index": clip_index,
                "target_clip_index": target_clip_index,
                "name": target_slot.clip.name,
            }
        except Exception as e:
            self.log_message("Error duplicating clip: " + str(e))
            raise

    def _delete_clip(self, track_index, clip_index):
        """Delete the clip in a slot (the slot itself remains)."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip_slot.delete_clip()
            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "deleted": True,
            }
        except Exception as e:
            self.log_message("Error deleting clip: " + str(e))
            raise
    
    
    def _start_playback(self):
        """Start playing the session"""
        try:
            self._song.start_playing()
            
            result = {
                "playing": self._song.is_playing
            }
            return result
        except Exception as e:
            self.log_message("Error starting playback: " + str(e))
            raise
    
    def _stop_playback(self):
        """Stop playing the session"""
        try:
            self._song.stop_playing()
            
            result = {
                "playing": self._song.is_playing
            }
            return result
        except Exception as e:
            self.log_message("Error stopping playback: " + str(e))
            raise

    # --- Scenes ---------------------------------------------------------

    def _scene_at(self, scene_index):
        """Return song.scenes[scene_index] or raise IndexError."""
        scenes = self._song.scenes
        if scene_index < 0 or scene_index >= len(scenes):
            raise IndexError(
                "Scene index %d out of range (0..%d)"
                % (scene_index, len(scenes) - 1))
        return scenes[scene_index]

    def _scene_dict(self, scene, index):
        info = {
            "index": index,
            "name": scene.name,
            "is_empty": scene.is_empty,
            "is_triggered": scene.is_triggered,
        }
        try:
            info["color"] = scene.color
        except Exception:
            pass
        try:
            info["tempo"] = scene.tempo
            info["tempo_enabled"] = scene.tempo_enabled
        except Exception:
            pass
        try:
            info["time_signature_numerator"] = scene.time_signature_numerator
            info["time_signature_denominator"] = scene.time_signature_denominator
        except Exception:
            pass
        return info

    def _get_scenes(self):
        """List all scenes in the session."""
        try:
            scenes = self._song.scenes
            return {
                "scene_count": len(scenes),
                "scenes": [self._scene_dict(scenes[i], i)
                           for i in range(len(scenes))],
            }
        except Exception as e:
            self.log_message("Error getting scenes: " + str(e))
            raise

    def _fire_scene(self, scene_index):
        """Launch a scene (fires all its clips)."""
        try:
            scene = self._scene_at(scene_index)
            scene.fire()
            return {"fired": scene_index}
        except Exception as e:
            self.log_message("Error firing scene: " + str(e))
            raise

    def _create_scene(self, index):
        """Create a scene at index (-1 appends)."""
        try:
            self._song.create_scene(index)
            return {"scene_count": len(self._song.scenes), "index": index}
        except Exception as e:
            self.log_message("Error creating scene: " + str(e))
            raise

    def _delete_scene(self, scene_index):
        """Delete a scene."""
        try:
            # Validate range before delete (delete_scene takes the index).
            self._scene_at(scene_index)
            self._song.delete_scene(scene_index)
            return {"scene_count": len(self._song.scenes)}
        except Exception as e:
            self.log_message("Error deleting scene: " + str(e))
            raise

    def _duplicate_scene(self, scene_index):
        """Duplicate a scene (copy inserted after it)."""
        try:
            self._scene_at(scene_index)
            self._song.duplicate_scene(scene_index)
            return {"scene_count": len(self._song.scenes)}
        except Exception as e:
            self.log_message("Error duplicating scene: " + str(e))
            raise

    def _set_scene_name(self, scene_index, name):
        """Rename a scene."""
        try:
            scene = self._scene_at(scene_index)
            scene.name = name
            return {"scene_index": scene_index, "name": scene.name}
        except Exception as e:
            self.log_message("Error setting scene name: " + str(e))
            raise

    def _set_scene_property(self, scene_index, prop, value):
        """Set color / tempo / tempo_enabled / time_signature on a scene.
        Values arrive already coerced from the server."""
        try:
            scene = self._scene_at(scene_index)
            if prop == "color":
                scene.color = int(value)
            elif prop == "tempo":
                scene.tempo = float(value)
            elif prop == "tempo_enabled":
                scene.tempo_enabled = bool(value)
            elif prop == "time_signature":
                # value is [numerator, denominator]
                scene.time_signature_numerator = int(value[0])
                scene.time_signature_denominator = int(value[1])
            else:
                raise ValueError("Unsupported scene property: %s" % prop)
            return {"scene_index": scene_index, "property": prop, "value": value}
        except Exception as e:
            self.log_message("Error setting scene property: " + str(e))
            raise

    # --- Transport ------------------------------------------------------

    def _continue_playback(self):
        """Resume playback from the current position."""
        try:
            self._song.continue_playing()
            return {"playing": self._song.is_playing}
        except Exception as e:
            self.log_message("Error continuing playback: " + str(e))
            raise

    def _get_transport(self):
        """Read transport / arrangement state."""
        try:
            song = self._song
            info = {
                "is_playing": song.is_playing,
                "current_song_time": song.current_song_time,
                "tempo": song.tempo,
                "signature_numerator": song.signature_numerator,
                "signature_denominator": song.signature_denominator,
                "metronome": song.metronome,
                "loop": song.loop,
                "loop_start": song.loop_start,
                "loop_length": song.loop_length,
                "record_mode": song.record_mode,
                "punch_in": song.punch_in,
                "punch_out": song.punch_out,
            }
            try:
                info["session_record"] = song.session_record
            except Exception:
                pass
            try:
                info["song_length"] = song.song_length
            except Exception:
                pass
            try:
                info["back_to_arranger"] = song.back_to_arranger
            except Exception:
                pass
            # Phase 10: global feel / quantization.
            # Phase 11: capture / recording state (all read-only).
            for key in ("groove_amount", "swing_amount",
                        "clip_trigger_quantization", "midi_recording_quantization",
                        "count_in_duration", "nudge_up", "nudge_down",
                        "can_capture_midi", "is_counting_in",
                        "session_record_status"):
                try:
                    info[key] = getattr(song, key)
                except Exception:
                    pass
            return info
        except Exception as e:
            self.log_message("Error getting transport: " + str(e))
            raise

    def _set_metronome(self, on):
        """Toggle the metronome."""
        try:
            self._song.metronome = bool(on)
            return {"metronome": self._song.metronome}
        except Exception as e:
            self.log_message("Error setting metronome: " + str(e))
            raise

    def _set_groove_amount(self, value):
        """Set the global groove amount (0.0-1.0). Read-back may lag."""
        try:
            self._song.groove_amount = float(value)
            return {"groove_amount": self._song.groove_amount}
        except Exception as e:
            self.log_message("Error setting groove amount: " + str(e))
            raise

    def _get_groove_pool(self, params):
        """List the grooves in Live's Groove Pool (index + name)."""
        grooves = list(self._song.groove_pool.grooves)
        return {
            "count": len(grooves),
            "grooves": [{"index": i, "name": g.name}
                        for i, g in enumerate(grooves)],
        }

    def _assign_groove_to_clip(self, params):
        """Assign a Groove-Pool groove to a clip. The selector is resolved
        server-side to {by:'index'|'name', value:...}; the pool lives here in
        Live's process so the final lookup happens here. Read-back lags, so we
        report the intended groove name (the mutation itself is reliable)."""
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        by = params.get("by", "index")
        value = params.get("value")
        song = self._song
        grooves = list(song.groove_pool.grooves)
        if not grooves:
            raise Exception("Groove Pool is empty - drag a groove into the "
                            "Groove Pool in Live first")
        tracks = song.tracks
        if track_index < 0 or track_index >= len(tracks):
            raise Exception("track_index %d out of range" % track_index)
        track = tracks[track_index]
        if clip_index < 0 or clip_index >= len(track.clip_slots):
            raise Exception("clip_index %d out of range" % clip_index)
        clip = track.clip_slots[clip_index].clip
        if clip is None:
            raise Exception("no clip at track %d slot %d" % (track_index, clip_index))
        if by == "name":
            matches = [g for g in grooves if g.name == value]
            if not matches:
                raise Exception("no groove named %r in pool (have: %s)"
                                % (value, [g.name for g in grooves]))
            target = matches[0]
        else:
            if not isinstance(value, int) or value < 0 or value >= len(grooves):
                raise Exception("groove index %r out of range (pool has %d)"
                                % (value, len(grooves)))
            target = grooves[value]
        clip.groove = target
        return {
            "assigned": target.name,
            "track_index": track_index,
            "clip_index": clip_index,
            "pool_count": len(grooves),
        }

    def _set_swing_amount(self, value):
        """Set the global swing amount (0.0-1.0). Read-back may lag."""
        try:
            self._song.swing_amount = float(value)
            return {"swing_amount": self._song.swing_amount}
        except Exception as e:
            self.log_message("Error setting swing amount: " + str(e))
            raise

    def _set_clip_trigger_quantization(self, value):
        """Set the global Session clip-launch quantization (enum int)."""
        try:
            self._song.clip_trigger_quantization = int(value)
            return {"clip_trigger_quantization": self._song.clip_trigger_quantization}
        except Exception as e:
            self.log_message("Error setting clip trigger quantization: " + str(e))
            raise

    def _set_midi_recording_quantization(self, value):
        """Set the global MIDI-recording quantization (enum int)."""
        try:
            self._song.midi_recording_quantization = int(value)
            return {"midi_recording_quantization":
                    self._song.midi_recording_quantization}
        except Exception as e:
            self.log_message("Error setting MIDI recording quantization: " + str(e))
            raise

    def _set_nudge(self, direction, active):
        """Hold/release a tempo-nudge button (direction 'up'|'down')."""
        try:
            value = bool(active)
            if direction == "up":
                self._song.nudge_up = value
            elif direction == "down":
                self._song.nudge_down = value
            else:
                raise Exception("Unknown nudge direction '%s' (up|down)" % (direction,))
            return {"direction": direction, "active": value}
        except Exception as e:
            self.log_message("Error setting nudge: " + str(e))
            raise

    def _capture_midi(self, destination):
        """Capture recently played MIDI material. destination is a name
        ('auto'|'session'|'arrangement') resolved here to the Live enum int.
        Read-back may lag — confirm via a follow-up read."""
        try:
            dest_enum = getattr(Live.Song.CaptureDestination, destination)
            self._song.capture_midi(dest_enum)
            return {"captured": True, "destination": destination}
        except Exception as e:
            self.log_message("Error capturing MIDI: " + str(e))
            raise

    def _capture_and_insert_scene(self, mode):
        """Capture currently playing clips into a new scene. mode is a name
        ('all') resolved here to the Live enum int."""
        try:
            mode_enum = getattr(Live.Song.CaptureMode, mode)
            self._song.capture_and_insert_scene(mode_enum)
            return {"captured": True, "mode": mode}
        except Exception as e:
            self.log_message("Error capturing scene: " + str(e))
            raise

    def _trigger_session_record(self, record_length):
        """Trigger a new Session recording. record_length (beats) optional;
        omit for Live's open-ended default."""
        try:
            if record_length is None:
                self._song.trigger_session_record()
            else:
                self._song.trigger_session_record(float(record_length))
            return {"triggered": True, "record_length": record_length}
        except Exception as e:
            self.log_message("Error triggering session record: " + str(e))
            raise

    def _stop_all_clips(self, track_index, quantized):
        """Stop all playing clips (track_index None) or one track's clips."""
        try:
            quant = bool(quantized)
            if track_index is None:
                self._song.stop_all_clips(quant)
                return {"stopped": True, "scope": "song", "quantized": quant}
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError(
                    "Track index out of range (0..%d)"
                    % (len(self._song.tracks) - 1,))
            self._song.tracks[track_index].stop_all_clips(quant)
            return {"stopped": True, "scope": "track",
                    "track_index": track_index, "quantized": quant}
        except Exception as e:
            self.log_message("Error stopping all clips: " + str(e))
            raise

    def _tap_tempo(self):
        """Trigger Live's tap-tempo (one tap)."""
        try:
            self._song.tap_tempo()
            return {"tapped": True, "tempo": self._song.tempo}
        except Exception as e:
            self.log_message("Error tapping tempo: " + str(e))
            raise

    def _set_selected_track(self, track_index, track_type):
        """Select a track in the Session/Arrangement view."""
        try:
            song = self._song
            if track_type == "master":
                track = song.master_track
                idx = -1
            elif track_type == "return":
                returns = song.return_tracks
                if track_index < 0 or track_index >= len(returns):
                    raise Exception(
                        "Return track index out of range (0..%d)"
                        % (len(returns) - 1,))
                track = returns[track_index]
                idx = track_index
            else:
                tracks = song.tracks
                if track_index < 0 or track_index >= len(tracks):
                    raise Exception(
                        "Track index out of range (0..%d)" % (len(tracks) - 1,))
                track = tracks[track_index]
                idx = track_index
            song.view.selected_track = track
            return {"selected_track": track.name, "track_type": track_type,
                    "track_index": idx}
        except Exception as e:
            self.log_message("Error setting selected track: " + str(e))
            raise

    def _set_selected_scene(self, scene_index):
        """Select a scene in the Session view."""
        try:
            scenes = self._song.scenes
            if scene_index < 0 or scene_index >= len(scenes):
                raise Exception(
                    "Scene index out of range (0..%d)" % (len(scenes) - 1,))
            self._song.view.selected_scene = scenes[scene_index]
            return {"selected_scene": scene_index, "name": scenes[scene_index].name}
        except Exception as e:
            self.log_message("Error setting selected scene: " + str(e))
            raise

    def _set_detail_clip(self, track_index, clip_slot_index):
        """Show a Session clip in Live's Detail view (slot must hold a clip)."""
        try:
            tracks = self._song.tracks
            if track_index < 0 or track_index >= len(tracks):
                raise Exception(
                    "Track index out of range (0..%d)" % (len(tracks) - 1,))
            slots = tracks[track_index].clip_slots
            if clip_slot_index < 0 or clip_slot_index >= len(slots):
                raise Exception(
                    "Clip slot index out of range (0..%d)" % (len(slots) - 1,))
            slot = slots[clip_slot_index]
            if not slot.has_clip:
                raise Exception(
                    "No clip in slot %d on track %d" % (clip_slot_index, track_index))
            self._song.view.detail_clip = slot.clip
            return {"detail_clip": slot.clip.name,
                    "track_index": track_index,
                    "clip_slot_index": clip_slot_index}
        except Exception as e:
            self.log_message("Error setting detail clip: " + str(e))
            raise

    def _set_highlighted_clip_slot(self, track_index, scene_index):
        """Highlight a Session clip slot (regular track + scene)."""
        try:
            tracks = self._song.tracks
            if track_index < 0 or track_index >= len(tracks):
                raise Exception(
                    "Track index out of range (0..%d)" % (len(tracks) - 1,))
            slots = tracks[track_index].clip_slots
            if scene_index < 0 or scene_index >= len(slots):
                raise Exception(
                    "Scene index out of range (0..%d)" % (len(slots) - 1,))
            self._song.view.highlighted_clip_slot = slots[scene_index]
            return {"track_index": track_index, "scene_index": scene_index,
                    "has_clip": slots[scene_index].has_clip}
        except Exception as e:
            self.log_message("Error setting highlighted clip slot: " + str(e))
            raise

    def _set_track_fold(self, track_index, folded):
        """Fold/unfold a group track. Rejected if the track is not foldable."""
        try:
            tracks = self._song.tracks
            if track_index < 0 or track_index >= len(tracks):
                raise Exception(
                    "Track index out of range (0..%d)" % (len(tracks) - 1,))
            track = tracks[track_index]
            if not track.is_foldable:
                raise Exception(
                    "Track %d ('%s') is not a group track (not foldable)"
                    % (track_index, track.name))
            track.fold_state = 1 if folded else 0
            return {"track_index": track_index, "name": track.name,
                    "fold_state": track.fold_state}
        except Exception as e:
            self.log_message("Error setting track fold: " + str(e))
            raise

    def _get_view_selection(self):
        """Read the current Live view selection."""
        try:
            song = self._song
            view = song.view
            out = {}
            try:
                sel_track = view.selected_track
                out["selected_track_name"] = sel_track.name
                # Resolve index within regular tracks (None for return/master).
                idx = None
                for i in range(len(song.tracks)):
                    if song.tracks[i] == sel_track:
                        idx = i
                        break
                out["selected_track_index"] = idx
            except Exception:
                pass
            try:
                sel_scene = view.selected_scene
                sidx = None
                for i in range(len(song.scenes)):
                    if song.scenes[i] == sel_scene:
                        sidx = i
                        break
                out["selected_scene_index"] = sidx
            except Exception:
                pass
            try:
                dc = view.detail_clip
                out["detail_clip"] = dc.name if dc is not None else None
            except Exception:
                pass
            try:
                slot = view.highlighted_clip_slot
                out["highlighted_clip_slot_has_clip"] = (
                    slot.has_clip if slot is not None else None)
            except Exception:
                pass
            return out
        except Exception as e:
            self.log_message("Error getting view selection: " + str(e))
            raise

    def _set_arrangement_record(self, on):
        """Arm/disarm arrangement record (record_mode)."""
        try:
            self._song.record_mode = bool(on)
            return {"record_mode": self._song.record_mode}
        except Exception as e:
            self.log_message("Error setting arrangement record: " + str(e))
            raise

    def _set_session_record(self, on):
        """Toggle session record."""
        try:
            self._song.session_record = bool(on)
            return {"session_record": self._song.session_record}
        except Exception as e:
            self.log_message("Error setting session record: " + str(e))
            raise

    def _set_punch(self, punch_in, punch_out):
        """Set punch-in/out flags (only the provided ones)."""
        try:
            if punch_in is not None:
                self._song.punch_in = bool(punch_in)
            if punch_out is not None:
                self._song.punch_out = bool(punch_out)
            return {
                "punch_in": self._song.punch_in,
                "punch_out": self._song.punch_out,
            }
        except Exception as e:
            self.log_message("Error setting punch: " + str(e))
            raise

    def _set_song_position(self, time_beats):
        """Jump the playhead to an absolute beat position."""
        try:
            self._song.current_song_time = float(time_beats)
            return {"current_song_time": self._song.current_song_time}
        except Exception as e:
            self.log_message("Error setting song position: " + str(e))
            raise

    def _jump_by(self, beats):
        """Nudge the playhead by +/- beats."""
        try:
            self._song.jump_by(float(beats))
            return {"current_song_time": self._song.current_song_time}
        except Exception as e:
            self.log_message("Error jumping by beats: " + str(e))
            raise

    # --- Arrangement ----------------------------------------------------

    def _set_arrangement_loop(self, enabled, start, length):
        """Set the arrangement loop brace (only the provided fields)."""
        try:
            song = self._song
            if start is not None:
                song.loop_start = float(start)
            if length is not None:
                song.loop_length = float(length)
            if enabled is not None:
                song.loop = bool(enabled)
            return {
                "loop": song.loop,
                "loop_start": song.loop_start,
                "loop_length": song.loop_length,
            }
        except Exception as e:
            self.log_message("Error setting arrangement loop: " + str(e))
            raise

    def _get_cue_points(self):
        """List arrangement cue points (locators)."""
        try:
            cues = self._song.cue_points
            return {
                "cue_count": len(cues),
                "cue_points": [
                    {"index": i, "name": cues[i].name, "time": cues[i].time}
                    for i in range(len(cues))
                ],
            }
        except Exception as e:
            self.log_message("Error getting cue points: " + str(e))
            raise

    def _jump_to_cue(self, direction):
        """Jump to the next/prev arrangement cue. direction is 'next' or 'prev'."""
        try:
            if direction == "next":
                self._song.jump_to_next_cue()
            elif direction == "prev":
                self._song.jump_to_prev_cue()
            else:
                raise ValueError("direction must be 'next' or 'prev'")
            return {
                "direction": direction,
                "current_song_time": self._song.current_song_time,
            }
        except Exception as e:
            self.log_message("Error jumping to cue: " + str(e))
            raise

    def _back_to_arrangement(self):
        """Re-engage the arrangement after launching session clips."""
        try:
            self._song.back_to_arranger = 0
            return {"back_to_arranger": self._song.back_to_arranger}
        except Exception as e:
            self.log_message("Error returning to arrangement: " + str(e))
            raise

    def _create_cue_at_playhead(self):
        """Create a cue point at the CURRENT playhead position via
        set_or_delete_cue(). The server positions the playhead in a separate,
        already-settled command first (current_song_time writes are async and
        do NOT settle within one task). No-ops if a cue already sits here, so
        the toggle never deletes an existing marker."""
        try:
            pos = self._song.current_song_time
            cues = self._song.cue_points
            for i in range(len(cues)):
                if abs(cues[i].time - pos) <= 1e-6:
                    return {"created": False, "reason": "exists",
                            "index": i, "time": cues[i].time}
            self._song.set_or_delete_cue()
            cues = self._song.cue_points
            for i in range(len(cues)):
                if abs(cues[i].time - pos) <= 1e-6:
                    return {"created": True, "index": i, "time": cues[i].time}
            return {"created": True, "index": -1, "time": pos}
        except Exception as e:
            self.log_message("Error creating cue at playhead: " + str(e))
            raise

    def _delete_cue_at_playhead(self):
        """Delete the cue at the CURRENT playhead position via
        set_or_delete_cue(). The server positions the playhead to the target
        cue's time in a separate, settled command first. No-ops if no cue sits
        here (so the toggle never creates one)."""
        try:
            pos = self._song.current_song_time
            cues = self._song.cue_points
            found = -1
            for i in range(len(cues)):
                if abs(cues[i].time - pos) <= 1e-6:
                    found = i
                    break
            if found < 0:
                return {"deleted": False, "reason": "absent", "time": pos}
            self._song.set_or_delete_cue()
            return {"deleted": True, "index": found, "time": pos}
        except Exception as e:
            self.log_message("Error deleting cue at playhead: " + str(e))
            raise

    def _get_arrangement_clips(self, track_index):
        """List the clips placed on a track's Arrangement timeline."""
        try:
            tracks = self._song.tracks
            if track_index < 0 or track_index >= len(tracks):
                raise IndexError(
                    "Track index out of range (0..%d)" % (len(tracks) - 1))
            track = tracks[track_index]
            clips = track.arrangement_clips
            out = []
            for i in range(len(clips)):
                c = clips[i]
                out.append({
                    "index": i,
                    "name": c.name,
                    "start_time": c.start_time,
                    "end_time": c.end_time,
                    "length": c.length,
                    "is_midi_clip": c.is_midi_clip,
                })
            return {"track_index": track_index, "count": len(out), "clips": out}
        except Exception as e:
            self.log_message("Error getting arrangement clips: " + str(e))
            raise

    def _duplicate_clip_to_arrangement(self, track_index, source_slot_index,
                                       destination_time):
        """Place a same-track Session-slot clip onto the Arrangement timeline."""
        try:
            tracks = self._song.tracks
            if track_index < 0 or track_index >= len(tracks):
                raise IndexError(
                    "Track index out of range (0..%d)" % (len(tracks) - 1))
            track = tracks[track_index]
            slots = track.clip_slots
            if source_slot_index < 0 or source_slot_index >= len(slots):
                raise IndexError(
                    "Slot index out of range (0..%d)" % (len(slots) - 1))
            slot = slots[source_slot_index]
            if not slot.has_clip:
                raise ValueError(
                    "No clip in session slot %d on track %d"
                    % (source_slot_index, track_index))
            new_clip = track.duplicate_clip_to_arrangement(
                slot.clip, float(destination_time))
            info = None
            if new_clip is not None:
                info = {
                    "name": new_clip.name,
                    "start_time": new_clip.start_time,
                    "end_time": new_clip.end_time,
                }
            return {
                "track_index": track_index,
                "source_slot_index": source_slot_index,
                "destination_time": float(destination_time),
                "placed": True,
                "new_clip": info,
            }
        except Exception as e:
            self.log_message("Error duplicating clip to arrangement: " + str(e))
            raise

    def _delete_arrangement_clip(self, track_index, clip_index):
        """Delete a clip from a track's Arrangement timeline."""
        try:
            tracks = self._song.tracks
            if track_index < 0 or track_index >= len(tracks):
                raise IndexError(
                    "Track index out of range (0..%d)" % (len(tracks) - 1))
            track = tracks[track_index]
            clips = track.arrangement_clips
            n = len(clips)
            if clip_index < 0 or clip_index >= n:
                if n == 0:
                    raise IndexError(
                        "No arrangement clips on track %d" % track_index)
                raise IndexError(
                    "Arrangement clip index out of range (0..%d)" % (n - 1))
            name = clips[clip_index].name
            track.delete_clip(clips[clip_index])
            return {"track_index": track_index, "clip_index": clip_index,
                    "deleted": True, "name": name}
        except Exception as e:
            self.log_message("Error deleting arrangement clip: " + str(e))
            raise

    def _re_enable_automation(self):
        """Re-enable automation that was overridden."""
        try:
            self._song.re_enable_automation()
            return {"re_enabled": True}
        except Exception as e:
            self.log_message("Error re-enabling automation: " + str(e))
            raise

    def _get_browser_item(self, uri, path):
        """Get a browser item by URI or path"""
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            result = {
                "uri": uri,
                "path": path,
                "found": False
            }
            
            # Try to find by URI first if provided
            if uri:
                item = self._find_browser_item_by_uri(app.browser, uri)
                if item:
                    result["found"] = True
                    result["item"] = {
                        "name": item.name,
                        "is_folder": item.is_folder,
                        "is_device": item.is_device,
                        "is_loadable": item.is_loadable,
                        "uri": item.uri
                    }
                    return result
            
            # If URI not provided or not found, try by path
            if path:
                # Parse the path and navigate to the specified item
                path_parts = path.split("/")
                
                # Determine the root based on the first part
                current_item = None
                if path_parts[0].lower() == "nstruments":
                    current_item = app.browser.instruments
                elif path_parts[0].lower() == "sounds":
                    current_item = app.browser.sounds
                elif path_parts[0].lower() == "drums":
                    current_item = app.browser.drums
                elif path_parts[0].lower() == "audio_effects":
                    current_item = app.browser.audio_effects
                elif path_parts[0].lower() == "midi_effects":
                    current_item = app.browser.midi_effects
                else:
                    # Default to instruments if not specified
                    current_item = app.browser.instruments
                    # Don't skip the first part in this case
                    path_parts = ["instruments"] + path_parts
                
                # Navigate through the path
                for i in range(1, len(path_parts)):
                    part = path_parts[i]
                    if not part:  # Skip empty parts
                        continue
                    
                    found = False
                    for child in current_item.children:
                        if child.name.lower() == part.lower():
                            current_item = child
                            found = True
                            break
                    
                    if not found:
                        result["error"] = "Path part '{0}' not found".format(part)
                        return result
                
                # Found the item
                result["found"] = True
                result["item"] = {
                    "name": current_item.name,
                    "is_folder": current_item.is_folder,
                    "is_device": current_item.is_device,
                    "is_loadable": current_item.is_loadable,
                    "uri": current_item.uri
                }
            
            return result
        except Exception as e:
            self.log_message("Error getting browser item: " + str(e))
            self.log_message(traceback.format_exc())
            raise   
    
    
    
    def _load_browser_item(self, track_index, item_uri, track_type="regular"):
        """Load a browser item onto a track by its URI"""
        try:
            track = self._resolve_track(track_index, track_type)

            # Access the application's browser instance instead of creating a new one
            app = self.application()

            # Find the browser item by URI
            item = self._find_browser_item_by_uri(app.browser, item_uri)

            if not item:
                raise ValueError("Browser item with URI '{0}' not found".format(item_uri))

            # Select the track
            self._song.view.selected_track = track

            # Load the item
            app.browser.load_item(item)

            result = {
                "loaded": True,
                "item_name": item.name,
                "track_name": track.name,
                "track_type": track_type,
                "uri": item_uri
            }
            return result
        except Exception as e:
            self.log_message("Error loading browser item: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
    
    def _find_browser_item_by_uri(self, browser_or_item, uri, max_depth=10, current_depth=0):
        """Find a browser item by its URI"""
        try:
            # Check if this is the item we're looking for
            if hasattr(browser_or_item, 'uri') and browser_or_item.uri == uri:
                return browser_or_item
            
            # Stop recursion if we've reached max depth
            if current_depth >= max_depth:
                return None
            
            # Check if this is a browser with root categories
            if hasattr(browser_or_item, 'instruments'):
                # Check all main categories. user_library/packs/current_project
                # are essential for loading User Library presets (.adv/.adg) and
                # were previously omitted, so those URIs were never found.
                categories = []
                for attr in ('instruments', 'sounds', 'drums', 'audio_effects',
                             'midi_effects', 'user_library', 'packs',
                             'current_project', 'clips', 'samples'):
                    if hasattr(browser_or_item, attr):
                        try:
                            categories.append(getattr(browser_or_item, attr))
                        except Exception:
                            pass
                # user_folders (browser "Places") is a list of BrowserItems.
                if hasattr(browser_or_item, 'user_folders'):
                    try:
                        categories.extend(list(browser_or_item.user_folders))
                    except Exception:
                        pass

                for category in categories:
                    item = self._find_browser_item_by_uri(category, uri, max_depth, current_depth + 1)
                    if item:
                        return item

                return None
            
            # Check if this item has children
            if hasattr(browser_or_item, 'children') and browser_or_item.children:
                for child in browser_or_item.children:
                    item = self._find_browser_item_by_uri(child, uri, max_depth, current_depth + 1)
                    if item:
                        return item
            
            return None
        except Exception as e:
            self.log_message("Error finding browser item by URI: {0}".format(str(e)))
            return None
    
    # Helper methods
    
    def _get_device_type(self, device):
        """Get the type of a device"""
        try:
            # Simple heuristic - in a real implementation you'd look at the device class
            if device.can_have_drum_pads:
                return "drum_machine"
            elif device.can_have_chains:
                return "rack"
            elif "instrument" in device.class_display_name.lower():
                return "instrument"
            elif "audio_effect" in device.class_name.lower():
                return "audio_effect"
            elif "midi_effect" in device.class_name.lower():
                return "midi_effect"
            else:
                return "unknown"
        except:
            return "unknown"
    
    def get_browser_tree(self, category_type="all"):
        """
        Get a simplified tree of browser categories.
        
        Args:
            category_type: Type of categories to get ('all', 'instruments', 'sounds', etc.)
            
        Returns:
            Dictionary with the browser tree structure
        """
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            # Check if browser is available
            if not hasattr(app, 'browser') or app.browser is None:
                raise RuntimeError("Browser is not available in the Live application")
            
            # Log available browser attributes to help diagnose issues
            browser_attrs = [attr for attr in dir(app.browser) if not attr.startswith('_')]
            self.log_message("Available browser attributes: {0}".format(browser_attrs))
            
            result = {
                "type": category_type,
                "categories": [],
                "available_categories": browser_attrs
            }
            
            # Helper function to process a browser item and its children
            def process_item(item, depth=0):
                if not item:
                    return None
                
                result = {
                    "name": item.name if hasattr(item, 'name') else "Unknown",
                    "is_folder": hasattr(item, 'children') and bool(item.children),
                    "is_device": hasattr(item, 'is_device') and item.is_device,
                    "is_loadable": hasattr(item, 'is_loadable') and item.is_loadable,
                    "uri": item.uri if hasattr(item, 'uri') else None,
                    "children": []
                }
                
                
                return result
            
            # Process based on category type and available attributes
            if (category_type == "all" or category_type == "instruments") and hasattr(app.browser, 'instruments'):
                try:
                    instruments = process_item(app.browser.instruments)
                    if instruments:
                        instruments["name"] = "Instruments"  # Ensure consistent naming
                        result["categories"].append(instruments)
                except Exception as e:
                    self.log_message("Error processing instruments: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "sounds") and hasattr(app.browser, 'sounds'):
                try:
                    sounds = process_item(app.browser.sounds)
                    if sounds:
                        sounds["name"] = "Sounds"  # Ensure consistent naming
                        result["categories"].append(sounds)
                except Exception as e:
                    self.log_message("Error processing sounds: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "drums") and hasattr(app.browser, 'drums'):
                try:
                    drums = process_item(app.browser.drums)
                    if drums:
                        drums["name"] = "Drums"  # Ensure consistent naming
                        result["categories"].append(drums)
                except Exception as e:
                    self.log_message("Error processing drums: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "audio_effects") and hasattr(app.browser, 'audio_effects'):
                try:
                    audio_effects = process_item(app.browser.audio_effects)
                    if audio_effects:
                        audio_effects["name"] = "Audio Effects"  # Ensure consistent naming
                        result["categories"].append(audio_effects)
                except Exception as e:
                    self.log_message("Error processing audio_effects: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "midi_effects") and hasattr(app.browser, 'midi_effects'):
                try:
                    midi_effects = process_item(app.browser.midi_effects)
                    if midi_effects:
                        midi_effects["name"] = "MIDI Effects"
                        result["categories"].append(midi_effects)
                except Exception as e:
                    self.log_message("Error processing midi_effects: {0}".format(str(e)))
            
            # Try to process other potentially available categories
            for attr in browser_attrs:
                if attr not in ['instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects'] and \
                   (category_type == "all" or category_type == attr):
                    try:
                        item = getattr(app.browser, attr)
                        if hasattr(item, 'children') or hasattr(item, 'name'):
                            category = process_item(item)
                            if category:
                                category["name"] = attr.capitalize()
                                result["categories"].append(category)
                    except Exception as e:
                        self.log_message("Error processing {0}: {1}".format(attr, str(e)))
            
            self.log_message("Browser tree generated for {0} with {1} root categories".format(
                category_type, len(result['categories'])))
            return result
            
        except Exception as e:
            self.log_message("Error getting browser tree: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
    
    def get_browser_items_at_path(self, path):
        """
        Get browser items at a specific path.
        
        Args:
            path: Path in the format "category/folder/subfolder"
                 where category is one of: instruments, sounds, drums, audio_effects, midi_effects
                 or any other available browser category
                 
        Returns:
            Dictionary with items at the specified path
        """
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            # Check if browser is available
            if not hasattr(app, 'browser') or app.browser is None:
                raise RuntimeError("Browser is not available in the Live application")
            
            # Log available browser attributes to help diagnose issues
            browser_attrs = [attr for attr in dir(app.browser) if not attr.startswith('_')]
            self.log_message("Available browser attributes: {0}".format(browser_attrs))
                
            # Parse the path
            path_parts = path.split("/")
            if not path_parts:
                raise ValueError("Invalid path")
            
            # Determine the root category
            root_category = path_parts[0].lower()
            current_item = None
            
            # Check standard categories first
            if root_category == "instruments" and hasattr(app.browser, 'instruments'):
                current_item = app.browser.instruments
            elif root_category == "sounds" and hasattr(app.browser, 'sounds'):
                current_item = app.browser.sounds
            elif root_category == "drums" and hasattr(app.browser, 'drums'):
                current_item = app.browser.drums
            elif root_category == "audio_effects" and hasattr(app.browser, 'audio_effects'):
                current_item = app.browser.audio_effects
            elif root_category == "midi_effects" and hasattr(app.browser, 'midi_effects'):
                current_item = app.browser.midi_effects
            else:
                # Try to find the category in other browser attributes
                found = False
                for attr in browser_attrs:
                    if attr.lower() == root_category:
                        try:
                            current_item = getattr(app.browser, attr)
                            found = True
                            break
                        except Exception as e:
                            self.log_message("Error accessing browser attribute {0}: {1}".format(attr, str(e)))
                
                if not found:
                    # If we still haven't found the category, return available categories
                    return {
                        "path": path,
                        "error": "Unknown or unavailable category: {0}".format(root_category),
                        "available_categories": browser_attrs,
                        "items": []
                    }
            
            # Navigate through the path
            for i in range(1, len(path_parts)):
                part = path_parts[i]
                if not part:  # Skip empty parts
                    continue
                
                if not hasattr(current_item, 'children'):
                    return {
                        "path": path,
                        "error": "Item at '{0}' has no children".format('/'.join(path_parts[:i])),
                        "items": []
                    }
                
                found = False
                for child in current_item.children:
                    if hasattr(child, 'name') and child.name.lower() == part.lower():
                        current_item = child
                        found = True
                        break
                
                if not found:
                    return {
                        "path": path,
                        "error": "Path part '{0}' not found".format(part),
                        "items": []
                    }
            
            # Get items at the current path
            items = []
            if hasattr(current_item, 'children'):
                for child in current_item.children:
                    item_info = {
                        "name": child.name if hasattr(child, 'name') else "Unknown",
                        "is_folder": hasattr(child, 'children') and bool(child.children),
                        "is_device": hasattr(child, 'is_device') and child.is_device,
                        "is_loadable": hasattr(child, 'is_loadable') and child.is_loadable,
                        "uri": child.uri if hasattr(child, 'uri') else None
                    }
                    items.append(item_info)
            
            result = {
                "path": path,
                "name": current_item.name if hasattr(current_item, 'name') else "Unknown",
                "uri": current_item.uri if hasattr(current_item, 'uri') else None,
                "is_folder": hasattr(current_item, 'children') and bool(current_item.children),
                "is_device": hasattr(current_item, 'is_device') and current_item.is_device,
                "is_loadable": hasattr(current_item, 'is_loadable') and current_item.is_loadable,
                "items": items
            }
            
            self.log_message("Retrieved {0} items at path: {1}".format(len(items), path))
            return result
            
        except Exception as e:
            self.log_message("Error getting browser items at path: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    def get_browser_presets(self, path, max_depth=6):
        """
        Recursively list loadable presets under a browser path.

        Args:
            path: Path in the format "category/folder/subfolder" (same grammar
                  as get_browser_items_at_path); category is one of instruments,
                  sounds, drums, audio_effects, midi_effects, or any available
                  browser attribute.
            max_depth: How many levels of children to descend (preset trees are
                  shallow; keeps pathological recursion bounded).

        Returns:
            {"path", "count", "presets": [{"name", "relative_path", "uri"}, ...]}
            on success, or the same {error, available_categories|...} envelope as
            get_browser_items_at_path on a path miss.
        """
        try:
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
            if not hasattr(app, 'browser') or app.browser is None:
                raise RuntimeError("Browser is not available in the Live application")

            browser_attrs = [attr for attr in dir(app.browser) if not attr.startswith('_')]

            # Parse the path and locate the start node (mirrors
            # get_browser_items_at_path's root-category + path-walk logic).
            path_parts = path.split("/")
            if not path_parts:
                raise ValueError("Invalid path")

            root_category = path_parts[0].lower()
            current_item = None
            if root_category == "instruments" and hasattr(app.browser, 'instruments'):
                current_item = app.browser.instruments
            elif root_category == "sounds" and hasattr(app.browser, 'sounds'):
                current_item = app.browser.sounds
            elif root_category == "drums" and hasattr(app.browser, 'drums'):
                current_item = app.browser.drums
            elif root_category == "audio_effects" and hasattr(app.browser, 'audio_effects'):
                current_item = app.browser.audio_effects
            elif root_category == "midi_effects" and hasattr(app.browser, 'midi_effects'):
                current_item = app.browser.midi_effects
            else:
                found = False
                for attr in browser_attrs:
                    if attr.lower() == root_category:
                        try:
                            current_item = getattr(app.browser, attr)
                            found = True
                            break
                        except Exception as e:
                            self.log_message("Error accessing browser attribute {0}: {1}".format(attr, str(e)))
                if not found:
                    return {
                        "path": path,
                        "error": "Unknown or unavailable category: {0}".format(root_category),
                        "available_categories": browser_attrs,
                        "presets": []
                    }

            for i in range(1, len(path_parts)):
                part = path_parts[i]
                if not part:
                    continue
                if not hasattr(current_item, 'children'):
                    return {
                        "path": path,
                        "error": "Item at '{0}' has no children".format('/'.join(path_parts[:i])),
                        "presets": []
                    }
                found = False
                for child in current_item.children:
                    if hasattr(child, 'name') and child.name.lower() == part.lower():
                        current_item = child
                        found = True
                        break
                if not found:
                    return {
                        "path": path,
                        "error": "Path part '{0}' not found".format(part),
                        "presets": []
                    }

            # Recursively collect loadable leaves.
            presets = []

            def walk(node, rel_parts, depth):
                if depth > max_depth:
                    return
                if not hasattr(node, 'children'):
                    return
                for child in node.children:
                    cname = child.name if hasattr(child, 'name') else "Unknown"
                    loadable = hasattr(child, 'is_loadable') and child.is_loadable
                    has_kids = hasattr(child, 'children') and bool(child.children)
                    if loadable:
                        presets.append({
                            "name": cname,
                            "relative_path": "/".join(rel_parts + [cname]),
                            "uri": child.uri if hasattr(child, 'uri') else None,
                        })
                    if has_kids:
                        walk(child, rel_parts + [cname], depth + 1)

            walk(current_item, [], 0)

            self.log_message("Found {0} presets under path: {1}".format(len(presets), path))
            return {"path": path, "count": len(presets), "presets": presets}

        except Exception as e:
            self.log_message("Error getting browser presets: {0}".format(str(e)))
            self.log_message(traceback.format_exc())

    def find_sample_uri(self, name, category="samples"):
        """Resolve a sample base name to its browser URI by walking a category.

        The LOM browser exposes a loadable item's name + uri but not its file
        path, so the host (which has the path from a filesystem walk) resolves
        the uri here by matching the base name. Returns
        {"uri": <first match or None>, "matches": <count>}; matches exactly
        first, then case-insensitively.
        """
        try:
            app = self.application()
            if not app or not hasattr(app, 'browser') or app.browser is None:
                return {"uri": None, "matches": 0}
            root = getattr(app.browser, category, None)
            if root is None:
                return {"uri": None, "matches": 0}
            lower = name.lower()
            exact = []
            ci = []

            def walk(node, depth):
                if depth > 8 or not hasattr(node, 'children'):
                    return
                for child in node.children:
                    cname = child.name if hasattr(child, 'name') else ""
                    loadable = hasattr(child, 'is_loadable') and child.is_loadable
                    if loadable and hasattr(child, 'uri'):
                        if cname == name:
                            exact.append(child.uri)
                        elif cname.lower() == lower:
                            ci.append(child.uri)
                    if hasattr(child, 'children') and child.children:
                        walk(child, depth + 1)

            walk(root, 0)
            if exact:
                return {"uri": exact[0], "matches": len(exact)}
            if ci:
                return {"uri": ci[0], "matches": len(ci)}
            return {"uri": None, "matches": 0}
        except Exception as e:
            self.log_message("Error in find_sample_uri: {0}".format(str(e)))
            return {"uri": None, "matches": 0}

    def _select_drum_pad(self, track_index, pad_note):
        """Select the Drum Rack pad for a MIDI note so a following
        load_browser_item lands the sample on that pad."""
        try:
            tracks = self._song.tracks
            if track_index < 0 or track_index >= len(tracks):
                return {"selected": False, "error": "track index out of range"}
            track = tracks[track_index]
            rack = None
            for d in track.devices:
                if hasattr(d, 'can_have_drum_pads') and d.can_have_drum_pads:
                    rack = d
                    break
            if rack is None:
                return {"selected": False, "error": "no drum rack on track"}
            for pad in rack.drum_pads:
                if pad.note == pad_note:
                    rack.view.selected_drum_pad = pad
                    return {"selected": True, "pad_note": pad_note}
            return {"selected": False,
                    "error": "no pad for note %d" % pad_note}
        except Exception as e:
            self.log_message("Error in select_drum_pad: " + str(e))
            return {"selected": False, "error": str(e)}
            raise
