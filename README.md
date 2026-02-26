# Sony WH-1000XM6 Web Controller for macOS

A web-based controller for Sony WH-1000XM6 headphones on macOS. Since Sony doesn't provide a desktop app, this project reverse-engineers the Bluetooth RFCOMM protocol to control your headphones directly from the browser.

<img width="520" alt="screenshot" src="https://img.shields.io/badge/dark_theme-UI-1a1a1f?style=for-the-badge">

## Features

| Feature | Status |
|---------|--------|
| Noise Cancelling (NC) toggle | Working |
| Ambient Sound mode + level (1-20) | Working |
| Focus on Voice | Working |
| Battery level + charging status | Working |
| Volume control (0-30) | Working |
| DSEE Extreme (AI upscaling) | Working |
| Speak-to-Chat | Working |
| Playback control (play/pause/skip) | Working (via macOS/Spotify) |
| Equalizer presets | Not supported (XM6 uses different channel) |

## Architecture

```
Browser (localhost:5050)
    ↕ HTTP REST API
Flask (daemon thread)
    ↕ thread-safe queue
IOBluetooth RFCOMM (main thread + NSRunLoop)
    ↕ Bluetooth RFCOMM
Sony WH-1000XM6
```

**Why this architecture?** macOS IOBluetooth is NOT thread-safe. The main thread runs `CFRunLoopRunInMode` for Bluetooth delegate callbacks, while Flask serves HTTP in a daemon thread. All BT operations are marshaled to the main thread via a queue.

## Setup

### Prerequisites

- macOS (tested on macOS 15 Sequoia)
- Python 3.10+
- Sony WH-1000XM6 paired via System Settings > Bluetooth

### Install

```bash
git clone https://github.com/andersonsouza/sony-xm6-web.git
cd sony-xm6-web
pip install -r requirements.txt
```

### Run

```bash
python app.py
```

Open http://localhost:5050 in your browser and click **Connect**.

## Protocol Details

The WH-1000XM6 uses a proprietary binary protocol over Bluetooth RFCOMM, reverse-engineered from HCI traffic captures and the [sony-headphones-client](https://github.com/ibatra/sony-headphones-client) project.

### Key findings for XM6

- **Service UUID (V2)**: `956C7B26-D49A-4BA8-B03F-B17D393CB6E2` on RFCOMM channel 9
- **Data type**: XM6 uses `DataMdr` (0x0C) for commands — NOT `DataMdrNo2` (0x0E) used by XM5
- **Sequence numbers**: Alternate 0↔1 (bidirectional ACK handshake)
- **ACK type**: Always 0x01 regardless of data type
- **Init handshake**: Required after connect — `[0x00, 0x00]` then `[0x06, 0x00]`

### Command Map

| Feature | GET | Response | SET | Response |
|---------|-----|----------|-----|----------|
| Battery | `22 00` | `23 [00, level, charging]` | — | — |
| NC/ANC | `66 19` | `67 [19, ...]` | `68 19 01 enable asm nc level focus 00` | `69` |
| Volume | `A6 20` | `A7 [20, level]` | `A8 20 level` | `A9` |
| DSEE | `E6 01` | `E7 [01, on/off]` | `E8 01 on/off` | `E9` |
| Speak-to-Chat | `F6 02` | `F7 [02, on, ...]` | `F8 02 on sens timeout` | `F9` |

### PyObjC Quirks

IOBluetooth bindings in PyObjC have incorrect type metadata for some methods:
- `getRFCOMMChannelID:` — needs `o^C` (output pointer to UInt8), not `*` (char pointer)
- `openRFCOMMChannelAsync:withChannelID:delegate:` — first param needs `o^@` (output object pointer)

These are fixed at import time via `objc.registerMetaDataForSelector()`.

## REST API

| Endpoint | Method | Body | Description |
|----------|--------|------|-------------|
| `/api/devices` | GET | — | List paired Sony headphones |
| `/api/connect` | POST | `{"address": "..."}` | Connect (auto-discovers if no address) |
| `/api/disconnect` | POST | — | Disconnect |
| `/api/status` | GET | — | Battery, ANC mode, volume, toggles |
| `/api/anc` | POST | `{"mode": "off\|nc\|ambient", "level": 0-20, "focus": bool}` | Set noise control |
| `/api/volume` | POST | `{"level": 0-30}` | Set volume |
| `/api/dsee` | POST | `{"enabled": bool}` | Toggle DSEE |
| `/api/speak-to-chat` | POST | `{"enabled": bool}` | Toggle Speak-to-Chat |
| `/api/playback` | POST | `{"action": "play\|pause\|next\|prev"}` | Media control (via macOS) |

## Credits

- Protocol reference: [ibatra/sony-headphones-client](https://github.com/ibatra/sony-headphones-client) (Rust/Tauri)
- V2 UUID discovery: [Plutoberth/SonyHeadphonesClient](https://github.com/Plutoberth/SonyHeadphonesClient)
- XM5/XM6 support: [mos9527/SonyHeadphonesClient](https://github.com/mos9527/SonyHeadphonesClient)
- Protocol docs: [Gadgetbridge Sony Headphones](https://codeberg.org/Freeyourgadget/Gadgetbridge/wiki/Sony-Headphones)

## License

MIT
