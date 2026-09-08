import os

APP_NAME = "Recap"
ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.png")


def apply_mac_dock_branding():
    # Recap.app (Contents/Info.plist) now declares a real CFBundleIconFile
    # (AppIcon.icns) — when launched as that bundle, macOS's own Launch
    # Services already shows the correct icon immediately, no code needed,
    # exactly like any normal app. This manual override predates that and
    # is only still needed as a fallback for running `python3 main.py`
    # directly (no real bundle, so it'd otherwise show Python's own icon).
    # Applying it anyway on top of an already-correct native bundle icon
    # forces a visible re-render with a differently-sized raw PNG — that
    # redundant repaint is what looked like the icon "growing"/scaling.
    try:
        from Foundation import NSBundle

        bundle = NSBundle.mainBundle()
        if bundle.objectForInfoDictionaryKey_("CFBundleIconFile") == "AppIcon":
            return  # Real bundle icon already showing correctly — nothing to do.

        from AppKit import NSApplication, NSImage

        icon = NSImage.alloc().initWithContentsOfFile_(ICON_PATH)
        if icon is not None:
            NSApplication.sharedApplication().setApplicationIconImage_(icon)

        info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
        if info is not None:
            info["CFBundleName"] = APP_NAME
    except Exception:
        pass


# Called here, before the slow `from backend.app import app` import below
# (which pulls in torch/speechbrain and takes several seconds) rather than
# after window creation, purely for the python3-main.py-direct fallback
# case above — no effect on a real Recap.app launch, which now no-ops out
# of this function immediately.
apply_mac_dock_branding()

import socket  # noqa: E402
import threading  # noqa: E402

import webview  # noqa: E402

from backend import menubar, window_state  # noqa: E402
from backend.app import app  # noqa: E402

HOST = "127.0.0.1"
PREFERRED_PORT = 51823


def patch_media_capture_permission():
    # pywebview's own WKUIDelegate (BrowserView.BrowserDelegate) doesn't
    # implement requestMediaCapturePermissionForOrigin — the WKWebView API
    # (macOS 12+) apps use to cache a mic-access decision themselves.
    # Without it, WebKit falls back to its own default: showing its own
    # permission popup on every single getUserMedia() call in a fresh
    # page load, i.e. every app launch, regardless of the one-time macOS
    # System Settings permission already granted via TCC. This is a
    # documented WKWebView limitation (confirmed via WebKit/Apple docs),
    # not something specific to this app.
    #
    # Subclassing BrowserDelegate (rather than patching a method onto the
    # already-realized instance/class pywebview creates internally) so
    # the new selector registers through PyObjC's normal class-creation
    # path — deliberately avoiding the approach that crashed twice before
    # in this project. Swapping the class reference on BrowserView before
    # create_window()/start() run means pywebview's own
    # `BrowserView.BrowserDelegate.alloc().init()` call picks up this
    # subclass instead, with no changes needed to pywebview itself.
    try:
        from webview.platforms.cocoa import BrowserView
        from WebKit import WKPermissionDecisionGrant

        class PermissiveBrowserDelegate(BrowserView.BrowserDelegate):
            def webView_requestMediaCapturePermissionForOrigin_initiatedByFrame_type_decisionHandler_(
                self, webview_, origin, frame, media_type, decision_handler
            ):
                # Our real gate is the one-time System Settings mic
                # permission (already tied to this app's own bundle
                # identity). Grant automatically instead of showing
                # WebKit's own redundant, non-persistent popup on top of
                # that every launch.
                if not decision_handler.__block_signature__:
                    decision_handler.__block_signature__ = BrowserView.pyobjc_method_signature(b'v@q')
                decision_handler(WKPermissionDecisionGrant)

        BrowserView.BrowserDelegate = PermissiveBrowserDelegate
    except Exception:
        pass


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


def sync_titlebar_color(window):
    # Match the native window's background exactly to our page background
    # (plain black/white, not windowBackgroundColor() — that's a
    # slightly-off system gray in each mode, not a true match, so a seam
    # reappears in a different shade if used here). Re-run any time the
    # appearance actually changes, not just once at launch — macOS's
    # "Automatic" appearance setting switches light/dark on its own
    # schedule while the app may already be running.
    try:
        from AppKit import NSAppearanceNameAqua, NSAppearanceNameDarkAqua, NSColor

        native = window.native
        best_match = native.effectiveAppearance().bestMatchFromAppearancesWithNames_(
            [NSAppearanceNameAqua, NSAppearanceNameDarkAqua]
        )
        is_dark = best_match == NSAppearanceNameDarkAqua
        native.setBackgroundColor_(NSColor.blackColor() if is_dark else NSColor.whiteColor())
    except Exception:
        pass


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
    except Exception:
        pass

    sync_titlebar_color(window)


def watch_appearance_changes(window):
    # AppleInterfaceThemeChangedNotification fires whenever the effective
    # appearance actually changes — a manual toggle, or macOS's own
    # "Automatic" schedule flipping it while the app is already running.
    try:
        from Foundation import NSDistributedNotificationCenter, NSOperationQueue
        from PyObjCTools import AppHelper

        def on_change(_notification):
            AppHelper.callAfter(sync_titlebar_color, window)

        NSDistributedNotificationCenter.defaultCenter().addObserverForName_object_queue_usingBlock_(
            "AppleInterfaceThemeChangedNotification", None, NSOperationQueue.mainQueue(), on_change
        )
    except Exception:
        pass


if __name__ == "__main__":
    port = find_port()
    flask_thread = threading.Thread(target=run_flask, args=(port,), daemon=True)
    flask_thread.start()

    patch_media_capture_permission()

    # Restore the last position/size, but only if it's still within some
    # currently-connected screen's bounds — a saved position from a monitor
    # that's since been unplugged (a laptop undocked, an external display
    # disconnected) would otherwise put the window somewhere unreachable.
    # Falls back to today's default (centered, 850x600) whenever there's no
    # saved state, or it's off-screen.
    create_kwargs = {"width": 850, "height": 600, "min_size": (700, 500), "background_color": "#FFFFFF"}
    saved_state = window_state.load()
    if saved_state:
        try:
            x, y = saved_state["x"], saved_state["y"]
            on_screen = any(
                s.frame.origin.x <= x < s.frame.origin.x + s.frame.size.width
                and s.frame.origin.y <= y < s.frame.origin.y + s.frame.size.height
                for s in webview.screens
            )
            if on_screen:
                create_kwargs.update(x=x, y=y, width=saved_state["width"], height=saved_state["height"])
        except Exception:
            pass

    window = webview.create_window(APP_NAME, f"http://{HOST}:{port}", **create_kwargs)

    _save_state_timer = None

    def _save_window_state():
        try:
            window_state.save(window.x, window.y, window.width, window.height)
        except Exception:
            pass

    def schedule_save_window_state():
        # events.moved/resized fire repeatedly during a drag — debounce so
        # this only actually writes once things settle, not on every
        # intermediate frame.
        global _save_state_timer
        if _save_state_timer is not None:
            _save_state_timer.cancel()
        _save_state_timer = threading.Timer(0.5, _save_window_state)
        _save_state_timer.daemon = True
        _save_state_timer.start()

    def on_shown():
        # events.shown fires on a background thread, but AppKit requires
        # any NSWindow changes to happen on the main thread (confirmed by
        # an NSInternalInconsistencyException when called directly here).
        from PyObjCTools import AppHelper

        AppHelper.callAfter(hide_titlebar_text, window)
        AppHelper.callAfter(watch_appearance_changes, window)
        AppHelper.callAfter(menubar.sync, window)

    def on_closing():
        # Only hide-instead-of-quit when the menu bar icon is actually
        # showing — otherwise there'd be no way to get the window back, and
        # closing should behave exactly like it always has. Unlike
        # events.shown above, this fires synchronously from an AppKit
        # delegate callback already on the main thread (confirmed via
        # pywebview's own cocoa.py: windowShouldClose_ -> should_close(),
        # both plain calls, no thread hop) — no callAfter needed here.
        # Returning False vetoes the close (see pywebview's Event.set():
        # any handler returning False makes should_close() return NO).
        if menubar.is_enabled():
            menubar.hide_window()
            return False

    window.events.shown += on_shown
    window.events.closing += on_closing
    window.events.moved += schedule_save_window_state
    window.events.resized += schedule_save_window_state
    webview.start()
