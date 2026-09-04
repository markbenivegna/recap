import contextlib
import os
import subprocess
import tempfile

import numpy as np
import soundfile as sf
import torch
from sklearn.cluster import AgglomerativeClustering
from speechbrain.inference.speaker import EncoderClassifier

# Cosine-distance cutoff for treating two segments as different speakers.
# Lower = more speakers detected (more likely to split one voice into two);
# higher = fewer speakers detected (more likely to merge two voices into one).
CLUSTER_THRESHOLD = float(os.environ.get("DIARIZATION_THRESHOLD", "0.7"))

MIN_SEGMENT_SECONDS = 0.3

_model = None


def get_model():
    global _model
    if _model is None:
        cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".cache", "spkrec-ecapa-voxceleb")
        _model = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb", savedir=cache_dir)
    return _model


def _load_audio_mono(file_path):
    """Read an audio file as a mono float32 array + sample rate. `soundfile`
    (libsndfile) can't decode WebM/Opus — what the browser's MediaRecorder
    actually produces — so this transparently falls back to converting via
    ffmpeg to a temp WAV first for anything soundfile can't open directly.
    """
    try:
        audio, sample_rate = sf.read(file_path, dtype="float32")
    except Exception:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", file_path, "-ar", "16000", "-ac", "1", wav_path],
                check=True,
                capture_output=True,
            )
            audio, sample_rate = sf.read(wav_path, dtype="float32")
        finally:
            with contextlib.suppress(OSError):
                os.remove(wav_path)

    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return audio, sample_rate


def diarize_segments(file_path, segments):
    """Assign a speaker label to each Whisper segment by clustering speaker
    embeddings (SpeechBrain's ECAPA-TDNN model — openly downloadable, no
    HuggingFace account or gated-model approval needed), rather than a
    dedicated diarization pipeline like pyannote.audio, whose pretrained
    models require signing up for one.

    Mutates and returns `segments`, each now carrying a "speaker" key.
    """
    if not segments:
        return segments

    audio, sample_rate = _load_audio_mono(file_path)

    model = get_model()

    embeddings = []
    embedded_indices = []
    for i, seg in enumerate(segments):
        start_sample = int(seg["start"] * sample_rate)
        end_sample = int(seg["end"] * sample_rate)
        clip = audio[start_sample:end_sample]
        if len(clip) < sample_rate * MIN_SEGMENT_SECONDS:
            continue
        tensor = torch.from_numpy(clip).unsqueeze(0)
        with torch.no_grad():
            embedding = model.encode_batch(tensor).squeeze().cpu().numpy()
        embeddings.append(embedding)
        embedded_indices.append(i)

    if len(embeddings) < 2:
        for seg in segments:
            seg["speaker"] = "Speaker 1"
        return segments

    embeddings = np.stack(embeddings)
    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=CLUSTER_THRESHOLD,
        metric="cosine",
        linkage="average",
    )
    labels = clustering.fit_predict(embeddings)

    label_by_index = dict(zip(embedded_indices, labels))

    # Segments too short to embed inherit the nearest prior speaker.
    last_label = 0
    for i, seg in enumerate(segments):
        if i in label_by_index:
            last_label = int(label_by_index[i])
        seg["speaker"] = f"Speaker {last_label + 1}"

    return segments


def format_transcript_with_speakers(segments):
    """Merge consecutive same-speaker segments into "Speaker N: ..." turns,
    one per paragraph — used for the transcript sent to Claude and filed to
    Notion, so speaker attribution survives past the raw segment list."""
    turns = []
    for seg in segments:
        speaker = seg.get("speaker")
        text = seg["text"].strip()
        if not text:
            continue
        if turns and turns[-1]["speaker"] == speaker:
            turns[-1]["text"] += " " + text
        else:
            turns.append({"speaker": speaker, "text": text})

    lines = []
    for turn in turns:
        if turn["speaker"]:
            lines.append(f"{turn['speaker']}: {turn['text']}")
        else:
            lines.append(turn["text"])
    return "\n\n".join(lines)
