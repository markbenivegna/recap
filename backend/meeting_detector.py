import struct
import threading

import objc
import CoreAudio as CA
from Foundation import NSBundle, NSObject, NSUserNotification, NSUserNotificationCenter

from backend.config import read_config

# 2s latency before noticing a meeting started is imperceptible for this —
# nobody needs millisecond responsiveness for "someone joined a call" — and
# polling turned out dramatically simpler and lower-risk than the originally
# planned push-based AudioObjectAddPropertyListener callback: that needs a
# real C function pointer marshaled through PyObjC, historically one of the
# trickier things to get right there. A full poll (enumerate every audio
# process CoreAudio knows about + check each one) measured at ~30ms on this
# machine — negligible at a 2s interval.
POLL_INTERVAL_SECONDS = 2

_poll_timer = None
_own_bundle_id = None
_previously_running = set()
_window = None


def _own_bundle_identifier():
    global _own_bundle_id
    if _own_bundle_id is None:
        try:
            _own_bundle_id = NSBundle.mainBundle().bundleIdentifier() or ""
        except Exception:
            _own_bundle_id = ""
    return _own_bundle_id


def _get_property_bytes(object_id, selector):
    # b"" (not None) for the empty qualifier data below — confirmed
    # directly: None raises "TypeError: converting to a C array" even when
    # its paired size argument is 0, b"" doesn't.
    addr = CA.AudioObjectPropertyAddress(selector, CA.kAudioObjectPropertyScopeGlobal, CA.kAudioObjectPropertyElementMain)
    status, size = CA.AudioObjectGetPropertyDataSize(object_id, addr, 0, b"", None)
    if status != 0 or size == 0:
        return None
    buf = bytearray(size)
    status, _, data = CA.AudioObjectGetPropertyData(object_id, addr, 0, b"", size, buf)
    return bytes(data) if status == 0 else None


def _process_ids():
    raw = _get_property_bytes(CA.kAudioObjectSystemObject, CA.kAudioHardwarePropertyProcessObjectList)
    if not raw:
        return []
    count = len(raw) // 4
    return struct.unpack(f"{count}I", raw)


def _bundle_id_for(pid):
    raw = _get_property_bytes(pid, CA.kAudioProcessPropertyBundleID)
    if not raw or len(raw) != 8:
        return None
    ptr = struct.unpack("Q", raw)[0]
    if not ptr:
        return None
    try:
        # The property value is a CFStringRef — a plain pointer as far as
        # AudioObjectGetPropertyData is concerned, bridged back to a real
        # string via objc.objc_object (confirmed directly against real
        # process bundle IDs, e.g. "com.google.Chrome.helper").
        return str(objc.objc_object(c_void_p=ptr))
    except Exception:
        return None


def _is_running_input(pid):
    raw = _get_property_bytes(pid, CA.kAudioProcessPropertyIsRunningInput)
    return bool(struct.unpack("I", raw)[0]) if raw else False


def _click_record_button():
    try:
        # Reuse the exact same click path a real user's Record click takes
        # (respects the current recording state, so this can't accidentally
        # stop an already-running recording) rather than duplicating
        # startRecording()'s own guard logic here.
        _window.evaluate_js(
            "if (typeof recording !== 'undefined' && !recording) "
            "{ document.getElementById('recordBtn').click(); }"
        )
    except Exception:
        pass


class _NotificationDelegate(NSObject):
    def userNotificationCenter_didActivateNotification_(self, center, notification):
        try:
            if _window is not None:
                # NSUserNotificationCenterDelegate callbacks fire on the
                # main thread — confirmed the hard way, this caused a real
                # deadlock. window.evaluate_js() internally does its own
                # AppHelper.callAfter(...) to hop onto the main thread, then
                # blocks the *calling* thread on a semaphore waiting for
                # that scheduled call to run and release it. Called
                # directly from here (already on the main thread), the
                # semaphore-wait blocks the only thread that could ever run
                # the callAfter-scheduled call that would release it —
                # exactly the "spinning wheel, force quit" the user hit.
                # window.hide()/show() don't have this problem (fire-and-
                # forget callAfter, no wait) — only evaluate_js does, since
                # it's the only one built to return a value. Dispatching to
                # a plain background thread first sidesteps it entirely:
                # evaluate_js's blocking wait is safe from any thread that
                # isn't the one the callAfter callback itself needs to run
                # on.
                threading.Thread(target=_click_record_button, daemon=True).start()
        except Exception:
            pass
        try:
            center.removeDeliveredNotification_(notification)
        except Exception:
            pass


_delegate = _NotificationDelegate.alloc().init()


def _notify_meeting_detected():
    try:
        center = NSUserNotificationCenter.defaultUserNotificationCenter()
        center.setDelegate_(_delegate)
        note = NSUserNotification.alloc().init()
        note.setTitle_("Meeting detected")
        note.setInformativeText_("Another app just started using your microphone. Start recording in Recap?")
        note.setHasActionButton_(True)
        note.setActionButtonTitle_("Start Recording")
        center.deliverNotification_(note)
    except Exception:
        pass


def _check_once():
    global _previously_running
    own = _own_bundle_identifier()
    currently_running = set()
    for pid in _process_ids():
        if not _is_running_input(pid):
            continue
        bundle_id = _bundle_id_for(pid)
        # Recap's own recording shows up here too (WKWebView's getUserMedia
        # capture is attributed to the host app's own process, same as how
        # mic permission itself is tied to Recap's bundle identity) —
        # excluding our own bundle id is what keeps this from notifying
        # about a recording Recap itself just started.
        if not bundle_id or bundle_id == own:
            continue
        currently_running.add(bundle_id)

    newly_started = currently_running - _previously_running
    _previously_running = currently_running

    if newly_started:
        _notify_meeting_detected()


def _poll():
    global _poll_timer
    try:
        _check_once()
    except Exception:
        pass
    if read_config().get("DETECT_MEETINGS", "") != "false":
        _poll_timer = threading.Timer(POLL_INTERVAL_SECONDS, _poll)
        _poll_timer.daemon = True
        _poll_timer.start()
    else:
        _poll_timer = None


def sync(window=None):
    """Start/stop polling to match the current DETECT_MEETINGS setting.
    Safe to call any time — at launch (with the real `window`, stored so
    the notification's Start Recording action can reach it later), or with
    no arguments live from a settings save."""
    global _window, _poll_timer
    if window is not None:
        _window = window

    enabled = read_config().get("DETECT_MEETINGS", "") != "false"
    if enabled and _poll_timer is None:
        _poll()
    elif not enabled and _poll_timer is not None:
        _poll_timer.cancel()
        _poll_timer = None


def is_enabled():
    return _poll_timer is not None
