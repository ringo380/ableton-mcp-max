// tap-server.js - Node-for-Max relay for the MCP Audio Tap device.
// Receives per-100ms block stats from the Max patch via Max messages and serves
// a reset-able rolling buffer over TCP :9878 using the {ok,data} envelope.
//
// Max -> Node messages (via the [node.script] object inlet, handled below):
//   "block"  <ms_k_l> <ms_k_r> <tp>   one 100ms block of stats
//   "sr"     <sample_rate>            report device sample rate
//   "peak"   <linear_peak>            running sample-peak since reset
//   "rms"    <linear_rms>             running RMS since reset
//
// TCP commands (one JSON object per connection write): {"command":"ping|reset|read"}

const net = require('net');
const Max = require('max-api');

const PORT = 9878;
const MAX_BLOCKS = 36000;          // ~1 hour at 10 blocks/s
const BLOCK_SECONDS = 0.1;

let sampleRate = 48000;
let channels = 2;
let blocks = [];
let peak = 0.0;
let rms = 0.0;

Max.addHandler('sr', (v) => { sampleRate = v; });
Max.addHandler('peak', (v) => { peak = v; });
Max.addHandler('rms', (v) => { rms = v; });
Max.addHandler('block', (msL, msR, tp) => {
  blocks.push({ ms_k_l: msL, ms_k_r: msR, tp: tp });
  if (blocks.length > MAX_BLOCKS) blocks.shift();
});

function resetBuffer() {
  blocks = [];
  peak = 0.0;
  rms = 0.0;
}

function readPayload() {
  return {
    sample_rate: sampleRate,
    since_reset_s: blocks.length * BLOCK_SECONDS,
    block_count: blocks.length,
    truncated: blocks.length >= MAX_BLOCKS,
    blocks: blocks,
    peak: peak,
    rms: rms,
  };
}

function handle(command) {
  switch (command) {
    case 'ping':
      return { ok: true, data: { device: 'mcp-audio-tap', version: '1.0.0',
                                 sample_rate: sampleRate, channels: channels } };
    case 'reset':
      resetBuffer();
      return { ok: true, data: { reset: true } };
    case 'read':
      return { ok: true, data: readPayload() };
    default:
      return { ok: false, error: 'unknown command: ' + command };
  }
}

const server = net.createServer((socket) => {
  let buf = '';
  socket.on('data', (chunk) => {
    buf += chunk.toString('utf8');
    let msg;
    try {
      msg = JSON.parse(buf);
    } catch (e) {
      return; // wait for the rest of the frame
    }
    buf = '';
    let resp;
    try {
      resp = handle(msg.command);
    } catch (e) {
      resp = { ok: false, error: String(e) };
    }
    socket.write(JSON.stringify(resp));
  });
  socket.on('error', () => {});
});

server.on('error', (e) => { Max.post('tap-server error: ' + e.message); });
server.listen(PORT, '127.0.0.1', () => { Max.post('tap-server listening on ' + PORT); });
