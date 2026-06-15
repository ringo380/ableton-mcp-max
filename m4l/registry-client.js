// registry-client.js - Node-for-Max client for the unified MCP Tap device.
// Connects OUT to the Python-hosted tap registry (127.0.0.1:9878), announces this
// device's track identity, then streams per-100ms stat blocks. Reconnects if the
// registry restarts.
//
// Identity is derived entirely via the proven live.object query mechanism:
//   - the device's canonical_parent -> the track's LOM id  (selector "trk")
//   - live_set's ordered tracks / return_tracks / master_track id lists ("song")
//   - the track's position in those lists = (index, kind)
//
// Max -> Node:
//   "trk"   id <T>                         track LOM id (from canonical_parent)
//   "song"  tracks|return_tracks|master_track id <..> id <..>
//   "sr"    <sample_rate>
//   "block" <ms_k_l> <ms_k_r> <peak> [rms] [b0..b7] [mid] [side]
// Registry -> device (one JSON object/line): {"command":"reset"|"ping"}

const net = require('net');
const Max = require('max-api');

const PORT = 9878;
const HOST = '127.0.0.1';

let identity = {
  uuid: 'u' + Math.floor(Math.random() * 1e9),
  name: '', index: -99, kind: 'unknown', color: 0, debug: '',
};
let sampleRate = 48000;
let sock = null;
let connected = false;

let trackId = null;
let songTracks = [];
let songReturns = [];
let songMaster = null;

function send(obj) { if (sock && connected) { try { sock.write(JSON.stringify(obj) + '\n'); } catch (e) {} } }
function sendHello() {
  send({ type: 'hello', track: identity, device: 'mcp-tap', version: '2.0.0', sample_rate: sampleRate });
}

// Extract the LOM ids out of a "<listtype> id N id M ..." token list.
function ids(arr) {
  const out = [];
  for (let i = 0; i < arr.length; i++) {
    if (String(arr[i]) === 'id' && i + 1 < arr.length) out.push(String(arr[i + 1]));
  }
  return out;
}

function recompute() {
  if (trackId == null) return;
  let idx = songTracks.indexOf(trackId);
  if (idx >= 0) { identity.index = idx; identity.kind = 'regular'; }
  else {
    const r = songReturns.indexOf(trackId);
    if (r >= 0) { identity.index = r; identity.kind = 'return'; }
    else if (songMaster === trackId) { identity.index = -1; identity.kind = 'master'; }
  }
  identity.debug = ('trk=' + trackId + ' T=' + songTracks.length + ' R=' + songReturns.length + ' M=' + songMaster).slice(0, 180);
  if (connected) sendHello();
}

Max.addHandler('trk', (...t) => {
  const s = t.map(String); const k = s.indexOf('id');
  if (k >= 0) trackId = s[k + 1];
  recompute();
});
Max.addHandler('song', (...t) => {
  const s = t.map(String); const lt = s[0];
  if (lt === 'tracks') songTracks = ids(s);
  else if (lt === 'return_tracks') songReturns = ids(s);
  else if (lt === 'master_track') { const m = ids(s); songMaster = m[0] || null; }
  recompute();
});

Max.addHandler('sr', (v) => { sampleRate = v; if (connected) sendHello(); });

Max.addHandler('block', (...a) => {
  const bands = a.slice(4, 12);
  send({ type: 'block', data: {
    ms_k_l: a[0] || 0, ms_k_r: a[1] || 0, peak: a[2] || 0,
    rms: (a[3] == null ? null : a[3]),
    bands: bands.length === 8 ? bands : [0, 0, 0, 0, 0, 0, 0, 0],
    mid: a[12] || 0, side: a[13] || 0,
  } });
});

function connect() {
  sock = net.connect(PORT, HOST, () => { connected = true; sendHello(); Max.post('tap connected'); });
  sock.on('data', (chunk) => {
    String(chunk).split('\n').forEach((line) => {
      if (!line.trim()) return;
      try { const m = JSON.parse(line); if (m.command === 'reset') Max.outlet('reset'); } catch (e) {}
    });
  });
  sock.on('error', () => {});
  sock.on('close', () => { connected = false; setTimeout(connect, 2000); });
}
connect();
