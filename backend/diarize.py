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


def _embed_and_cluster(audio, sample_rate, segments, indices):
    """Cluster the given subset of segment indices by speaker embedding.
    Returns {index: local_cluster_id} (0-based, only meaningful within this
    call) for every index in `indices`. Segments too short to embed
    reliably inherit the nearest prior label within this same subset."""
    if not indices:
        return {}

    model = get_model()
    embeddings = []
    embedded_indices = []
    for i in indices:
        seg = segments[i]
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

    if not embedded_indices:
        return {i: 0 for i in indices}

    if len(embeddings) == 1:
        label_by_index = {embedded_indices[0]: 0}
    else:
        stacked = np.stack(embeddings)
        clustering = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=CLUSTER_THRESHOLD,
            metric="cosine",
            linkage="average",
        )
        labels = clustering.fit_predict(stacked)
        label_by_index = dict(zip(embedded_indices, labels))

    result = {}
    last_label = 0
    for i in indices:
        if i in label_by_index:
            last_label = int(label_by_index[i])
        result[i] = last_label
    return result


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
    label_by_index = _embed_and_cluster(audio, sample_rate, segments, list(range(len(segments))))

    for i, seg in enumerate(segments):
        seg["speaker"] = f"Speaker {label_by_index.get(i, 0) + 1}"

    return segments


def diarize_with_source_separation(mic_path, system_path, segments):
    """Like diarize_segments, but uses two separate reference recordings —
    mic-only and system-audio-only, captured in parallel with the main
    mixed recording — to determine each segment's source directly by which
    track is louder at that moment, instead of relying purely on
    voice-embedding similarity. Pure similarity struggles when two voices
    happen to sound alike (e.g. mistaking a video's narrator for the user).

    The largest mic-side voice cluster is labeled "You"; every other
    distinct voice (an extra voice sharing the mic, or any number of voices
    coming through system audio) gets a normal "Speaker N" label, numbered
    in order of first appearance. Mutates and returns `segments`.
    """
    if not segments:
        return segments

    mic_audio, mic_sr = _load_audio_mono(mic_path)
    sys_audio, sys_sr = _load_audio_mono(system_path)

    def rms(audio, sr, start, end):
        clip = audio[int(start * sr) : int(end * sr)]
        return float(np.sqrt(np.mean(clip**2))) if len(clip) else 0.0

    mic_indices, system_indices = [], []
    for i, seg in enumerate(segments):
        mic_level = rms(mic_audio, mic_sr, seg["start"], seg["end"])
        sys_level = rms(sys_audio, sys_sr, seg["start"], seg["end"])
        (mic_indices if mic_level >= sys_level else system_indices).append(i)

    mic_labels = _embed_and_cluster(mic_audio, mic_sr, segments, mic_indices)
    system_labels = _embed_and_cluster(sys_audio, sys_sr, segments, system_indices)

    you_cluster = None
    if mic_labels:
        counts = {}
        for label in mic_labels.values():
            counts[label] = counts.get(label, 0) + 1
        you_cluster = max(counts, key=counts.get)

    speaker_names = {}
    next_number = 1
    for i in range(len(segments)):
        if i in mic_labels:
            key = ("mic", mic_labels[i])
        else:
            key = ("system", system_labels.get(i, 0))

        if key == ("mic", you_cluster):
            segments[i]["speaker"] = "You"
            continue

        if key not in speaker_names:
            speaker_names[key] = f"Speaker {next_number}"
            next_number += 1
        segments[i]["speaker"] = speaker_names[key]

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
