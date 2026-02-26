"""Sony WH-1000XM6 Web Controller — Entry Point.

Architecture:
    Main thread  → IOBluetooth + NSRunLoop (required by macOS)
    Daemon thread → Flask HTTP server

ALL Bluetooth operations (connect, disconnect, send_command) must run on
the main thread. Flask routes schedule them via run_on_main().
"""

import logging
import queue
import threading

from flask import Flask, jsonify, render_template, request

from bluetooth.connector import SonyBluetoothConnector
from protocol.commands import (
    build_anc_command_xm6,
    build_battery_inquiry,
    build_dsee_get,
    build_dsee_set,
    build_eq_preset,
    build_nc_asm_get,
    build_next,
    build_pause,
    build_play,
    build_prev,
    build_speak_to_chat_get,
    build_speak_to_chat_set,
    build_volume_get,
    build_volume_set,
)
from protocol.constants import ANC_MODE_NAMES, EQ_PRESET_NAMES, AncMode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

# --- Shared state ---
connector = SonyBluetoothConnector()
# Queue for scheduling BT operations from Flask thread → main thread
bt_queue: queue.Queue[tuple] = queue.Queue()

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Helper: schedule a BT operation on the main thread
# ---------------------------------------------------------------------------

def run_on_main(fn, *args, timeout=10.0):
    """Schedule a function to run on the main thread and wait for result.

    The main thread's run loop polls bt_queue and executes callables.
    """
    result_event = threading.Event()
    result_holder = [None, None]  # [result, exception]

    def wrapper():
        try:
            result_holder[0] = fn(*args)
        except Exception as exc:
            result_holder[1] = exc
        finally:
            result_event.set()

    bt_queue.put(wrapper)
    if result_event.wait(timeout=timeout):
        if result_holder[1]:
            raise result_holder[1]
        return result_holder[0]
    raise TimeoutError("Main-thread operation timed out")


def send_cmd(payload: bytes) -> bool:
    """Send a command via the main thread and return success."""
    resp = run_on_main(connector.send_command, payload)
    return resp is not None


def send_cmd_nowait(payload: bytes) -> bool:
    """Send a fire-and-forget command (no response expected)."""
    resp = run_on_main(connector.send_command, payload, 0.5)
    # For fire-and-forget, we consider it successful if the write didn't error
    return True


# ---------------------------------------------------------------------------
# Flask Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/devices", methods=["GET"])
def api_devices():
    """List available Sony headphones."""
    try:
        devices = run_on_main(connector.discover_sony_devices)
        return jsonify({"devices": devices})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/connect", methods=["POST"])
def api_connect():
    """Connect to a Sony headphone by address."""
    data = request.get_json(silent=True) or {}
    address = data.get("address")

    if not address:
        try:
            devices = run_on_main(connector.discover_sony_devices)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        if not devices:
            return jsonify({"error": "No Sony headphones found"}), 404
        address = devices[0]["address"]

    try:
        success = run_on_main(connector.connect, address, timeout=20.0)
        if success:
            # Request initial state — each goes through the main thread
            send_cmd(build_battery_inquiry())
            send_cmd(build_nc_asm_get())
            send_cmd(build_volume_get())
            send_cmd(build_dsee_get())
            send_cmd(build_speak_to_chat_get())
            return jsonify({"connected": True, "address": address})
        return jsonify({"error": "Connection failed"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/disconnect", methods=["POST"])
def api_disconnect():
    """Disconnect from the headphones."""
    try:
        run_on_main(connector.disconnect)
        return jsonify({"connected": False})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/status", methods=["GET"])
def api_status():
    """Get current headphone status."""
    return jsonify({
        "connected": connector.connected,
        "battery": connector.battery_level,
        "charging": connector.battery_charging,
        "anc_mode": connector.anc_mode,
        "volume": connector.volume_level,
        "dsee": connector.dsee_enabled,
        "speak_to_chat": connector.speak_to_chat_enabled,
    })


@app.route("/api/anc", methods=["POST"])
def api_anc():
    """Set ANC / Ambient Sound mode."""
    data = request.get_json(silent=True) or {}
    mode_name = data.get("mode", "off")
    level = int(data.get("level", 10))
    focus = bool(data.get("focus", False))

    mode = ANC_MODE_NAMES.get(mode_name)
    if mode is None:
        return jsonify({"error": f"Unknown mode: {mode_name}"}), 400

    payload = build_anc_command_xm6(mode, asm_level=level, focus_voice=focus)
    ok = send_cmd(payload)
    return jsonify({"ok": ok, "mode": mode_name})


@app.route("/api/eq", methods=["POST"])
def api_eq():
    """Set EQ preset."""
    data = request.get_json(silent=True) or {}
    preset_name = data.get("preset", "off")

    preset = EQ_PRESET_NAMES.get(preset_name)
    if preset is None:
        return jsonify({"error": f"Unknown preset: {preset_name}"}), 400

    payload = build_eq_preset(preset)
    ok = send_cmd(payload)
    return jsonify({"ok": ok, "preset": preset_name})


@app.route("/api/volume", methods=["POST"])
def api_volume():
    """Set volume level (0-30)."""
    data = request.get_json(silent=True) or {}
    level = int(data.get("level", 15))

    payload = build_volume_set(level)
    ok = send_cmd(payload)
    return jsonify({"ok": ok, "level": level})


@app.route("/api/dsee", methods=["POST"])
def api_dsee():
    """Enable/disable DSEE."""
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled", False))

    payload = build_dsee_set(enabled)
    ok = send_cmd(payload)
    return jsonify({"ok": ok, "enabled": enabled})


@app.route("/api/speak-to-chat", methods=["POST"])
def api_speak_to_chat():
    """Enable/disable Speak-to-Chat."""
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled", False))

    payload = build_speak_to_chat_set(enabled)
    ok = send_cmd(payload)
    return jsonify({"ok": ok, "enabled": enabled})


@app.route("/api/playback", methods=["POST"])
def api_playback():
    """Playback control via macOS media keys (AVRCP goes through the OS)."""
    import subprocess
    data = request.get_json(silent=True) or {}
    action = data.get("action", "play")

    # Use Spotify AppleScript API, fall back to generic media player
    scripts = {
        "play": 'tell application "Spotify" to play',
        "pause": 'tell application "Spotify" to pause',
        "next": 'tell application "Spotify" to next track',
        "prev": 'tell application "Spotify" to previous track',
    }
    script = scripts.get(action)
    if script is None:
        return jsonify({"error": f"Unknown action: {action}"}), 400

    try:
        subprocess.Popen(["osascript", "-e", script],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return jsonify({"ok": True, "action": action})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_flask():
    """Run Flask in a daemon thread."""
    app.run(host="127.0.0.1", port=5050, debug=False, use_reloader=False)


def main():
    """Main thread: start Flask in background, then run NSRunLoop.

    The NSRunLoop is required for IOBluetooth delegate callbacks.
    We also poll bt_queue to execute BT operations scheduled from Flask.
    """
    from Foundation import NSDate, NSRunLoop
    from CoreFoundation import CFRunLoopRunInMode, kCFRunLoopDefaultMode

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    log.info("Flask server started on http://127.0.0.1:5050")
    log.info("Open your browser to control the WH-1000XM6")

    # Main run loop: process IOBluetooth callbacks + our BT queue
    try:
        while True:
            # Run the NSRunLoop for a short interval to process BT callbacks
            CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.05, False)

            # Process any queued BT operations from Flask thread
            while not bt_queue.empty():
                try:
                    fn = bt_queue.get_nowait()
                    fn()
                except queue.Empty:
                    break
                except Exception:
                    log.exception("Error in queued BT operation")

    except KeyboardInterrupt:
        log.info("Shutting down...")
        if connector.connected:
            connector.disconnect()


if __name__ == "__main__":
    main()
