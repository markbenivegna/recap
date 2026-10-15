import json
import re
import urllib.request

LATEST_RELEASE_URL = "https://api.github.com/repos/markbenivegna/recap/releases/latest"
APP_BUNDLE_ID = "com.markbenivegna.meetingnotes"


def current_version():
    """The version baked into the packaged app's Info.plist, or None when
    running from source (python3 main.py, the dev server), where there is
    no real version to compare against and nothing to update."""
    try:
        from Foundation import NSBundle

        bundle = NSBundle.mainBundle()
        if bundle.bundleIdentifier() != APP_BUNDLE_ID:
            return None
        return bundle.objectForInfoDictionaryKey_("CFBundleShortVersionString")
    except Exception:
        return None


def _parse(version):
    match = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", version or "")
    return tuple(int(part) for part in match.groups()) if match else None


def check_for_update(running_version=None):
    """Compares the running version against the latest published GitHub
    release. Any failure (offline, rate limited, odd tag) just reports no
    update: this is a courtesy notice, never something that should surface
    an error."""
    running = running_version or current_version()
    result = {"update_available": False, "current": running}
    if not _parse(running):
        return result
    try:
        request = urllib.request.Request(LATEST_RELEASE_URL, headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(request, timeout=5) as response:
            release = json.load(response)
        latest = release.get("tag_name", "")
        if _parse(latest) and _parse(latest) > _parse(running):
            result.update(update_available=True, latest=latest.lstrip("v"), url=release.get("html_url", ""))
    except Exception:
        pass
    return result
