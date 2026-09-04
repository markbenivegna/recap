import os

import anthropic

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

SYSTEM_PROMPT = """You turn raw meeting transcripts into two things:

1. A concise summary — a few sentences describing what the meeting was about and the outcome.
2. Structured notes — bullet points grouped under "Key Points", "Decisions", and "Action Items" \
(use only the headings that apply; skip a heading if there's nothing for it).

Respond with exactly this format, no preamble:

SUMMARY:
<summary text>

NOTES:
<notes text, markdown bullet points>
"""


def _client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic(api_key=api_key)


def summarize_transcript(transcript_text):
    if not transcript_text or not transcript_text.strip():
        raise ValueError("Transcript is empty")

    client = _client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Transcript:\n\n{transcript_text}"}],
    )

    raw = "".join(block.text for block in message.content if block.type == "text")
    return _parse_response(raw)


def _parse_response(raw):
    summary = ""
    notes = ""

    notes_idx = raw.find("NOTES:")
    if notes_idx == -1:
        # Model didn't follow the format; treat the whole thing as summary.
        return {"summary": raw.strip(), "notes": ""}

    summary_part = raw[:notes_idx]
    notes_part = raw[notes_idx + len("NOTES:"):]

    summary = summary_part.replace("SUMMARY:", "").strip()
    notes = notes_part.strip()

    return {"summary": summary, "notes": notes}
