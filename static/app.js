/* Sony WH-1000XM6 Web Controller — Frontend */

const API = '';
let isConnected = false;
let pollTimer = null;

// --- API helpers ---

async function api(method, path, body) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    try {
        const res = await fetch(API + path, opts);
        return await res.json();
    } catch (err) {
        console.error(`API ${method} ${path} failed:`, err);
        return { error: err.message };
    }
}

// --- Connection ---

async function toggleConnection() {
    const btn = document.getElementById('connectBtn');
    btn.disabled = true;
    btn.textContent = isConnected ? 'Disconnecting...' : 'Connecting...';

    if (isConnected) {
        await api('POST', '/api/disconnect');
    } else {
        await api('POST', '/api/connect');
    }
    await pollStatus();
    btn.disabled = false;
}

// --- Status polling ---

async function pollStatus() {
    const data = await api('GET', '/api/status');
    if (data.error) return;

    isConnected = data.connected;

    // Connection indicator
    const dot = document.getElementById('statusDot');
    const text = document.getElementById('statusText');
    const btn = document.getElementById('connectBtn');

    dot.classList.toggle('connected', isConnected);
    text.textContent = isConnected ? 'Connected' : 'Disconnected';
    btn.textContent = isConnected ? 'Disconnect' : 'Connect';
    btn.classList.toggle('connected', isConnected);

    // Battery
    if (data.battery >= 0) {
        const pct = Math.min(100, Math.max(0, data.battery));
        document.getElementById('batteryPercent').textContent = pct + '%';
        const fill = document.getElementById('batteryFill');
        fill.style.width = pct + '%';
        fill.classList.toggle('low', pct <= 20);
        fill.classList.toggle('mid', pct > 20 && pct <= 50);
    } else {
        document.getElementById('batteryPercent').textContent = '--%';
    }

    const chargingEl = document.getElementById('batteryCharging');
    chargingEl.style.display = data.charging ? 'inline' : 'none';

    // ANC mode
    if (data.anc_mode && data.anc_mode !== 'unknown') {
        setActiveAnc(data.anc_mode);
    }

    // Volume
    if (data.volume >= 0) {
        document.getElementById('volumeSlider').value = data.volume;
        document.getElementById('volumeValue').textContent = data.volume;
    }

    // Toggles
    document.getElementById('dseeToggle').checked = data.dsee;
    document.getElementById('stcToggle').checked = data.speak_to_chat;
}

function startPolling() {
    pollStatus();
    pollTimer = setInterval(pollStatus, 5000);
}

// --- ANC ---

function setActiveAnc(mode) {
    document.querySelectorAll('.anc-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mode === mode);
    });
    document.getElementById('ambientOptions').style.display =
        mode === 'ambient' ? 'block' : 'none';
}

async function setAnc(mode) {
    setActiveAnc(mode);
    const level = parseInt(document.getElementById('ambientLevel').value);
    const focus = document.getElementById('focusVoice').checked;
    await api('POST', '/api/anc', { mode, level, focus });
}

function updateAmbientLabel() {
    const val = document.getElementById('ambientLevel').value;
    document.getElementById('ambientValue').textContent = val;
}

// --- EQ ---

async function setEq(preset) {
    document.querySelectorAll('.eq-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.preset === preset);
    });
    await api('POST', '/api/eq', { preset });
}

// --- Volume ---

function updateVolumeLabel() {
    const val = document.getElementById('volumeSlider').value;
    document.getElementById('volumeValue').textContent = val;
}

async function setVolume() {
    const level = parseInt(document.getElementById('volumeSlider').value);
    await api('POST', '/api/volume', { level });
}

// --- Playback ---

async function sendPlayback(action) {
    await api('POST', '/api/playback', { action });
}

// --- Feature toggles ---

async function setDsee() {
    const enabled = document.getElementById('dseeToggle').checked;
    await api('POST', '/api/dsee', { enabled });
}

async function setSpeakToChat() {
    const enabled = document.getElementById('stcToggle').checked;
    await api('POST', '/api/speak-to-chat', { enabled });
}

// --- Init ---

document.addEventListener('DOMContentLoaded', startPolling);
