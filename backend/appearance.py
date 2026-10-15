from backend.config import read_config

_window = None


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


def sync(window=None):
    """Apply the APPEARANCE setting (system / light / dark). Overriding the
    app's NSAppearance is all it takes: the web view's own
    prefers-color-scheme follows it, so the stylesheet needs no changes,
    and so do native pieces like confirm dialogs. Passing nil goes back to
    following macOS. Same calling convention as menubar.sync: pass the real
    window at launch, nothing on a live settings save, and run it on the
    main thread."""
    global _window
    if window is not None:
        _window = window
    if _window is None:
        return

    try:
        from AppKit import NSAppearance, NSAppearanceNameAqua, NSAppearanceNameDarkAqua, NSApplication

        choice = read_config().get("APPEARANCE", "")
        name = {"light": NSAppearanceNameAqua, "dark": NSAppearanceNameDarkAqua}.get(choice)
        NSApplication.sharedApplication().setAppearance_(NSAppearance.appearanceNamed_(name) if name else None)
    except Exception:
        pass
    sync_titlebar_color(_window)
