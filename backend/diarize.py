import contextlib
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
import soundfile as sf
import torch
from sklearn.cluster import AgglomerativeClustering
from speechbrain.inference.speaker import EncoderClassifier

from backend.paths import CACHE_DIR

# Cosine-distance cutoff for treating two segments as different speakers.
# Lower = more speakers detected (more likely to split one voice into two);
# higher = fewer speakers detected (more likely to merge two voices into one).
CLUSTER_THRESHOLD = float(os.environ.get("DIARIZATION_THRESHOLD", "0.7"))

# AgglomerativeClustering's "average" linkage decides whether to merge two
# clusters based on the *average* pairwise distance between every embedding
# in one and every embedding in the other. Over a whole real meeting, one
# real person's voice can still end up split across two clusters this way —
# not because any single pair of their segments looked unlike each other,
# but because enough individual noisy pairs (different energy, distance
# from the mic, background noise at that moment) pushed the *average*
# above CLUSTER_THRESHOLD, even though the two clusters' overall centroids
# — averaged over many segments each, so far less noisy than any one
# pairwise comparison — are actually close. A single real standup with 5
# people came back with 15+ "speakers" this way: not sub-second fragments
# (MIN_SEGMENT_SECONDS below already handles those), real substantial
# utterances, repeatedly minting a new speaker instead of matching one
# already seen earlier in the meeting.
#
# _consolidate_clusters (below) is a second, coarser pass on top of the
# first: after clustering, merge any two clusters whose centroids —
# not their individual members — are within this more lenient bound.
# Deliberately looser than CLUSTER_THRESHOLD, since a centroid-to-centroid
# comparison is the more reliable signal and this pass's whole job is to
# catch what the noisier pairwise comparisons above missed.
MERGE_THRESHOLD = CLUSTER_THRESHOLD * 1.4

# Minimum RMS (on _rms_normalize'd audio, target=0.1) for a clip to be
# considered loud enough to embed reliably — only meaningful for the
# dual-stream mic/system path, where normalization is guaranteed. Real
# speech in an actual recording measured well above 0.07; a genuinely
# unreliable, barely-audible utterance measured at 0.012. This sits
# comfortably between the two.
MIN_EMBED_RMS = 0.02

# For the leak-reclassification check in diarize_with_source_separation:
# something has to actually be audible on the system channel for a mic
# segment's voice to plausibly be leaked from it in the first place, not
# just embedding similarity alone. See that function for the real
# evidence this caught.
LEAK_MIN_SYSTEM_RMS = 0.01

# ECAPA-TDNN (the embedding model below) needs a real run of speech to
# produce a stable voiceprint — anything much shorter than ~1 second gives a
# noisy embedding that doesn't reliably represent the actual speaker. With
# this at 0.3s, real meetings full of short back-and-forth ("yeah", "right",
# quick interjections) were feeding a lot of these unreliable embeddings
# straight into clustering, each one liable to land far enough from its
# true speaker's other segments to spawn its own spurious cluster — a real
# 3-person meeting coming back diarized as 26 "speakers". Segments shorter
# than this now skip embedding entirely and inherit the nearest prior
# label instead (see _embed_and_cluster below), which is a better guess
# than a noisy embedding for something this short anyway.
MIN_SEGMENT_SECONDS = 1.2

_model = None


def _find_ffmpeg_bin():
    # When packaged (see scripts/bundle_ffmpeg.sh), always prefer our own
    # bundled copy over whatever's on PATH — guaranteed present and
    # known-compatible, unlike an arbitrary system install someone may or
    # may not have. sys.executable is Contents/MacOS/Recap in a frozen app.
    if getattr(sys, "frozen", False):
        bundled = os.path.normpath(
            os.path.join(os.path.dirname(sys.executable), "..", "Resources", "ffmpeg-bin", "ffmpeg")
        )
        if os.path.isfile(bundled) and os.access(bundled, os.X_OK):
            return bundled

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
        cache_dir = os.path.join(CACHE_DIR, "spkrec-ecapa-voxceleb")
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


def _embed_clip(audio, sample_rate, start, end, min_rms=None):
    """Embed one segment's audio clip, or None if it's too short — or, when
    `min_rms` is given (only meaningful for RMS-normalized audio, e.g. the
    dual-stream mic/system path), too quiet — to embed reliably. A very
    faint utterance is unreliable for the same underlying reason a very
    short one is: not enough real signal in the clip for a stable
    voiceprint, just via loudness instead of duration. Confirmed against a
    real recording: a single 2-second "well" at roughly a tenth the RMS of
    normal speech in that same meeting produced an embedding that didn't
    match anyone, becoming its own phantom one-segment "speaker"."""
    clip = audio[int(start * sample_rate) : int(end * sample_rate)]
    if len(clip) < sample_rate * MIN_SEGMENT_SECONDS:
        return None
    if min_rms is not None and (len(clip) == 0 or float(np.sqrt(np.mean(clip**2))) < min_rms):
        return None
    tensor = torch.from_numpy(clip).unsqueeze(0)
    with torch.no_grad():
        return get_model().encode_batch(tensor).squeeze().cpu().numpy()


def _cosine_distance(a, b):
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 1.0
    return 1.0 - float(np.dot(a, b) / denom)


def _consolidate_clusters(embeddings, embedded_indices, label_by_index):
    """Second pass on top of an initial clustering (see MERGE_THRESHOLD's
    comment for why this is needed): merge any two clusters whose mean
    embeddings — not their individual members — land within
    MERGE_THRESHOLD of each other. Mutates `label_by_index` in place.

    Only merges when one of the two clusters is clearly a minority
    fragment of the other (see _is_fragment below), not just because their
    centroids happen to be close — two real, comparably-sized clusters
    (e.g. a second person who spoke substantially through part of a
    meeting) are a real second speaker far more often than they're one
    voice's variance, even when MERGE_THRESHOLD alone would call them
    close enough. Confirmed against real use: without this size check, a
    whole genuine conversation between the user and a real third person
    got folded into an existing speaker instead of staying its own
    "Speaker N" — exactly the opposite failure from the one this pass was
    added to fix (see f89a927), just with the leniency turned too far the
    other way.
    """
    # Group embeddings by their initial cluster label so we can average
    # each cluster's own embeddings into one centroid.
    by_label = {}
    for i, idx in enumerate(embedded_indices):
        by_label.setdefault(label_by_index[idx], []).append(embeddings[i])
    centroids = {label: np.mean(embs, axis=0) for label, embs in by_label.items()}
    sizes = {label: len(embs) for label, embs in by_label.items()}

    def _is_fragment(label_a, label_b):
        smaller, larger = sorted((sizes[label_a], sizes[label_b]))
        # A handful of segments (natural variance splitting off a few
        # utterances) folds back in; a real ongoing exchange - several
        # segments and a meaningful fraction of the larger cluster's size
        # - does not, regardless of how close the centroids land.
        return smaller <= 3 and smaller <= larger * 0.25

    merged = True
    while merged and len(centroids) > 1:
        merged = False
        labels_list = list(centroids)
        for i, label_a in enumerate(labels_list):
            if label_a not in centroids:
                continue
            for label_b in labels_list[i + 1 :]:
                if label_b not in centroids:
                    continue
                if not _is_fragment(label_a, label_b):
                    continue
                if _cosine_distance(centroids[label_a], centroids[label_b]) < MERGE_THRESHOLD:
                    # Keep whichever label is the larger cluster so the
                    # surviving label is the well-established one.
                    keep, drop = (label_a, label_b) if sizes[label_a] >= sizes[label_b] else (label_b, label_a)
                    for idx, lbl in label_by_index.items():
                        if lbl == drop:
                            label_by_index[idx] = keep
                    sizes[keep] += sizes[drop]
                    del centroids[drop]
                    del sizes[drop]
                    merged = True
                    if drop == label_a:
                        # label_a itself just got merged away — every
                        # remaining label_b in this inner loop would look it
                        # up in sizes/centroids and KeyError, since the
                        # `label_a not in centroids` guard above only runs
                        # once per label_a, before this inner loop starts,
                        # not after a merge happens partway through it. The
                        # outer while-loop already restarts with a fresh
                        # labels_list on the next pass, so bailing out here
                        # is enough to pick this back up correctly.
                        break


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


def _embed_and_cluster(audio, sample_rate, segments, indices, min_rms=None):
    """Cluster the given subset of segment indices by speaker embedding.
    Returns {index: local_cluster_id} (0-based, only meaningful within this
    call) for every index in `indices`. Segments too short (or, with
    `min_rms` set, too quiet) to embed reliably inherit the nearest prior
    label within this same subset."""
    if not indices:
        return {}

    embeddings = []
    embedded_indices = []
    for i in indices:
        seg = segments[i]
        emb = _embed_clip(audio, sample_rate, seg["start"], seg["end"], min_rms=min_rms)
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
        _consolidate_clusters(embeddings, embedded_indices, label_by_index)

    result = {}
    last_label = 0
    for i in indices:
        if i in label_by_index:
            last_label = int(label_by_index[i])
        result[i] = last_label
    return result


def _cluster_centroids(audio, sample_rate, segments, indices, labels, min_rms=None):
    """Mean embedding per cluster label, for matching other audio against
    these voices later."""
    buckets = {}
    for i in indices:
        seg = segments[i]
        emb = _embed_clip(audio, sample_rate, seg["start"], seg["end"], min_rms=min_rms)
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
        seg.pop("words", None)

    return segments


def _smooth_word_runs(runs):
    """Absorb single-word runs into whichever neighboring run is longer,
    before splitting on channel changes.

    Per-word RMS is noisy — a brief pause or breath mid-sentence can let
    the other channel's ambient floor momentarily read louder, flipping a
    single word's route even in the middle of one person's uninterrupted
    turn. Confirmed against real output: normal continuous speech like
    "...just kind of giving me a little bit of an update on what you're
    working on..." was getting shredded into single-word runs alternating
    speakers every word or two — not a real speaker change, just RMS
    noise on isolated words. A genuine speaker change (the actual bug this
    resegmentation fixes) produces a run of several consecutive words on
    the new channel, not a single flickering word, so absorbing only
    length-1 runs into their longer neighbor fixes the noise without
    undoing the real fix.
    """
    runs = [(route, list(words)) for route, words in runs]
    changed = True
    while changed and len(runs) > 1:
        changed = False
        for i, (_, words) in enumerate(runs):
            if len(words) > 1:
                continue
            prev_len = len(runs[i - 1][1]) if i > 0 else -1
            next_len = len(runs[i + 1][1]) if i < len(runs) - 1 else -1
            target = i - 1 if prev_len >= next_len else i + 1
            target_route = runs[target][0]
            merged_words = sorted(runs[target][1] + words, key=lambda w: w["start"])
            runs[target] = (target_route, merged_words)
            del runs[i]
            changed = True
            break

    # Merging can leave two adjacent runs on the same route (e.g. a
    # flickered word absorbed leftward now sits between two same-route
    # runs) — collapse those back into one.
    collapsed = []
    for route, words in runs:
        if collapsed and collapsed[-1][0] == route:
            collapsed[-1] = (route, collapsed[-1][1] + words)
        else:
            collapsed.append((route, words))
    return collapsed


def _resegment_by_channel(segments, mic_audio, mic_sr, sys_audio, sys_sr):
    """Split each segment at points where the louder channel changes from
    one word to the next, instead of routing the whole segment to one
    channel based on its overall average RMS.

    A Whisper segment's boundaries come from pause detection, not from who
    is talking — two people trading quick turns (e.g. "can you hear me
    now?" / "yep, there we go") easily land inside the same segment. RMS-
    averaging that whole blended segment routes it entirely to whichever
    channel happened to be louder on average, stealing one person's words
    into the other's. Real evidence: a real call-opening segment measured
    mic=0.087 vs sys=0.130 — genuinely close, not a clean signal either
    way, because it blended both people's short exchange into one 12-
    second span. Routing per word instead means only the words that were
    actually louder on a channel get attributed to it.

    Segments without word-level timestamps (or with only one word) pass
    through unchanged. Drops the "words" key either way — nothing
    downstream needs per-word data past this point.
    """
    new_segments = []
    for seg in segments:
        words = seg.get("words") or []
        if len(words) < 2:
            new_segments.append({k: v for k, v in seg.items() if k != "words"})
            continue

        runs = []
        for w in words:
            mic_level = _rms(mic_audio, mic_sr, w["start"], w["end"])
            sys_level = _rms(sys_audio, sys_sr, w["start"], w["end"])
            route = "mic" if mic_level >= sys_level else "sys"
            if runs and runs[-1][0] == route:
                runs[-1][1].append(w)
            else:
                runs.append((route, [w]))

        runs = _smooth_word_runs(runs)

        if len(runs) == 1:
            new_segments.append({k: v for k, v in seg.items() if k != "words"})
            continue

        for _, run_words in runs:
            text = "".join(w["word"] for w in run_words).strip()
            if not text:
                continue
            new_segments.append(
                {
                    "start": run_words[0]["start"],
                    "end": run_words[-1]["end"],
                    "text": text,
                }
            )

    return new_segments


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

    segments[:] = _resegment_by_channel(segments, mic_audio, mic_sr, sys_audio, sys_sr)

    mic_indices, system_indices = [], []
    for i, seg in enumerate(segments):
        mic_level = _rms(mic_audio, mic_sr, seg["start"], seg["end"])
        sys_level = _rms(sys_audio, sys_sr, seg["start"], seg["end"])
        (mic_indices if mic_level >= sys_level else system_indices).append(i)

    system_labels = _embed_and_cluster(sys_audio, sys_sr, segments, system_indices, min_rms=MIN_EMBED_RMS)
    system_centroids = _cluster_centroids(
        sys_audio, sys_sr, segments, system_indices, system_labels, min_rms=MIN_EMBED_RMS
    )

    # A provisional, unfiltered clustering of every mic-side segment, used
    # only to get a rough "this is what the user's own voice looks like"
    # reference before any leak filtering happens. Without this, the leak
    # check below has nothing to compare a candidate match against except
    # an absolute threshold — and real evidence showed that's not enough:
    # short, early segments of genuine, continuous user speech matched an
    # unrelated system voice at distances of 0.59-0.70 (just under
    # CLUSTER_THRESHOLD) purely from embedding noise on a short clip, while
    # actually sitting at 0.18-0.56 from what the user's own voice turned
    # out to be — a far closer match that was simply never considered.
    provisional_mic_labels = _embed_and_cluster(mic_audio, mic_sr, segments, mic_indices, min_rms=MIN_EMBED_RMS)
    provisional_you_centroid = None
    if provisional_mic_labels:
        counts = {}
        for label in provisional_mic_labels.values():
            counts[label] = counts.get(label, 0) + 1
        provisional_you = max(counts, key=counts.get)
        provisional_centroids = _cluster_centroids(
            mic_audio, mic_sr, segments, mic_indices, provisional_mic_labels, min_rms=MIN_EMBED_RMS
        )
        provisional_you_centroid = provisional_centroids.get(provisional_you)

    # Mic-side segments whose voice actually matches a known system-audio
    # voice are leaked/bled-through audio, not the user — reclassify them
    # to that speaker rather than lumping them in with the user's own voice.
    #
    # But that's only physically possible if something was actually
    # audible on the system-audio channel at that moment for it to leak
    # from — real evidence caught this misfiring on genuine, continuous
    # user speech: distances of 0.65-0.68 (under CLUSTER_THRESHOLD) got
    # real "You" segments reclassified as a system speaker, while the
    # system channel's RMS at those exact same moments was ~0.0004 -
    # silence, nowhere near the ~0.07+ a real playing voice measures at.
    # There was nothing to leak. A single embedding comparison alone
    # isn't enough evidence; require audible system output at the same
    # moment as a precondition, not just voice similarity.
    #
    # Even with that precondition, a match under the absolute threshold
    # isn't enough on its own — it also has to be a *better* match than
    # the user's own provisional voiceprint above, or a noisy short clip
    # of the user's real voice can still get stolen just for happening to
    # land under CLUSTER_THRESHOLD against some unrelated system speaker.
    true_mic_indices = []
    reclassified = {}
    for i in mic_indices:
        seg = segments[i]
        if _rms(sys_audio, sys_sr, seg["start"], seg["end"]) < LEAK_MIN_SYSTEM_RMS:
            true_mic_indices.append(i)
            continue
        emb = _embed_clip(mic_audio, mic_sr, seg["start"], seg["end"], min_rms=MIN_EMBED_RMS)
        if emb is None or not system_centroids:
            true_mic_indices.append(i)
            continue
        best_label = min(system_centroids, key=lambda label: _cosine_distance(emb, system_centroids[label]))
        best_dist = _cosine_distance(emb, system_centroids[best_label])
        closer_to_you = (
            provisional_you_centroid is not None
            and _cosine_distance(emb, provisional_you_centroid) <= best_dist
        )
        if best_dist < CLUSTER_THRESHOLD and not closer_to_you:
            reclassified[i] = best_label
        else:
            true_mic_indices.append(i)

    mic_labels = _embed_and_cluster(mic_audio, mic_sr, segments, true_mic_indices, min_rms=MIN_EMBED_RMS)

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

        # _embed_and_cluster's own consolidation pass requires the smaller
        # cluster to look like a minority fragment (see _is_fragment) —
        # the right call for telling two real, different people apart,
        # but too strict here: the mic-side prior is fundamentally
        # different, since almost all mic audio genuinely is the user
        # regardless of how big a second cluster is, unless it's clearly
        # a different voice. Without this, a real second mic-side
        # cluster of the user's own voice (moving relative to the mic,
        # volume changes) stayed its own "Speaker N" and the transcript
        # showed the same person as both "You" and a numbered speaker.
        #
        # So: fold any other mic cluster into You whenever it's close
        # enough, with no size requirement — but "close enough" here is
        # CLUSTER_THRESHOLD, not the more lenient MERGE_THRESHOLD the
        # general pass uses. Real measured same-person variance (the
        # same voice at two different volumes/tones) lands around 0.22 -
        # nowhere near even 0.7 - because a centroid comparison averages
        # away the noise that made the *initial* pairwise-average-linkage
        # clustering split them in the first place. That's plenty of
        # room to catch a genuine same-person split without reaching for
        # MERGE_THRESHOLD's extra leniency, which risked folding in a
        # real in-person guest who just happens to sound somewhat
        # similar. If a real same-person split ever needs more room than
        # this catches, that's a real signal to revisit - not something
        # to pre-emptively loosen for.
        mic_centroids = _cluster_centroids(
            mic_audio, mic_sr, segments, true_mic_indices, mic_labels, min_rms=MIN_EMBED_RMS
        )
        you_centroid = mic_centroids.get(you_cluster)
        if you_centroid is not None:
            for label, centroid in mic_centroids.items():
                if label == you_cluster:
                    continue
                if _cosine_distance(centroid, you_centroid) < CLUSTER_THRESHOLD:
                    for i in list(mic_labels):
                        if mic_labels[i] == label:
                            mic_labels[i] = you_cluster

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
