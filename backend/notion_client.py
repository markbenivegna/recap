import os
import re

import requests

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def _headers():
    api_key = os.environ.get("NOTION_API_KEY")
    if not api_key:
        raise RuntimeError("NOTION_API_KEY is not set")
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _title_from_object(obj):
    props = obj.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            title_parts = prop.get("title", [])
            text = "".join(part.get("plain_text", "") for part in title_parts)
            if text:
                return text
    # Databases keep their title outside "properties"
    if obj.get("title"):
        return "".join(part.get("plain_text", "") for part in obj["title"])
    return "Untitled"


def list_pages():
    resp = requests.post(
        f"{NOTION_API_BASE}/search",
        headers=_headers(),
        json={
            "filter": {"property": "object", "value": "page"},
            "sort": {"direction": "descending", "timestamp": "last_edited_time"},
            "page_size": 100,
        },
        timeout=15,
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])

    pages = []
    for obj in results:
        pages.append(
            {
                "id": obj["id"],
                "type": obj["object"],  # "page" or "database"
                "title": _title_from_object(obj),
            }
        )
    return pages


_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_HEADER_LINE_RE = re.compile(r"^\*\*(.+)\*\*$")


def _inline_rich_text(text):
    """Split a line on **bold** spans into Notion rich_text objects."""
    parts = []
    last_end = 0
    for match in _BOLD_RE.finditer(text):
        if match.start() > last_end:
            parts.append({"type": "text", "text": {"content": text[last_end:match.start()]}})
        parts.append(
            {
                "type": "text",
                "text": {"content": match.group(1)},
                "annotations": {"bold": True},
            }
        )
        last_end = match.end()
    if last_end < len(text):
        parts.append({"type": "text", "text": {"content": text[last_end:]}})
    return parts or [{"type": "text", "text": {"content": text}}]


def _markdown_to_blocks(text):
    """Turn our Claude-generated markdown (headers as **Text**, "- " bullets,
    plain paragraphs) into real Notion blocks instead of flattening
    everything into plain paragraphs with literal asterisks. Bullets under
    an "Action Items" header become checkable to_do blocks instead of plain
    bullets, since they're actionable rather than just informational."""
    blocks = []
    current_section = None
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue

        header_match = _HEADER_LINE_RE.match(line)
        if header_match:
            current_section = header_match.group(1).strip().lower()
            blocks.append(
                {
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {"rich_text": [{"type": "text", "text": {"content": header_match.group(1)}}]},
                }
            )
        elif line.startswith("- ") or line.startswith("* "):
            rich_text = _inline_rich_text(line[2:].strip()[:2000])
            if current_section == "action items":
                blocks.append(
                    {
                        "object": "block",
                        "type": "to_do",
                        "to_do": {"rich_text": rich_text, "checked": False},
                    }
                )
            else:
                blocks.append(
                    {
                        "object": "block",
                        "type": "bulleted_list_item",
                        "bulleted_list_item": {"rich_text": rich_text},
                    }
                )
        else:
            blocks.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": _inline_rich_text(line[:2000])},
                }
            )
    return blocks


_SPEAKER_TURN_RE = re.compile(r"^(Speaker \d+): (.*)$", re.DOTALL)


def _chunk_text(text, size=1900):
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


def _transcript_toggle(transcript):
    """A collapsed toggle block holding the full transcript, so an hour-plus
    meeting doesn't dominate the page — everyone sees Summary/Notes first
    and opens the transcript only if they need it. Each speaker turn (from
    format_transcript_with_speakers) becomes its own paragraph with the
    speaker label bolded; falls back to blind chunking for plain,
    non-diarized transcripts (e.g. if diarization failed for that recording)."""
    turns = transcript.split("\n\n") if "\n\n" in transcript else [transcript]

    chunks = []
    for turn in turns:
        match = _SPEAKER_TURN_RE.match(turn)
        if match:
            speaker, body = match.group(1), match.group(2)
            for i, piece in enumerate(_chunk_text(body)):
                rich_text = (
                    [{"type": "text", "text": {"content": f"{speaker}: "}, "annotations": {"bold": True}}]
                    if i == 0
                    else []
                ) + [{"type": "text", "text": {"content": piece}}]
                chunks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text}})
        else:
            for piece in _chunk_text(turn):
                chunks.append(
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": [{"type": "text", "text": {"content": piece}}]},
                    }
                )

    # Notion allows at most 100 children per block; trim if a transcript is extreme.
    chunks = chunks[:100]

    return {
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [{"type": "text", "text": {"content": "Click to expand"}}],
            "children": chunks,
        },
    }


def _heading(text):
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def _title_property_key(database_id):
    resp = requests.get(f"{NOTION_API_BASE}/databases/{database_id}", headers=_headers(), timeout=15)
    resp.raise_for_status()
    for name, prop in resp.json().get("properties", {}).items():
        if prop.get("type") == "title":
            return name
    return "Name"


def create_meeting_page(parent_id, parent_type, title, summary, notes, transcript):
    parent = {"database_id": parent_id} if parent_type == "database" else {"page_id": parent_id}

    title_key = _title_property_key(parent_id) if parent_type == "database" else "title"
    properties = {title_key: {"title": [{"type": "text", "text": {"content": title}}]}}

    children = []
    children.append(_heading("Summary"))
    children.extend(_markdown_to_blocks(summary))
    children.append(_heading("Notes"))
    children.extend(_markdown_to_blocks(notes))
    children.append(_heading("Transcript"))
    children.append(_transcript_toggle(transcript))

    # Notion allows at most 100 top-level children per create-page call;
    # trim if needed (the transcript itself doesn't count against this since
    # its chunks live nested inside the single toggle block above).
    if len(children) > 100:
        children = children[:100]

    resp = requests.post(
        f"{NOTION_API_BASE}/pages",
        headers=_headers(),
        json={"parent": parent, "properties": properties, "children": children},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return {"id": data["id"], "url": data.get("url")}
