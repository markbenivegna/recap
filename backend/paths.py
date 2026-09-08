import os
import shutil

# The standard macOS location for a per-user app's own writable data. Works
# the same whether running from source (`python3 main.py`) or from a real
# packaged Recap.app — a frozen bundle's own Contents/Resources is
# effectively read-only distributed code, not somewhere to write .env, cache
# the downloaded diarization model, or track usage, and it'd get wiped out
# on every app update anyway.
APP_SUPPORT_DIR = os.path.join(os.path.expanduser("~/Library/Application Support"), "Recap")

ENV_PATH = os.path.join(APP_SUPPORT_DIR, ".env")
CACHE_DIR = os.path.join(APP_SUPPORT_DIR, ".cache")
USAGE_FILE = os.path.join(APP_SUPPORT_DIR, ".usage.json")
RECORDINGS_DIR = os.path.join(APP_SUPPORT_DIR, "recordings")
WINDOW_STATE_FILE = os.path.join(APP_SUPPORT_DIR, "window_state.json")

# Where these used to live — every existing install (every copy of Recap
# has run from source so far) has real user data sitting here: API keys in
# .env, and the downloaded diarization model in .cache/ (a few hundred MB,
# not something to make anyone re-download just because of where the file
# happens to live now).
_OLD_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OLD_ENV_PATH = os.path.join(_OLD_PROJECT_DIR, ".env")
_OLD_CACHE_DIR = os.path.join(_OLD_PROJECT_DIR, ".cache")
_OLD_USAGE_FILE = os.path.join(_OLD_PROJECT_DIR, ".usage.json")


def _migrate_if_needed():
    os.makedirs(APP_SUPPORT_DIR, exist_ok=True)
    if os.path.exists(_OLD_ENV_PATH) and not os.path.exists(ENV_PATH):
        shutil.copy2(_OLD_ENV_PATH, ENV_PATH)
    if os.path.isdir(_OLD_CACHE_DIR) and not os.path.exists(CACHE_DIR):
        shutil.copytree(_OLD_CACHE_DIR, CACHE_DIR)
    if os.path.exists(_OLD_USAGE_FILE) and not os.path.exists(USAGE_FILE):
        shutil.copy2(_OLD_USAGE_FILE, USAGE_FILE)


_migrate_if_needed()
os.makedirs(RECORDINGS_DIR, exist_ok=True)
