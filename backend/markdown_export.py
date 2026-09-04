import re


def safe_filename(title):
    # Replace (not strip) characters invalid in macOS/Windows filenames —
    # titles always end with a "M/D/YYYY at H:MM AM/PM" timestamp, and
    # deleting the "/" and ":" outright would mangle it into
    # unreadable digit soup (e.g. "2:30 PM" -> "230 PM").
    cleaned = re.sub(r'[/\\:*?"<>|]', "-", title).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned or "Meeting Notes"


def build_markdown(title, summary, notes, transcript):
    parts = [f"# {title}", "", "## Summary", "", summary.strip(), "", "## Notes", "", notes.strip()]
    if transcript.strip():
        parts += ["", "## Transcript", "", transcript.strip()]
    return "\n".join(parts) + "\n"


def write_markdown(path, title, summary, notes, transcript):
    content = build_markdown(title, summary, notes, transcript)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path
