import os
import re

from faster_whisper import WhisperModel

MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "small")

_model = None
_WORD_RE = re.compile(r"[A-Za-z']+")


def _edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (ca.lower() != cb.lower()))
        prev = curr
    return prev[-1]


def _match_case(hint, sample):
    """Make a correction respect how the misheard word was actually
    capitalized (start of sentence, ALL CAPS, etc.) instead of always
    substituting the hint's own literal casing."""
    if sample.isupper():
        return hint.upper()
    if sample and sample[0].isupper():
        return hint[:1].upper() + hint[1:]
    return hint


def _apply_vocabulary_corrections(text, hints):
    """initial_prompt is only a soft bias — for a hint that's an
    intentionally unusual spelling of an otherwise common word (e.g.
    "Anthm" for a product name that sounds exactly like "Anthem"),
    Whisper's language-model prior can override the prompt and just
    transcribe the common word instead, even with the hint supplied.
    Confirmed against real transcripts: "Anthm" never appeared once
    despite being in VOCABULARY_HINTS every time, always coming out as
    the ordinary word it sounds like.

    This catches that case after the fact: any single-word hint that's a
    close spelling match (small edit distance, same first letter) to a
    word actually in the transcript gets corrected to the hint's exact
    spelling, case-matched to how it was originally written. Multi-word
    hints (e.g. "Mando Man") are skipped — this is specifically for the
    single-word near-homophone case, not general find-and-replace.
    """
    if not text or not hints:
        return text
    hint_words = [h.strip() for h in hints.split(",") if h.strip() and " " not in h.strip()]
    if not hint_words:
        return text

    def replace(match):
        word = match.group(0)
        for hint in hint_words:
            if word.lower() == hint.lower():
                return word
            if word[:1].lower() != hint[:1].lower():
                continue
            # Longer words can tolerate a slightly bigger edit distance
            # (e.g. "Anthem"/"Anthm" is 1 edit on a 6-letter word) without
            # it meaning much less about whether they're really the same
            # word — a fixed distance of 1 would be too strict there but
            # too loose on short words, where even 1 edit can turn one
            # real word into a completely different one.
            max_distance = 1 if len(hint) <= 5 else 2
            if _edit_distance(word, hint) <= max_distance:
                return _match_case(hint, word)
        return word

    return _WORD_RE.sub(replace, text)


def get_model():
    global _model
    if _model is None:
        # int8 keeps this fast enough on CPU-only Macs; switch to "auto" if you have a GPU.
        _model = WhisperModel(MODEL_SIZE, device="auto", compute_type="int8")
    return _model


def transcribe_audio(file_path):
    model = get_model()
    # Read fresh on every call, not once at import — Settings can update
    # this via VOCABULARY_HINTS in os.environ at any point after startup,
    # and a module-level constant would never pick that change up.
    # Comma-separated names/nicknames/jargon Whisper otherwise mishears
    # (e.g. "Mando Man" -> "Mando", "Ghoul" -> "Google") — biases
    # transcription toward these specific words without needing a bigger,
    # slower model.
    vocabulary_hints = os.environ.get("VOCABULARY_HINTS", "").strip()
    try:
        segments, info = model.transcribe(
            file_path,
            beam_size=5,
            initial_prompt=vocabulary_hints or None,
            # Without this, silence/near-silence gets fed to the decoder
            # like any other audio, and with nothing real to anchor on it
            # tends to hallucinate — often echoing back exactly the
            # initial_prompt text (e.g. VOCABULARY_HINTS) as if it had
            # been said. VAD strips non-speech before it reaches the
            # decoder at all.
            vad_filter=True,
            # A Whisper segment's boundaries reflect pause detection, not
            # who's talking — two people trading quick turns (e.g. "can you
            # hear me now?" / "yep, there we go") easily land in the same
            # segment. Dual-stream diarization needs per-word timing to
            # split a segment like that at the real speaker change instead
            # of routing the whole blended segment to one channel.
            word_timestamps=True,
        )
        segment_list = []
        full_text_parts = []
        for segment in segments:
            text = _apply_vocabulary_corrections(segment.text.strip(), vocabulary_hints)
            segment_list.append(
                {
                    "start": round(segment.start, 2),
                    "end": round(segment.end, 2),
                    "text": text,
                    "words": [
                        {
                            "start": round(w.start, 2),
                            "end": round(w.end, 2),
                            "word": _apply_vocabulary_corrections(w.word, vocabulary_hints),
                        }
                        for w in (segment.words or [])
                    ],
                }
            )
            full_text_parts.append(text)

        return {
            "language": info.language,
            "duration": round(info.duration, 2),
            "segments": segment_list,
            "text": " ".join(full_text_parts).strip(),
        }
    except ValueError:
        # VAD found no speech anywhere in the file at all (e.g. hit
        # Record and said nothing) — faster-whisper's own language-guess
        # step raises on an empty candidate list in exactly this case
        # rather than returning an empty result itself.
        try:
            import soundfile as sf

            duration = round(sf.info(file_path).duration, 2)
        except Exception:
            duration = 0.0
        return {"language": None, "duration": duration, "segments": [], "text": ""}
