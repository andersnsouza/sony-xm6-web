"""Sony WH-1000XM6 Web Controller — Entry Point.

Architecture:
    Main thread  → NSStatusBar menu + IOBluetooth + NSRunLoop
    Daemon thread → Flask HTTP server

ALL Bluetooth operations (connect, disconnect, send_command) must run on
the main thread. Flask routes and menu callbacks schedule them via
run_on_main() / bt_queue.
"""

import logging
import os
import queue
import threading
import webbrowser

import objc
from AppKit import (
    NSApplication,
    NSImage,
    NSMenu,
    NSMenuItem,
    NSObject,
    NSStatusBar,
    NSVariableStatusItemLength,
)

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
        "play": 'tell application "Spotify" to playpause',
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
# Flask server
# ---------------------------------------------------------------------------

def run_flask():
    """Run Flask in a daemon thread."""
    app.run(host="127.0.0.1", port=5050, debug=False, use_reloader=False)


# ---------------------------------------------------------------------------
# macOS Menu Bar (NSStatusBar)
# ---------------------------------------------------------------------------

_quit_requested = False
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _resource_path(filename):
    """Locate a resource file (works as script and inside .app bundle)."""
    for d in [os.path.join(_BASE_DIR, "resources"), _BASE_DIR]:
        p = os.path.join(d, filename)
        if os.path.exists(p):
            return p
    return None


class MenuBarDelegate(NSObject):
    """Handles NSStatusBar menu item callbacks."""

    def openWebUI_(self, sender):
        webbrowser.open("http://localhost:5050")

    def toggleConnection_(self, sender):
        if connector.connected:
            bt_queue.put(lambda: connector.disconnect())
        else:
            def _connect():
                devices = connector.discover_sony_devices()
                if devices:
                    if connector.connect(devices[0]["address"]):
                        connector.send_command(build_battery_inquiry())
                        connector.send_command(build_nc_asm_get())
                        connector.send_command(build_volume_get())
                        connector.send_command(build_dsee_get())
                        connector.send_command(build_speak_to_chat_get())
            bt_queue.put(_connect)

    def ancOff_(self, sender):
        try:
            log.info("Menu: ANC Off")
            payload = build_anc_command_xm6(AncMode.OFF)
            bt_queue.put(lambda: connector.send_command(payload))
        except Exception:
            log.exception("ancOff_ failed")

    def ancNc_(self, sender):
        try:
            log.info("Menu: Noise Cancelling")
            payload = build_anc_command_xm6(AncMode.NOISE_CANCELLING)
            bt_queue.put(lambda: connector.send_command(payload))
        except Exception:
            log.exception("ancNc_ failed")

    def ancAmbient_(self, sender):
        try:
            log.info("Menu: Ambient Sound")
            payload = build_anc_command_xm6(AncMode.AMBIENT_SOUND)
            bt_queue.put(lambda: connector.send_command(payload))
        except Exception:
            log.exception("ancAmbient_ failed")

    def playPrev_(self, sender):
        import subprocess
        subprocess.Popen(["osascript", "-e", 'tell application "Spotify" to previous track'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def playPause_(self, sender):
        import subprocess
        subprocess.Popen(["osascript", "-e", 'tell application "Spotify" to playpause'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def playNext_(self, sender):
        import subprocess
        subprocess.Popen(["osascript", "-e", 'tell application "Spotify" to next track'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def quitApp_(self, sender):
        global _quit_requested
        _quit_requested = True

    @objc.python_method
    def update_status(self, status_line, connect_item):
        """Refresh the menu bar status text."""
        if connector.connected:
            bat = connector.battery_level
            mode = (
                connector.anc_mode.upper()
                if connector.anc_mode != "unknown"
                else "-"
            )
            chrg = " chrg" if connector.battery_charging else ""
            status_line.setTitle_(f"Battery: {bat}%{chrg} | {mode}")
            connect_item.setTitle_("Disconnect")
        else:
            status_line.setTitle_("Not connected")
            connect_item.setTitle_("Connect")


def setup_menu_bar():
    """Initialize NSApplication and create the menu bar status item.

    Returns (delegate, status_line_item, connect_item).
    """
    ns_app = NSApplication.sharedApplication()
    ns_app.setActivationPolicy_(1)  # NSApplicationActivationPolicyAccessory

    delegate = MenuBarDelegate.alloc().init()

    status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(
        NSVariableStatusItemLength
    )

    # Try to load template icon; fall back to text
    icon_path = _resource_path("icon.png")
    if icon_path:
        icon = NSImage.alloc().initWithContentsOfFile_(icon_path)
        icon.setTemplate_(True)
        icon.setSize_((22, 22))
        status_item.button().setImage_(icon)
    else:
        status_item.button().setTitle_("XM6")

    # -- Dropdown menu --
    menu = NSMenu.alloc().init()

    status_line = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Not connected", None, ""
    )
    status_line.setEnabled_(False)
    menu.addItem_(status_line)
    menu.addItem_(NSMenuItem.separatorItem())

    # -- ANC / Ambient controls --
    anc_off_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "ANC Off", "ancOff:", ""
    )
    anc_off_item.setTarget_(delegate)
    menu.addItem_(anc_off_item)

    anc_nc_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Noise Cancelling", "ancNc:", ""
    )
    anc_nc_item.setTarget_(delegate)
    menu.addItem_(anc_nc_item)

    anc_ambient_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Ambient Sound", "ancAmbient:", ""
    )
    anc_ambient_item.setTarget_(delegate)
    menu.addItem_(anc_ambient_item)
    menu.addItem_(NSMenuItem.separatorItem())

    # -- Playback controls --
    prev_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "⏮ Previous", "playPrev:", ""
    )
    prev_item.setTarget_(delegate)
    menu.addItem_(prev_item)

    playpause_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "⏯ Play / Pause", "playPause:", ""
    )
    playpause_item.setTarget_(delegate)
    menu.addItem_(playpause_item)

    next_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "⏭ Next", "playNext:", ""
    )
    next_item.setTarget_(delegate)
    menu.addItem_(next_item)
    menu.addItem_(NSMenuItem.separatorItem())

    open_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Open Web UI", "openWebUI:", ""
    )
    open_item.setTarget_(delegate)
    menu.addItem_(open_item)
    menu.addItem_(NSMenuItem.separatorItem())

    connect_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Connect", "toggleConnection:", ""
    )
    connect_item.setTarget_(delegate)
    menu.addItem_(connect_item)
    menu.addItem_(NSMenuItem.separatorItem())

    quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Quit", "quitApp:", "q"
    )
    quit_item.setTarget_(delegate)
    menu.addItem_(quit_item)

    status_item.setMenu_(menu)

    return delegate, status_line, connect_item


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    """Main thread: menu bar + Flask server + event loop.

    Uses NSApplication.nextEventMatchingMask… + sendEvent_ to pump both
    AppKit events (menu clicks) and run-loop sources (IOBluetooth
    callbacks) in a single loop.
    """
    from Foundation import NSDate, NSDefaultRunLoopMode

    # Menu bar icon
    delegate, status_line, connect_item = setup_menu_bar()
    ns_app = NSApplication.sharedApplication()
    log.info("Menu bar icon ready")

    # Flask web server (daemon thread)
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    log.info("Flask server started on http://127.0.0.1:5050")

    log.info("Web UI available at http://localhost:5050")

    tick = 0
    NSAnyEventMask = 0xFFFFFFFF

    try:
        while not _quit_requested:
            # Pump AppKit events (menus, clicks) — also runs the
            # CFRunLoop internally, which processes IOBluetooth callbacks.
            event = ns_app.nextEventMatchingMask_untilDate_inMode_dequeue_(
                NSAnyEventMask,
                NSDate.dateWithTimeIntervalSinceNow_(0.05),
                NSDefaultRunLoopMode,
                True,
            )
            if event is not None:
                ns_app.sendEvent_(event)

            # Execute queued BT operations from Flask / menu bar
            while not bt_queue.empty():
                try:
                    fn = bt_queue.get_nowait()
                    fn()
                except queue.Empty:
                    break
                except Exception:
                    log.exception("Error in queued BT operation")

            # Update menu bar status (~once per second)
            tick += 1
            if tick % 20 == 0:
                delegate.update_status(status_line, connect_item)

    except KeyboardInterrupt:
        log.info("Shutting down...")

    # Cleanup
    if connector.connected:
        connector.disconnect()
    log.info("Goodbye.")


if __name__ == "__main__":
    main()
