import json
import os

from backend.paths import WINDOW_STATE_FILE


def load():
    if os.path.exists(WINDOW_STATE_FILE):
        try:
            with open(WINDOW_STATE_FILE) as f:
                data = json.load(f)
            if all(k in data for k in ("x", "y", "width", "height")):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return None


def save(x, y, width, height):
    try:
        with open(WINDOW_STATE_FILE, "w") as f:
            json.dump({"x": x, "y": y, "width": width, "height": height}, f)
    except OSError:
        pass
