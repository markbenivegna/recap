import os

from faster_whisper import WhisperModel

MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "small")

# Comma-separated names/nicknames/jargon Whisper otherwise mishears (e.g.
# "Mando Man" -> "Mando", "Ghoul" -> "Google") — biases transcription
# toward these specific words without needing a bigger, slower model.
VOCABULARY_HINTS = os.environ.get("VOCABULARY_HINTS", "").strip()

_model = None


def get_model():
    global _model
    if _model is None:
        # int8 keeps this fast enough on CPU-only Macs; switch to "auto" if you have a GPU.
        _model = WhisperModel(MODEL_SIZE, device="auto", compute_type="int8")
    return _model


def transcribe_audio(file_path):
    model = get_model()
    try:
        segments, info = model.transcribe(
            file_path,
            beam_size=5,
            initial_prompt=VOCABULARY_HINTS or None,
            # Without this, silence/near-silence gets fed to the decoder
            # like any other audio, and with nothing real to anchor on it
            # tends to hallucinate — often echoing back exactly the
            # initial_prompt text (e.g. VOCABULARY_HINTS) as if it had
            # been said. VAD strips non-speech before it reaches the
            # decoder at all.
            vad_filter=True,
        )
        segment_list = []
        full_text_parts = []
        for segment in segments:
            segment_list.append(
                {
                    "start": round(segment.start, 2),
                    "end": round(segment.end, 2),
                    "text": segment.text.strip(),
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
