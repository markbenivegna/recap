from Foundation import NSObject, NSUserNotification, NSUserNotificationCenter

# NSUserNotificationCenter only supports a single delegate at a time, so
# every notification this app delivers shares one delegate here, dispatching
# by a "kind" tag carried in the notification's own userInfo — rather than
# each feature (meeting detection, transcription-ready, ...) trying to
# install its own delegate and stepping on the others.
_action_handlers = {}


class _Delegate(NSObject):
    def userNotificationCenter_didActivateNotification_(self, center, notification):
        try:
            info = notification.userInfo() or {}
            handler = _action_handlers.get(info.get("kind"))
            if handler:
                handler()
        except Exception:
            pass
        try:
            center.removeDeliveredNotification_(notification)
        except Exception:
            pass


_delegate = _Delegate.alloc().init()


def register_action(kind, handler):
    """Run `handler()` when a notification delivered with deliver(kind=...)
    gets clicked (anywhere on it, not just a specific action button)."""
    _action_handlers[kind] = handler


def deliver(kind, title, informative_text, action_title=None):
    try:
        center = NSUserNotificationCenter.defaultUserNotificationCenter()
        center.setDelegate_(_delegate)
        note = NSUserNotification.alloc().init()
        note.setTitle_(title)
        note.setInformativeText_(informative_text)
        note.setUserInfo_({"kind": kind})
        if action_title:
            note.setHasActionButton_(True)
            note.setActionButtonTitle_(action_title)
        center.deliverNotification_(note)
    except Exception:
        pass
