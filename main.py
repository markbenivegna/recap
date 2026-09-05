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


def hide_titlebar_text(window):
    # Keep the native close/minimize/zoom buttons but remove the title
    # string and the visually distinct bar behind them, so the window
    # reads as a single continuous surface instead of "content below a
    # chrome bar" — same look as Notes/most modern Mac apps. Deliberately
    # NOT using pywebview's own frameless=True: that also hides the
    # traffic-light buttons themselves, which we want to keep.
    try:
        from AppKit import NSColor

        native = window.native
        native.setTitlebarAppearsTransparent_(True)
        native.setTitleVisibility_(1)  # NSWindowTitleHidden

        # pywebview's own Cocoa backend (platforms/cocoa.py) always paints
        # this specific titlebar subview with a static
        # NSColor.windowBackgroundColor() — "so it does not change with
        # the window color" per its own comment. Normally invisible
        # because the OS draws its own dynamic chrome on top; once the
        # titlebar is transparent that static paint is what actually
        # shows, permanently, with none of the usual active/inactive
        # dimming. Clear it so our own content shows through instead.
        native.contentView().superview().subviews().lastObject().setBackgroundColor_(NSColor.clearColor())

        # The window itself is created with a hardcoded white background
        # (pywebview's background_color, default '#FFFFFF' either way).
        # That's invisible in light mode, but in dark mode it's what was
        # showing through as a stray white bar up top — our own dark CSS
        # only covers the WKWebView's content area, not the native window
        # behind/around it.
        #
        # windowBackgroundColor looked like the obvious fix but isn't an
        # exact match for our page background in either mode (it's a
        # slightly-off system gray, not true #fff/#000), so the seam just
        # came back in a different color. Match our CSS exactly instead —
        # it's pure black/white on both sides, so plain black/white works.
        from AppKit import NSAppearanceNameAqua, NSAppearanceNameDarkAqua

        best_match = native.effectiveAppearance().bestMatchFromAppearancesWithNames_(
            [NSAppearanceNameAqua, NSAppearanceNameDarkAqua]
        )
        is_dark = best_match == NSAppearanceNameDarkAqua
        print(
            f"[titlebar-debug] window.effectiveAppearance().name() = {native.effectiveAppearance().name()!r}, "
            f"NSApp.effectiveAppearance().name() = {__import__('AppKit').NSApplication.sharedApplication().effectiveAppearance().name()!r}, "
            f"best_match = {best_match!r}, is_dark = {is_dark}",
            flush=True,
        )
        native.setBackgroundColor_(NSColor.blackColor() if is_dark else NSColor.whiteColor())
    except Exception:
        pass


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

    window = webview.create_window(
        APP_NAME, f"http://{HOST}:{port}", width=850, height=600, min_size=(700, 500), background_color="#FFFFFF"
    )

    def on_shown():
        # events.shown fires on a background thread, but AppKit requires
        # any NSWindow changes to happen on the main thread (confirmed by
        # an NSInternalInconsistencyException when called directly here).
        from PyObjCTools import AppHelper

        AppHelper.callAfter(hide_titlebar_text, window)

    window.events.shown += on_shown
    apply_mac_dock_branding()
    webview.start()
