import os
import socket
import threading

import webview

from backend.app import app

HOST = "127.0.0.1"
PREFERRED_PORT = 51823
APP_NAME = "Recap"
ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.png")


def find_port():
    # Prefer a fixed port so the app's origin (http://127.0.0.1:<port>) stays
    # the same across launches — WKWebView caches microphone permission per
    # origin, so a different port each time means it can never remember a
    # prior "allow" and re-prompts every launch. Only fall back to a random
    # free port if the preferred one is genuinely stuck (e.g. a leftover
    # process from a crash still holding it).
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((HOST, PREFERRED_PORT))
            return s.getsockname()[1]
        except OSError:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def run_flask(port):
    app.run(host=HOST, port=port, debug=False, use_reloader=False, threaded=True)


def apply_mac_dock_branding():
    # We launch via the system's Python.app framework binary rather than a
    # compiled app bundle of our own, so macOS otherwise shows the Dock
    # icon/name for "Python" instead of this app. Override both at runtime.
    try:
        from AppKit import NSApplication, NSImage
        from Foundation import NSBundle

        icon = NSImage.alloc().initWithContentsOfFile_(ICON_PATH)
        if icon is not None:
            NSApplication.sharedApplication().setApplicationIconImage_(icon)

        bundle = NSBundle.mainBundle()
        info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
        if info is not None:
            info["CFBundleName"] = APP_NAME
    except Exception:
        pass


if __name__ == "__main__":
    port = find_port()
    flask_thread = threading.Thread(target=run_flask, args=(port,), daemon=True)
    flask_thread.start()

    webview.create_window(APP_NAME, f"http://{HOST}:{port}", width=850, height=600, min_size=(700, 500))
    apply_mac_dock_branding()
    webview.start()
