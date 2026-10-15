import json
import os
import re
import traceback

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
this always comes first, before anything else. Action Items is always bullets, one per line — \
these become checkable to-do items, not prose.
   - After that, break the rest of the discussion into your own topic-specific section headings, \
named for what was actually discussed (e.g. "Budget Planning", "Hiring Timeline for Q3", "Client \
Feedback on the V2 Design") — not generic labels like "Key Points" or "Decisions". Use as many \
sections as make sense for how the conversation actually flowed; a short meeting might only need \
one or two.
   - Write each of those sections as normal prose paragraphs under its heading, the way you'd \
actually describe what was discussed and decided — not a bullet for every sentence. Reach for \
bullets within a section only when the content is genuinely list-shaped (e.g. several distinct, \
parallel short items, or a nested sub-point breaking out supporting detail under a bullet already \
in use) — bullets should be the exception inside a topic section, not the default structure.
   - Format every section heading (including "Action Items") as its own line wrapped in double \
asterisks, e.g. **Budget Planning**.

Always preserve specific, concrete details exactly as mentioned — deadlines and dates, dollar \
amounts, names, version numbers, and anything else precise. These are usually the actual point of \
an action item or decision; a summary that generalizes "ship pricing copy by Friday" down to just \
"ship pricing copy" has thrown away the one detail that made it actionable. When in doubt, keep the \
specific detail in rather than trim it for brevity.

That's about never dropping a detail that was actually said — it's not license to pad length. The \
overall length of the notes should track how much was actually discussed, not aim for some minimum \
amount of content: a short, low-content meeting should get short notes (maybe just a sentence or \
two, or a couple bullets, not padded-out sections), and a long, dense meeting earns the longer \
writeup. Being thorough about the details that exist is not the same as generating more text than \
the conversation actually contained.

The transcript's turns are labeled by voice, like "Speaker 1:" or "Speaker 2:" — these are \
automatically detected voices, not necessarily correct or stable if a speaker is briefly silent. \
If someone's real name becomes clear from what's actually said (introductions, being addressed \
by name, signing off with a name), use that name in the summary and notes instead of the \
generic label. If a speaker's name never comes up, keep referring to them by their generic \
label rather than guessing a name.

Coverage: every distinct topic that was substantively discussed, meaning someone explained, \
decided, or committed to something about it, needs a place in the notes. A long or dense meeting \
is not a reason to leave a topic out. If something has to be shortened, shorten how much you say \
about it, not whether it appears at all.
{{LEVEL}}
Respond with exactly this format, no preamble:

TITLE:
<title text>

SUMMARY:
<summary text>

NOTES:
<notes text, markdown bullet points>
"""


DETAIL_LEVELS = ("quick", "balanced", "detailed")
DEFAULT_DETAIL_LEVEL = "balanced"

# "balanced" adds nothing: it is the prompt above exactly as it was before
# detail levels existed, so choosing it changes no behavior.
_LEVEL_INSTRUCTIONS = {
    "quick": """
Detail level: QUICK. The reader wants the gist in under a minute, so this level deliberately \
overrides the coverage rule above. Write a one or two sentence summary. For the notes, write only \
the Action Items section (skip it if there genuinely are none), plus at most a few short bullets \
for decisions or deadlines that are not action items. Do not write topic sections.
""",
    "balanced": "",
    "detailed": """
Detail level: DETAILED. The reader wants the notes to stand in for the meeting. Keep the \
supporting detail for each topic and not just the headline: the reasoning behind a decision, the \
alternatives that were considered and why they lost, open questions, and who said what when it \
matters. Names, numbers, dates and technical specifics stay exact. Longer notes are fine at this \
level, but only for content that was really said.
""",
}

# Output ceiling per level. Quick only needs a little; keeping it low stops
# a runaway answer from costing more than the short result is worth.
# Balanced and detailed keep the full 16000 that stopped long meetings from
# being cut off mid-notes (see the note on max_tokens in summarize_transcript).
_LEVEL_MAX_TOKENS = {"quick": 3000, "balanced": 16000, "detailed": 16000}


def _detail_level():
    # Read on every call, not once at import: Settings changes this in
    # os.environ at any point after startup (same reason transcribe.py reads
    # VOCABULARY_HINTS per call).
    level = os.environ.get("SUMMARY_DETAIL_LEVEL", "").strip().lower()
    return level if level in DETAIL_LEVELS else DEFAULT_DETAIL_LEVEL


def _system_prompt(level):
    return SYSTEM_PROMPT.replace("{{LEVEL}}", _LEVEL_INSTRUCTIONS[level])


COVERAGE_PROMPT = """You audit meeting notes against the transcript they were written from.

List the substantive topics in the transcript that the notes do NOT cover, or cover so thinly \
that the key point is lost. Substantive means someone explained, decided, walked through, or \
committed to something that a reader would want to find in the notes later: decisions, plans, \
technical or product explanations, deadlines, numbers, names, open questions.

Do not list small talk, greetings, scheduling logistics, or tangents with no real content. A \
topic that appears in the notes in any form, even briefly, is covered; only list real gaps. Be \
conservative: if you are unsure whether something is a gap, leave it out.

Respond with only JSON, in this shape:
{"missing": [{"topic": "<2 to 6 words>", "detail": "<one sentence: what was actually said, with the specifics that would otherwise be lost>"}]}

Use {"missing": []} if nothing substantive is missing. List at most 6 items, most important first."""

ADD_TOPICS_PROMPT = """You add missing topics to existing meeting notes.

You are given a transcript, the notes as they currently stand, and a list of topics the notes \
miss. Write only the new content. For each topic, write a section heading in the same style as \
the existing notes (its own line wrapped in double asterisks, like **Topic Name**) followed by \
prose paragraphs describing what was actually discussed and decided. Keep names, numbers, dates \
and technical specifics exact, and refer to people the same way the existing notes do.

Do not repeat anything already in the notes, and do not write an Action Items section: put any \
commitments or deadlines in the prose instead. Respond with only the new sections, no preamble."""


def _parse_missing_topics(raw):
    """Pull the topic list out of the coverage check's reply. Best-effort on
    purpose: a malformed reply means no warning, never a broken summary."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return []
    try:
        items = json.loads(match.group(0)).get("missing", [])
    except (ValueError, AttributeError):
        return []
    topics = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and str(item.get("topic", "")).strip():
            topics.append({"topic": str(item["topic"]).strip(), "detail": str(item.get("detail", "")).strip()})
    return topics[:6]


def find_missing_topics(transcript, notes):
    """Second pass: check the finished notes against the transcript. A
    summary can finish completely normally and still just leave a whole
    topic out, with nothing to tell the reader anything is missing. This
    is what gives that case a signal."""
    client = _client()
    message = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        system=COVERAGE_PROMPT,
        messages=[{"role": "user", "content": f"Transcript:\n\n{transcript}\n\n---\n\nNotes:\n\n{notes}"}],
    )
    record_usage(MODEL, message.usage.input_tokens, message.usage.output_tokens)
    raw = "".join(block.text for block in message.content if block.type == "text")
    return _parse_missing_topics(raw)


def add_missing_topics(transcript, notes, topics):
    """Write sections for just the topics the coverage check found missing,
    to be appended to the existing notes."""
    client = _client()
    listed = "\n".join(f"- {t['topic']}: {t.get('detail', '')}" for t in topics)
    message = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=ADD_TOPICS_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Transcript:\n\n{transcript}\n\n---\n\nCurrent notes:\n\n{notes}\n\n---\n\nMissing topics:\n{listed}",
            }
        ],
    )
    record_usage(MODEL, message.usage.input_tokens, message.usage.output_tokens)
    return "".join(block.text for block in message.content if block.type == "text").strip()


def _client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return anthropic.Anthropic(api_key=api_key)


def summarize_transcript(transcript_text):
    if not transcript_text or not transcript_text.strip():
        raise ValueError("Transcript is empty")

    level = _detail_level()
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
        max_tokens=_LEVEL_MAX_TOKENS[level],
        system=_system_prompt(level),
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

    # Quick notes leave topics out on purpose, so checking them for gaps
    # would only flag the point of the setting.
    result["missing_topics"] = []
    if level != "quick" and result["notes"]:
        try:
            result["missing_topics"] = find_missing_topics(transcript_text, result["notes"])
        except Exception:
            # The notes are already good enough to show. A failed audit
            # means no warning this time, not a failed summary.
            traceback.print_exc()
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
