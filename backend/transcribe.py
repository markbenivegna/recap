import os

from faster_whisper import WhisperModel

MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "small")

_model = None


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
            segment_list.append(
                {
                    "start": round(segment.start, 2),
                    "end": round(segment.end, 2),
                    "text": segment.text.strip(),
                    "words": [
                        {"start": round(w.start, 2), "end": round(w.end, 2), "word": w.word}
                        for w in (segment.words or [])
                    ],
                }
            )
            full_text_parts.append(segment.text.strip())

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
