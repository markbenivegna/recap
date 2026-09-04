import os

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


def _text_blocks(text):
    blocks = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("- ") or line.startswith("* "):
            blocks.append(
                {
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [{"type": "text", "text": {"content": line[2:].strip()}}]
                    },
                }
            )
        else:
            blocks.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": line[:2000]}}]},
                }
            )
    return blocks


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
    children.extend(_text_blocks(summary))
    children.append(_heading("Notes"))
    children.extend(_text_blocks(notes))
    children.append(_heading("Transcript"))
    # Notion caps rich_text content at 2000 chars per block; chunk long transcripts.
    for i in range(0, len(transcript), 1900):
        chunk = transcript[i : i + 1900]
        children.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]},
            }
        )

    # Notion allows at most 100 children per create-page call; trim if needed.
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
