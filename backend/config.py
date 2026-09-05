import os

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")

# (env var name, whether it's a secret that should be masked in the UI)
CONFIG_FIELDS = [
    ("ANTHROPIC_API_KEY", True),
    ("NOTION_API_KEY", True),
    ("WHISPER_MODEL_SIZE", False),
    ("VOCABULARY_HINTS", False),
    ("DIARIZATION_THRESHOLD", False),
    ("RECORDING_OUTPUT_DEVICE", False),
    ("SPEND_ALERT_THRESHOLD", False),
]


def read_config():
    return {key: os.environ.get(key, "") for key, _secret in CONFIG_FIELDS}


def write_config(updates):
    valid_keys = {key for key, _secret in CONFIG_FIELDS}
    updates = {k: v for k, v in updates.items() if k in valid_keys}

    lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r") as f:
            lines = f.readlines()

    seen = set()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            lines[i] = f"{key}={updates[key]}\n"
            seen.add(key)

    for key, value in updates.items():
        if key not in seen:
            lines.append(f"{key}={value}\n")

    with open(ENV_PATH, "w") as f:
        f.writelines(lines)

    for key, value in updates.items():
        os.environ[key] = value
