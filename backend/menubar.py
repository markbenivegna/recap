import os

from Foundation import NSObject

from backend.config import read_config

# Just the mic glyph — assets/mic-icon-source.svg is already a plain single-
# path silhouette, no separate rasterization step needed: NSImage loads SVG
# data natively (confirmed directly against this macOS/PyObjC install, not
# assumed from docs).
_ICON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "mic-icon-source.svg"
)

_status_item = None
_target = None
_window = None

# pywebview's window.hidden is only ever the *initial* constructor value —
# .hide()/.show() never update it, so it can't be trusted to reflect live
# state. Track it ourselves instead, and route every hide/show through here
# (both the status item's own click and main.py's window-closing veto) so
# there's exactly one source of truth for it.
_window_hidden = False


def _load_template_icon():
    from AppKit import NSImage
    from Foundation import NSData

    with open(_ICON_PATH, "rb") as f:
        svg_bytes = f.read()
    ns_data = NSData.dataWithBytes_length_(svg_bytes, len(svg_bytes))
    image = NSImage.alloc().initWithData_(ns_data)
    if image is None:
        return None
    # NSStatusBar's own standard glyph size — matches every other menu-bar
    # icon (Wi-Fi, battery, etc.), not the source SVG's own 100x125 canvas.
    image.setSize_((18, 18))
    # This is what makes macOS render/invert it automatically to match every
    # system menu-bar state (light, dark, highlighted) on its own, same as
    # every native menu-bar icon — no manual color/theme handling needed.
    image.setTemplate_(True)
    return image


# Defined once at module level, not inside _make_target() — PyObjC
# registers a real Objective-C class the first time a class body like this
# runs, and Objective-C class names must be globally unique per process.
# Redefining it on every _create() call (toggling the setting off then
# back on) raised "MenuBarTarget is overriding existing Objective-C class"
# on the second attempt — silently swallowed by _create()'s own
# try/except, so the icon just never came back. Confirmed directly: a
# second call to a function containing this same class body reliably
# raises that exact error.
class _MenuBarTarget(NSObject):
    def toggleWindow_(self, sender):
        toggle_window()


def _make_target():
    return _MenuBarTarget.alloc().init()


def is_window_focused():
    """Whether Recap's window is currently the frontmost, focused window —
    used to decide whether a background completion (e.g. a finished
    transcription) is worth a notification, or the user's already looking
    right at it. False whenever it's hidden (our own tracked state — see
    the note above on window.hidden not being trustworthy) or some other
    window/app is currently focused instead."""
    if _window_hidden or _window is None:
        return False
    try:
        return bool(_window.native.isKeyWindow())
    except Exception:
        return False


def hide_window():
    global _window_hidden
    if _window is None:
        return
    try:
        _window.hide()
        _window_hidden = True
    except Exception:
        pass


def show_window():
    global _window_hidden
    if _window is None:
        return
    try:
        _window.show()
        _window_hidden = False
    except Exception:
        pass


def toggle_window():
    if _window_hidden:
        show_window()
    else:
        hide_window()


def _create():
    global _status_item, _target
    try:
        from AppKit import NSStatusBar, NSVariableStatusItemLength

        icon = _load_template_icon()
        _target = _make_target()
        bar = NSStatusBar.systemStatusBar()
        _status_item = bar.statusItemWithLength_(NSVariableStatusItemLength)
        button = _status_item.button()
        if icon is not None:
            button.setImage_(icon)
        button.setTarget_(_target)
        button.setAction_("toggleWindow:")
    except Exception:
        _status_item = None
        _target = None


def _destroy():
    global _status_item, _target
    if _status_item is None:
        return
    try:
        from AppKit import NSStatusBar

        NSStatusBar.systemStatusBar().removeStatusItem_(_status_item)
    except Exception:
        pass
    _status_item = None
    _target = None


def sync(window=None):
    """Create/remove the status item to match the current
    SHOW_MENU_BAR_ICON setting. Safe to call any time — at launch (with the
    real `window`, which gets stored for later), or with no arguments live
    from a settings save — a no-op if already in the right state. Must run
    on the main thread (same AppKit constraint as any other NSWindow/
    NSStatusBar call in this app — see main.py's on_shown for the existing
    pattern of dispatching onto it via AppHelper.callAfter)."""
    global _window
    if window is not None:
        _window = window
    if _window is None:
        return

    enabled = read_config().get("SHOW_MENU_BAR_ICON", "") != "false"
    if enabled and _status_item is None:
        _create()
    elif not enabled and _status_item is not None:
        _destroy()


def is_enabled():
    return _status_item is not None
