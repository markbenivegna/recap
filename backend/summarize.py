import os

import anthropic

from backend.usage_tracker import record_usage

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

SYSTEM_PROMPT = """You turn raw meeting transcripts into three things:

1. A short descriptive title for the meeting — 3-7 words, specific to what was actually \
discussed (e.g. "Q3 Roadmap Planning", "Client Onboarding Call: Acme Corp"). Not generic \
("Meeting Notes", "Team Sync") unless the transcript genuinely gives you nothing more specific.
2. A concise summary — a few sentences describing what the meeting was about and the outcome.
3. Structured notes as markdown, organized like this:
   - Start with an "**Action Items**" section (skip it entirely if there genuinely aren't any) — \
this always comes first, before anything else.
   - After that, break the rest of the discussion into your own topic-specific section headings, \
named for what was actually discussed (e.g. "Budget Planning", "Hiring Timeline for Q3", "Client \
Feedback on the V2 Design") — not generic labels like "Key Points" or "Decisions". Use as many \
sections as make sense for how the conversation actually flowed; a short meeting might only need \
one or two.
   - Within a section, use a nested sub-bullet (indent it two extra spaces under its parent bullet) \
when a point has supporting detail worth breaking out, e.g.:
     - Main point
       - Supporting detail
       - Another supporting detail
   - Format every section heading (including "Action Items") as its own line wrapped in double \
asterisks, e.g. **Budget Planning**.

Always preserve specific, concrete details exactly as mentioned — deadlines and dates, dollar \
amounts, names, version numbers, and anything else precise. These are usually the actual point of \
an action item or decision; a summary that generalizes "ship pricing copy by Friday" down to just \
"ship pricing copy" has thrown away the one detail that made it actionable. When in doubt, keep the \
specific detail in rather than trim it for brevity.

The transcript's turns are labeled by voice, like "Speaker 1:" or "Speaker 2:" — these are \
automatically detected voices, not necessarily correct or stable if a speaker is briefly silent. \
If someone's real name becomes clear from what's actually said (introductions, being addressed \
by name, signing off with a name), use that name in the summary and notes instead of the \
generic label. If a speaker's name never comes up, keep referring to them by their generic \
label rather than guessing a name.

Respond with exactly this format, no preamble:

TITLE:
<title text>

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
        # 1500, then 4096, both still truncated on a real ~80min meeting -
        # this is a non-streaming request, and Anthropic's own guidance
        # for those is up to ~16000 before HTTP timeouts become a risk
        # (Sonnet 5 itself supports up to 128K output, but that requires
        # streaming, which this synchronous endpoint doesn't do). 16000
        # is comfortably more than even a long meeting's summary+notes
        # should ever need, without restructuring this into a streaming
        # call.
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Transcript:\n\n{transcript_text}"}],
    )

    record_usage(MODEL, message.usage.input_tokens, message.usage.output_tokens)

    raw = "".join(block.text for block in message.content if block.type == "text")
    result = _parse_response(raw)
    # If the model ran out of room before finishing, say so rather than
    # silently handing back notes that just stop mid-thought — this is the
    # concrete, checkable version of the truncation risk max_tokens above
    # is already sized to avoid, not a replacement for that fix.
    if message.stop_reason == "max_tokens":
        result["truncated"] = True
    return result


def _parse_response(raw):
    summary_idx = raw.find("SUMMARY:")
    notes_idx = raw.find("NOTES:")

    if summary_idx == -1 or notes_idx == -1:
        # Model didn't follow the format; treat the whole thing as summary.
        return {"title": "", "summary": raw.strip(), "notes": ""}

    title_part = raw[:summary_idx]
    summary_part = raw[summary_idx + len("SUMMARY:"):notes_idx]
    notes_part = raw[notes_idx + len("NOTES:"):]

    title = title_part.replace("TITLE:", "").strip()
    summary = summary_part.strip()
    notes = notes_part.strip()

    return {"title": title, "summary": summary, "notes": notes}
