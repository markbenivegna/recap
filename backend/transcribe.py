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
    segments, info = model.transcribe(
        file_path,
        beam_size=5,
        initial_prompt=VOCABULARY_HINTS or None,
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
