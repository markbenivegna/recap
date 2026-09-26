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

    # A page's own `parent` is almost never actually the workspace root —
    # the pages a user shares with the integration (e.g. "Meetings") are
    # typically themselves nested under other pages in their own private
    # structure, which the integration can't see at all. So "top-level"
    # here doesn't mean "parented directly by the workspace" — it means
    # "not a child of another page/database we can also see", i.e. not one
    # of the individual meeting pages this app already filed underneath a
    # page the user picked as a destination.
    visible_ids = {obj["id"] for obj in results}

    pages = []
    for obj in results:
        parent = obj.get("parent", {})
        parent_id = parent.get("page_id") or parent.get("database_id")
        if parent_id in visible_ids:
            continue
        pages.append(
            {
                "id": obj["id"],
                "type": obj["object"],  # "page" or "database"
                "title": _title_from_object(obj),
            }
        )
    return pages


_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
# Trailing colon tolerated ("**Action Items:**") - a natural enough thing for
# Claude to write that requiring an exact "**Action Items**" with nothing
# else on the line was silently missing real headings, in turn silently
# skipping the to_do conversion below entirely.
_HEADER_LINE_RE = re.compile(r"^\*\*(.+?)\*\*:?$")


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
    """Turn our Claude-generated markdown into real Notion blocks instead of
    flattening everything into plain paragraphs with literal asterisks.
    Section headers (**Text**, on their own line) become heading_3 blocks —
    Claude names these dynamically per meeting, except "Action Items" is
    always the special case: its bullets become checkable to_do blocks
    instead of plain bullets, since they're actionable, not just
    informational. A bullet indented two extra spaces under another bullet
    becomes a nested sub-bullet (a child of that parent block) rather than
    another flat top-level item."""
    blocks = []
    current_section = None
    last_top_bullet = None
    for raw_line in text.split("\n"):
        if not raw_line.strip():
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()

        header_match = _HEADER_LINE_RE.match(line)
        if header_match:
            current_section = header_match.group(1).strip().lower()
            last_top_bullet = None
            blocks.append(
                {
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {"rich_text": [{"type": "text", "text": {"content": header_match.group(1)}}]},
                }
            )
        elif line.startswith("- ") or line.startswith("* "):
            rich_text = _inline_rich_text(line[2:].strip()[:2000])
            # Substring, not exact equality - the prompt asks for exactly
            # "Action Items", but real output has drifted from that before
            # ("Action Items:", "Key Action Items", ...) and an exact match
            # silently falls back to plain, unchecked bullets with no sign
            # anything went wrong.
            if current_section and "action item" in current_section:
                blocks.append(
                    {
                        "object": "block",
                        "type": "to_do",
                        "to_do": {"rich_text": rich_text, "checked": False},
                    }
                )
                last_top_bullet = None
            elif indent >= 2 and last_top_bullet is not None:
                last_top_bullet["bulleted_list_item"].setdefault("children", []).append(
                    {
                        "object": "block",
                        "type": "bulleted_list_item",
                        "bulleted_list_item": {"rich_text": rich_text},
                    }
                )
            else:
                block = {
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": rich_text},
                }
                blocks.append(block)
                last_top_bullet = block
        else:
            blocks.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": _inline_rich_text(line[:2000])},
                }
            )
            last_top_bullet = None
    return blocks


_SPEAKER_TURN_RE = re.compile(r"^(Speaker \d+|You): (.*)$", re.DOTALL)


def _chunk_text(text, size=1900):
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


_BLOCK_CHAR_BUDGET = 1900


def _transcript_toggle(transcript):
    """A collapsed toggle block holding the full transcript, so an hour-plus
    meeting doesn't dominate the page — everyone sees Summary/Notes first
    and opens the transcript only if they need it. Falls back to blind
    chunking for plain, non-diarized transcripts (e.g. if diarization
    failed for that recording).

    Consecutive speaker turns are batched into a shared paragraph block,
    joined by a literal newline, instead of always giving every turn its
    own block — Notion renders visible spacing between separate blocks,
    so a transcript full of short, quick back-and-forth turns (a real
    conversation, not one person monologuing) turned into a long stack of
    loosely-spaced one-liners instead of reading like a normal transcript.
    A newline inside one block's rich text is a soft line break with much
    tighter spacing. Turns keep batching into the same block until adding
    another would cross Notion's per-block size budget, then a new block
    starts."""
    turns = transcript.split("\n\n") if "\n\n" in transcript else [transcript]

    block_pieces = []  # list of rich-text-piece lists, one per output block
    current = []
    current_len = 0

    def flush():
        nonlocal current, current_len
        if current:
            block_pieces.append(current)
        current = []
        current_len = 0

    for turn in turns:
        match = _SPEAKER_TURN_RE.match(turn)
        if not match:
            for piece in _chunk_text(turn):
                flush()
                block_pieces.append([{"type": "text", "text": {"content": piece}}])
            continue

        speaker, body = match.group(1), match.group(2)
        turn_len = len(speaker) + 2 + len(body)

        if turn_len > _BLOCK_CHAR_BUDGET:
            # Too long to ever share a block — flush whatever's pending
            # and give it its own dedicated, chunked block(s).
            flush()
            for i, piece in enumerate(_chunk_text(body)):
                rich_text = (
                    [{"type": "text", "text": {"content": f"{speaker}: "}, "annotations": {"bold": True}}]
                    if i == 0
                    else []
                ) + [{"type": "text", "text": {"content": piece}}]
                block_pieces.append(rich_text)
            continue

        if current and current_len + 1 + turn_len > _BLOCK_CHAR_BUDGET:
            flush()
        if current:
            current.append({"type": "text", "text": {"content": "\n"}})
            current_len += 1
        current.append({"type": "text", "text": {"content": f"{speaker}: "}, "annotations": {"bold": True}})
        current.append({"type": "text", "text": {"content": body}})
        current_len += turn_len

    flush()

    chunks = [
        {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text}}
        for rich_text in block_pieces
    ]

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
