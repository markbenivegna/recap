import os
import shutil
import subprocess


def _find_switch_bin():
    # GUI-launched apps (double-clicked from Finder) get a minimal PATH that
    # doesn't include Homebrew's bin dir, unlike an interactive shell — so
    # shutil.which() alone can miss it even though it's installed. Fall back
    # to Homebrew's known install locations (Apple Silicon and Intel).
    found = shutil.which("SwitchAudioSource")
    if found:
        return found
    for candidate in ("/opt/homebrew/bin/SwitchAudioSource", "/usr/local/bin/SwitchAudioSource"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


_SWITCH_BIN = _find_switch_bin()

# Server-side because this app is effectively single-session/single-window;
# remembers what the output device was before we switched it for recording.
_previous_output = None


def available():
    return _SWITCH_BIN is not None


def _run(*args):
    return subprocess.run([_SWITCH_BIN, *args], capture_output=True, text=True, timeout=5)


def get_current_output():
    result = _run("-c", "-t", "output")
    return result.stdout.strip() if result.returncode == 0 else None


def list_output_devices():
    result = _run("-a", "-t", "output")
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def set_output(device_name):
    result = _run("-s", device_name, "-t", "output")
    return result.returncode == 0


def prepare_for_recording(target_device_name):
    """Remember the current output device, then switch to the recording
    device if it's configured and actually exists. Returns True if it
    switched, False if it left things alone (not configured, tool missing,
    or the named device isn't currently available)."""
    global _previous_output

    if not available() or not target_device_name:
        return False

    devices = list_output_devices()
    if target_device_name not in devices:
        return False

    current = get_current_output()
    if current == target_device_name:
        # Already on it — nothing to restore later either.
        _previous_output = None
        return False

    _previous_output = current
    return set_output(target_device_name)


def restore_previous_output():
    """Switch back to whatever was active before prepare_for_recording()
    switched it. No-op if there's nothing remembered."""
    global _previous_output

    if not available() or not _previous_output:
        return False

    switched = set_output(_previous_output)
    _previous_output = None
    return switched
