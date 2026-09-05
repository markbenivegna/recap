import contextlib
import os
import shutil
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


def _find_ffmpeg_bin():
    # Same issue as SwitchAudioSource in audio_switch.py: a GUI-launched app
    # (opened from Finder/the app drawer, not a Terminal) gets a minimal
    # PATH that doesn't include Homebrew's bin dir, so shutil.which() alone
    # can miss ffmpeg even though it's installed and this exact call works
    # fine when launched from an interactive shell.
    found = shutil.which("ffmpeg")
    if found:
        return found
    for candidate in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return "ffmpeg"


_FFMPEG_BIN = _find_ffmpeg_bin()


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
                [_FFMPEG_BIN, "-y", "-i", file_path, "-ar", "16000", "-ac", "1", wav_path],
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


def _embed_clip(audio, sample_rate, start, end):
    """Embed one segment's audio clip, or None if it's too short to embed
    reliably."""
    clip = audio[int(start * sample_rate) : int(end * sample_rate)]
    if len(clip) < sample_rate * MIN_SEGMENT_SECONDS:
        return None
    tensor = torch.from_numpy(clip).unsqueeze(0)
    with torch.no_grad():
        return get_model().encode_batch(tensor).squeeze().cpu().numpy()


def _cosine_distance(a, b):
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 1.0
    return 1.0 - float(np.dot(a, b) / denom)


def _rms(audio, sample_rate, start, end):
    clip = audio[int(start * sample_rate) : int(end * sample_rate)]
    return float(np.sqrt(np.mean(clip**2))) if len(clip) else 0.0


def _rms_normalize(audio, target=0.1):
    """Scale so the whole clip's overall RMS matches `target`. The mic/
    system comparison below is itself RMS-based (average energy per
    segment), so normalizing by RMS matches what's actually being
    compared — peak-normalizing instead was a mistake: a single loud
    transient (a click, a pop) anywhere in the file would skew the scale
    for the entire rest of it, since peak looks at just one sample rather
    than overall energy. This normalization compensates for
    getUserMedia's autoGainControl no longer doing it automatically (it
    had to be disabled elsewhere to stop echo cancellation from
    suppressing the system-audio capture entirely)."""
    overall_rms = float(np.sqrt(np.mean(audio**2))) if len(audio) else 0.0
    if overall_rms == 0:
        return audio
    return audio * (target / overall_rms)


def _embed_and_cluster(audio, sample_rate, segments, indices):
    """Cluster the given subset of segment indices by speaker embedding.
    Returns {index: local_cluster_id} (0-based, only meaningful within this
    call) for every index in `indices`. Segments too short to embed
    reliably inherit the nearest prior label within this same subset."""
    if not indices:
        return {}

    embeddings = []
    embedded_indices = []
    for i in indices:
        seg = segments[i]
        emb = _embed_clip(audio, sample_rate, seg["start"], seg["end"])
        if emb is not None:
            embeddings.append(emb)
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


def _cluster_centroids(audio, sample_rate, segments, indices, labels):
    """Mean embedding per cluster label, for matching other audio against
    these voices later."""
    buckets = {}
    for i in indices:
        seg = segments[i]
        emb = _embed_clip(audio, sample_rate, seg["start"], seg["end"])
        if emb is None:
            continue
        buckets.setdefault(labels[i], []).append(emb)
    return {label: np.mean(embs, axis=0) for label, embs in buckets.items()}


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
    mixed recording — to tell the user's voice apart from everyone else's,
    without assuming who talks first (not reliable — the user might not be
    the one who speaks first) and without relying purely on which track is
    louder (not reliable either — if the user has speakers rather than
    headphones, other people's audio is audible in the room and bleeds
    acoustically into the mic, which can outweigh the user's own voice).

    Key insight: system audio can only ever contain *other* people's voices
    — the user's own live mic input is never routed back out through their
    speakers. So system-audio segments are trustworthy "known not-you"
    voiceprints. Any mic-side segment whose voice actually matches one of
    those is leaked room audio, not really the user, and gets reclassified
    to that speaker instead. Whatever's left on the mic side is the user —
    labeled "You"; everyone else gets a normal "Speaker N" label, numbered
    in order of first appearance. Mutates and returns `segments`.
    """
    if not segments:
        return segments

    mic_audio, mic_sr = _load_audio_mono(mic_path)
    sys_audio, sys_sr = _load_audio_mono(system_path)
    mic_audio = _rms_normalize(mic_audio)
    sys_audio = _rms_normalize(sys_audio)

    mic_indices, system_indices = [], []
    for i, seg in enumerate(segments):
        mic_level = _rms(mic_audio, mic_sr, seg["start"], seg["end"])
        sys_level = _rms(sys_audio, sys_sr, seg["start"], seg["end"])
        (mic_indices if mic_level >= sys_level else system_indices).append(i)

    system_labels = _embed_and_cluster(sys_audio, sys_sr, segments, system_indices)
    system_centroids = _cluster_centroids(sys_audio, sys_sr, segments, system_indices, system_labels)

    # Mic-side segments whose voice actually matches a known system-audio
    # voice are leaked/bled-through audio, not the user — reclassify them
    # to that speaker rather than lumping them in with the user's own voice.
    true_mic_indices = []
    reclassified = {}
    for i in mic_indices:
        seg = segments[i]
        emb = _embed_clip(mic_audio, mic_sr, seg["start"], seg["end"])
        if emb is None or not system_centroids:
            true_mic_indices.append(i)
            continue
        best_label = min(system_centroids, key=lambda label: _cosine_distance(emb, system_centroids[label]))
        if _cosine_distance(emb, system_centroids[best_label]) < CLUSTER_THRESHOLD:
            reclassified[i] = best_label
        else:
            true_mic_indices.append(i)

    mic_labels = _embed_and_cluster(mic_audio, mic_sr, segments, true_mic_indices)

    # After removing leaked segments, whatever's left on the mic side should
    # overwhelmingly be one consistent voice — the user's. If someone else
    # is also genuinely sharing the mic (an in-person guest), that shows up
    # as a second, smaller cluster here; the largest one is "You".
    you_cluster = None
    if mic_labels:
        counts = {}
        for label in mic_labels.values():
            counts[label] = counts.get(label, 0) + 1
        you_cluster = max(counts, key=counts.get)

    speaker_names = {}
    next_number = 1
    for i in range(len(segments)):
        if i in reclassified:
            key = ("system", reclassified[i])
        elif i in mic_labels:
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
