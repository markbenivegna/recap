const recordBtn = document.getElementById("recordBtn");
const muteBtn = document.getElementById("muteBtn");
const fileInput = document.getElementById("fileInput");
const timerEl = document.getElementById("timer");
const recordingDotEl = document.getElementById("recordingDot");
const statusEl = document.getElementById("status");
const statusTextEl = document.getElementById("statusText");
const statusSpinnerEl = document.getElementById("statusSpinner");
const emptyEl = document.getElementById("empty");
const recordingAnimationEl = document.getElementById("recordingAnimation");
const recordingAnimationCanvas = document.getElementById("recordingAnimationCanvas");
const recordingAnimationTextEl = document.getElementById("recordingAnimationText");
const resultsEl = document.getElementById("results");
const transcribeErrorEl = document.getElementById("transcribeError");
const transcribeErrorTextEl = document.getElementById("transcribeErrorText");
const retryTranscribeBtn = document.getElementById("retryTranscribeBtn");
const transcribeErrorStartOverBtn = document.getElementById("transcribeErrorStartOverBtn");
const speakerEditBar = document.getElementById("speakerEditBar");
const speakerEditText = document.getElementById("speakerEditText");
const speakerUndoBtn = document.getElementById("speakerUndoBtn");
const regenerateNotesBtn = document.getElementById("regenerateNotesBtn");
const speakerMenu = document.getElementById("speakerMenu");
const coverageBar = document.getElementById("coverageBar");
const coverageList = document.getElementById("coverageList");
const coverageAddBtn = document.getElementById("coverageAddBtn");
const coverageDismissBtn = document.getElementById("coverageDismissBtn");
const cfgSummaryDetail = document.getElementById("cfgSummaryDetail");
const cfgSummaryDetailValue = document.getElementById("cfgSummaryDetailValue");
const meetingTitleEl = document.getElementById("meetingTitle");
const summaryContent = document.getElementById("summaryContent");
const notesContent = document.getElementById("notesContent");
const transcriptContent = document.getElementById("transcriptContent");
const notionSelect = document.getElementById("notionSelect");
const fileBtn = document.getElementById("fileBtn");
const splitBtn = fileBtn.closest(".split-btn");

// Drives the caret/select's disabled look via a JS-toggled class rather
// than a CSS :has() selector — :has() should work, but a WebKit-specific
// rendering quirk kept the caret looking enabled even when the button
// itself was disabled, so this sidesteps that dependency entirely.
function setFileBtnDisabled(disabled) {
  fileBtn.disabled = disabled;
  notionSelect.disabled = disabled;
  splitBtn.classList.toggle("split-btn-disabled", disabled);
}
const downloadBtn = document.getElementById("downloadBtn");
const fileStatus = document.getElementById("fileStatus");
const newRecordingBtn = document.getElementById("newRecordingBtn");
const uploadLabel = document.getElementById("uploadLabel");
const notionFileGroup = document.getElementById("notionFileGroup");
const notionHint = document.getElementById("notionHint");

let notionConfigured = false;

function applyNotionConfigured(isConfigured) {
  notionConfigured = isConfigured;
  notionFileGroup.hidden = !isConfigured;
  notionHint.hidden = isConfigured;
}
const settingsBtn = document.getElementById("settingsBtn");
const settingsModal = document.getElementById("settingsModal");
const settingsIntro = document.getElementById("settingsIntro");
const settingsForm = document.getElementById("settingsForm");
const settingsCloseBtn = document.getElementById("settingsCloseBtn");
const toastEl = document.getElementById("toast");
const toastTextEl = document.getElementById("toastText");
const cfgAnthropicKey = document.getElementById("cfgAnthropicKey");
const cfgNotionKey = document.getElementById("cfgNotionKey");
const cfgWhisperSize = document.getElementById("cfgWhisperSize");
const cfgVocabHints = document.getElementById("cfgVocabHints");
const cfgOutputDevice = document.getElementById("cfgOutputDevice");
const cfgSpendThreshold = document.getElementById("cfgSpendThreshold");
const cfgDiarizationThreshold = document.getElementById("cfgDiarizationThreshold");
const cfgDiarizationThresholdValue = document.getElementById("cfgDiarizationThresholdValue");
const cfgShowMenuBarIcon = document.getElementById("cfgShowMenuBarIcon");
const cfgDetectMeetings = document.getElementById("cfgDetectMeetings");
const cfgCheckUpdates = document.getElementById("cfgCheckUpdates");
const usageValueText = document.getElementById("usageValueText");
const usagePill = document.getElementById("usagePill");
const usageRingFill = document.getElementById("usageRingFill");
const usageSubtext = document.getElementById("usageSubtext");
const usageAlertBanner = document.getElementById("usageAlertBanner");
const usageAlertBannerText = document.getElementById("usageAlertBannerText");
const usageAlertBannerBtn = document.getElementById("usageAlertBannerBtn");
const usageResetBtn = document.getElementById("usageResetBtn");

const USAGE_RING_RADIUS = 27;
const USAGE_RING_CIRCUMFERENCE = 2 * Math.PI * USAGE_RING_RADIUS;
usageRingFill.style.strokeDasharray = `${USAGE_RING_CIRCUMFERENCE}`;
usageRingFill.style.strokeDashoffset = `${USAGE_RING_CIRCUMFERENCE}`;

let mediaRecorder = null;
let micRecorder = null;
let systemRecorder = null;
let recordedChunks = [];
let micChunks = [];
let systemChunks = [];
let recording = false;
let timerInterval = null;
let recordingStart = null;

// Wall-clock time the *current transcript's* recording actually started,
// so transcript timestamps can be shown aligned to real meeting time
// instead of just elapsed mm:ss. Set from `recordingStart` for a real
// recording; left null for an uploaded file, which has no meaningful
// "recording start" of its own.
let transcriptRecordingStart = null;

let lastResult = null; // { summary, notes, text, segments }
let lastFailedAudioArgs = null; // args to re-run handleAudioBlob with, for Retry

function setStatus(message, isError = false, showSpinner = false) {
  if (!message) {
    statusEl.hidden = true;
    return;
  }
  statusEl.hidden = false;
  statusTextEl.textContent = message;
  statusEl.classList.toggle("error", isError);
  statusSpinnerEl.hidden = !showSpinner;
}

const audioTipEl = document.getElementById("audioTip");
const audioTipIgnoreBtn = document.getElementById("audioTipIgnoreBtn");
const audioTipDismissBtn = document.getElementById("audioTipDismissBtn");

function saveConfigFlags(flags) {
  return fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(flags),
  }).catch(() => {});
}

// Shown when a recording starts without system audio (BlackHole missing or
// not wired up), since that silently means the other side of a call is not
// captured. The first time it only offers Dismiss; after that it also
// offers Ignore, which stops it for good. Anyone who has system audio
// working never sees it.
async function maybeShowAudioTip() {
  try {
    const res = await fetch("/api/settings");
    const cfg = await res.json();
    if (cfg.SYSTEM_AUDIO_TIP_IGNORED === "true") return;
    const seenBefore = cfg.SYSTEM_AUDIO_TIP_SEEN === "true";
    audioTipIgnoreBtn.hidden = !seenBefore;
    updateTipEl.hidden = true;
    audioTipEl.hidden = false;
    if (!seenBefore) saveConfigFlags({ SYSTEM_AUDIO_TIP_SEEN: "true" });
  } catch (err) {
    // The tip is a courtesy; never let it get in the way of recording.
  }
}

audioTipDismissBtn.addEventListener("click", () => {
  audioTipEl.hidden = true;
});
audioTipIgnoreBtn.addEventListener("click", () => {
  audioTipEl.hidden = true;
  saveConfigFlags({ SYSTEM_AUDIO_TIP_IGNORED: "true" });
});

const updateTipEl = document.getElementById("updateTip");
const updateTipTitleEl = document.getElementById("updateTipTitle");
const updateTipDownloadLink = document.getElementById("updateTipDownloadLink");
let pendingUpdateVersion = null;

// Runs once at launch. Only ever a notice with a download link, not an
// installer. Skipping a version stays quiet until an even newer one ships.
async function checkForUpdate(cfg) {
  if (cfg.CHECK_FOR_UPDATES === "false") return;
  try {
    const res = await fetch("/api/update-check");
    const info = await res.json();
    if (!info.update_available || info.latest === cfg.SKIPPED_UPDATE_VERSION) return;
    pendingUpdateVersion = info.latest;
    updateTipTitleEl.textContent = `Recap ${info.latest} is available (you have ${info.current})`;
    updateTipDownloadLink.href = info.url;
    // Don't stack on top of the recording tip.
    updateTipEl.hidden = !audioTipEl.hidden;
  } catch (err) {
    // A failed update check is never worth bothering anyone about.
  }
}

document.getElementById("updateTipLaterBtn").addEventListener("click", () => {
  updateTipEl.hidden = true;
});
document.getElementById("updateTipSkipBtn").addEventListener("click", () => {
  updateTipEl.hidden = true;
  saveConfigFlags({ SKIPPED_UPDATE_VERSION: pendingUpdateVersion });
});
updateTipDownloadLink.addEventListener("click", () => {
  updateTipEl.hidden = true;
});

let toastTimer = null;
function showToast(message, isError = false) {
  toastTextEl.textContent = message;
  toastEl.classList.toggle("error", isError);
  toastEl.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toastEl.hidden = true;
  }, 2500);
}

// Fills a panel with shimmer placeholder lines while its real content is
// still being generated, instead of leaving it visually empty behind the
// status banner's spinner — the last line is shorter to read as the tail
// of a paragraph rather than another full-width bar.
function renderSkeleton(el, lines = 3) {
  el.innerHTML = "";
  for (let i = 0; i < lines; i++) {
    const line = document.createElement("div");
    line.className = "skeleton-line";
    el.appendChild(line);
  }
}

function formatTimer(ms) {
  const totalSeconds = Math.floor(ms / 1000);
  const mins = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
  const secs = String(totalSeconds % 60).padStart(2, "0");
  return `${mins}:${secs}`;
}

function switchTab(tabName) {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tabName);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `tab-${tabName}`);
  });
}

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

function switchSettingsCategory(category) {
  document.querySelectorAll(".settings-nav-item").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.category === category);
  });
  document.querySelectorAll(".settings-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.category === category);
  });
}

document.querySelectorAll(".settings-nav-item").forEach((btn) => {
  btn.addEventListener("click", () => switchSettingsCategory(btn.dataset.category));
});

let activeStreams = [];
let liveMicStream = null;
let micMuted = false;
let recordingHasSystemAudio = false;
let audioCtx = null;
let micMeterAnalyser = null;
let micMeterTimer = null;

// Lazily loaded so the (relatively large) animation JSON is only fetched
// once someone actually hits Record, not on every app launch.
let recordingLottie = null;
let recordingAnimationTimer = null;
let recordingAnimationStart = 0;

// Lottie's own autoplay/loop ticks itself via requestAnimationFrame, which
// hits the exact same pywebview bug documented on startMicMeter() below:
// rAF can silently stall while the native window isn't considered
// "visible" even though it's genuinely on screen, then dumps a backlog of
// frames all at once when it resumes — the "fragmented and slow" look.
// Drive it ourselves on a setInterval instead, computing the target frame
// from wall-clock elapsed time (mod the clip length) so a delayed tick
// jumps straight to the correct frame instead of catching up frame-by-frame.
function driveRecordingAnimation() {
  if (!recordingLottie || !recordingLottie.isLoaded) return;
  const frameRate = recordingLottie.frameRate || 30;
  const totalFrames = recordingLottie.totalFrames || 1;
  const durationMs = (totalFrames / frameRate) * 1000;
  const elapsed = (performance.now() - recordingAnimationStart) % durationMs;
  recordingLottie.goToAndStop((elapsed / durationMs) * totalFrames, true);
}

function playRecordingAnimation(subtext) {
  recordingAnimationEl.hidden = false;
  recordingAnimationTextEl.textContent = subtext;
  recordingAnimationStart = performance.now();
  if (recordingAnimationTimer) clearInterval(recordingAnimationTimer);
  recordingAnimationTimer = setInterval(driveRecordingAnimation, 1000 / 30);
  if (recordingLottie) return;
  recordingLottie = lottie.loadAnimation({
    container: recordingAnimationCanvas,
    renderer: "svg",
    loop: false,
    autoplay: false,
    path: "assets/notes-document.json",
  });
}

function stopRecordingAnimation() {
  recordingAnimationEl.hidden = true;
  recordingAnimationTextEl.textContent = "";
  if (recordingAnimationTimer) {
    clearInterval(recordingAnimationTimer);
    recordingAnimationTimer = null;
  }
}

// Drives the mic icon's level fill (.mic-level in style.css) from the mic
// stream's loudness, so the one mic button is both the mute control and the
// "is it hearing me" meter.
function startMicMeter(stream) {
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  }
  micMeterAnalyser = audioCtx.createAnalyser();
  micMeterAnalyser.fftSize = 256;
  audioCtx.createMediaStreamSource(stream).connect(micMeterAnalyser);

  // One overall volume level (RMS of the time-domain signal) rather than
  // frequency bins: voice has almost no energy in the higher bins, so a
  // per-bin readout barely moved.
  //
  // Driven by setInterval, not requestAnimationFrame: rAF is spec'd to stop
  // firing whenever the page isn't considered "visible", and pywebview's
  // native window doesn't always wire up the Page Visibility API the way a
  // real browser tab does — so rAF can silently never run at all here, even
  // though the window is genuinely on screen. setInterval isn't gated by
  // that.
  const data = new Uint8Array(micMeterAnalyser.fftSize);

  function rms() {
    micMeterAnalyser.getByteTimeDomainData(data);
    let sumSquares = 0;
    for (let i = 0; i < data.length; i++) {
      const v = (data[i] - 128) / 128;
      sumSquares += v * v;
    }
    return Math.sqrt(sumSquares / data.length);
  }

  // A flat sqrt curve on raw RMS (a prior version of this) boosted quiet
  // levels so aggressively that ambient/background noise flickered the
  // meter too, while actual speech barely stood out above that already-
  // boosted floor. Calibrate to this room's actual ambient noise level for
  // the first ~500ms instead of guessing a fixed threshold — quiet vs
  // noisy rooms need different cutoffs for "is this your voice, or just
  // background sound" to work at all.
  let calibrating = true;
  const calibrationSamples = [];
  let noiseFloor = 0.01;
  setTimeout(() => {
    if (calibrationSamples.length) {
      const avg = calibrationSamples.reduce((a, b) => a + b, 0) / calibrationSamples.length;
      noiseFloor = avg * 1.6 + 0.005; // margin above the observed ambient level
    }
    calibrating = false;
  }, 500);

  micMeterTimer = setInterval(() => {
    const level = rms();
    if (calibrating) {
      calibrationSamples.push(level);
      return; // hold at empty while sampling ambient noise
    }
    const ceiling = Math.max(noiseFloor + 0.05, 0.22);
    const gated = Math.max(0, level - noiseFloor);
    const normalized = Math.min(1, gated / (ceiling - noiseFloor));
    setMicLevel(Math.sqrt(normalized));
  }, 60);
}

function setMicLevel(level) {
  muteBtn.style.setProperty("--mic-level", String(level));
}

function stopMicMeter() {
  if (micMeterTimer) {
    clearInterval(micMeterTimer);
    micMeterTimer = null;
  }
  micMeterAnalyser = null;
  setMicLevel(0);
}

async function findBlackHoleDeviceId() {
  // Device labels are blank until a getUserMedia call has been granted at
  // least once, so this must run after the mic permission is already live.
  const devices = await navigator.mediaDevices.enumerateDevices();
  const match = devices.find(
    (d) => d.kind === "audioinput" && /blackhole/i.test(d.label)
  );
  return match ? match.deviceId : null;
}

function recordingSubtext() {
  if (micMuted) {
    return recordingHasSystemAudio
      ? "Mic muted. Capturing system audio only."
      : "Mic muted. Nothing is being captured.";
  }
  return recordingHasSystemAudio ? "Capturing your mic and system audio." : "Capturing your mic.";
}

function setMicMuted(muted) {
  micMuted = muted;
  // A disabled track emits silence, so everything fed by the mic (the mix
  // and the separate mic-only recording) records silence while the
  // system-audio track keeps going, and all three recordings stay
  // time-aligned. Pausing the recorders instead would drop that span from
  // each file and shift every later timestamp.
  if (liveMicStream) liveMicStream.getAudioTracks().forEach((t) => (t.enabled = !muted));
  const label = muted ? "Unmute mic" : "Mute mic";
  muteBtn.title = label;
  muteBtn.setAttribute("aria-label", label);
  muteBtn.setAttribute("aria-pressed", String(muted));
  recordingDotEl.classList.toggle("muted", muted);
  recordingAnimationTextEl.textContent = recordingSubtext();
}

function resetMicMute() {
  micMuted = false;
  liveMicStream = null;
  muteBtn.hidden = true;
  muteBtn.title = "Mute mic";
  muteBtn.setAttribute("aria-label", "Mute mic");
  muteBtn.setAttribute("aria-pressed", "false");
  recordingDotEl.classList.remove("muted");
}

async function startRecording() {
  try {
    // Switch system audio output to the recording device (e.g. a
    // Multi-Output Device combining your speakers + BlackHole) before
    // grabbing the mic, so BlackHole is actually receiving audio by the
    // time we try to read from it below. No-ops quietly if not configured.
    try {
      await fetch("/api/audio/prepare-recording", { method: "POST" });
    } catch (err) {
      // Non-fatal — recording still works, just without the auto-switch.
    }

    // echoCancellation/noiseSuppression/autoGainControl default to true,
    // which engages a "voice processing" audio unit on macOS — once real
    // speech is detected on this stream, that can duck/suppress OTHER
    // concurrently-open audio inputs (like the separate BlackHole capture
    // below) for the rest of the session, to prevent echo. Disabling them
    // keeps this a plain, unprocessed capture that doesn't interfere with
    // the second device.
    const micStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    });
    activeStreams = [micStream];
    liveMicStream = micStream;

    let usingSystemAudio = false;
    let systemStream = null;
    const blackHoleId = await findBlackHoleDeviceId();
    let mixedStream = micStream;

    if (blackHoleId) {
      try {
        systemStream = await navigator.mediaDevices.getUserMedia({
          audio: { deviceId: { exact: blackHoleId }, echoCancellation: false, noiseSuppression: false, autoGainControl: false },
        });
        activeStreams.push(systemStream);

        // Mix mic + system audio (BlackHole) into a single stream so the
        // recording captures both sides of a call, not just your voice.
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const dest = audioCtx.createMediaStreamDestination();
        audioCtx.createMediaStreamSource(micStream).connect(dest);
        audioCtx.createMediaStreamSource(systemStream).connect(dest);
        mixedStream = dest.stream;
        usingSystemAudio = true;
      } catch (err) {
        // BlackHole device exists but couldn't be opened (e.g. not set as
        // part of a Multi-Output Device yet) — fall back to mic-only.
        mixedStream = micStream;
        systemStream = null;
      }
    }

    recordedChunks = [];
    micChunks = [];
    systemChunks = [];
    const stopPromises = [];

    mediaRecorder = new MediaRecorder(mixedStream);
    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) recordedChunks.push(e.data);
    };
    stopPromises.push(new Promise((resolve) => (mediaRecorder.onstop = resolve)));

    // Also record the mic and system-audio tracks separately (unmixed) when
    // both are present. These aren't used for transcription — the mixed
    // track stays the source of truth for that — but let the backend tell,
    // per transcript segment, whether it came from the mic (you) or system
    // audio (everyone else on the call), instead of relying purely on
    // voice similarity, which struggles when two voices sound alike.
    micRecorder = null;
    systemRecorder = null;
    if (usingSystemAudio) {
      micRecorder = new MediaRecorder(micStream);
      micRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) micChunks.push(e.data);
      };
      stopPromises.push(new Promise((resolve) => (micRecorder.onstop = resolve)));

      systemRecorder = new MediaRecorder(systemStream);
      systemRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) systemChunks.push(e.data);
      };
      stopPromises.push(new Promise((resolve) => (systemRecorder.onstop = resolve)));
    }

    Promise.all(stopPromises).then(() => {
      activeStreams.forEach((s) => s.getTracks().forEach((track) => track.stop()));
      activeStreams = [];
      if (audioCtx) {
        audioCtx.close();
        audioCtx = null;
      }
      fetch("/api/audio/restore", { method: "POST" }).catch(() => {});
      const blob = new Blob(recordedChunks, { type: "audio/webm" });
      const micBlob = micChunks.length ? new Blob(micChunks, { type: "audio/webm" }) : null;
      const systemBlob = systemChunks.length ? new Blob(systemChunks, { type: "audio/webm" }) : null;
      handleAudioBlob(blob, "recording.webm", micBlob, systemBlob, recordingStart);
    });

    mediaRecorder.start();
    if (micRecorder) micRecorder.start();
    if (systemRecorder) systemRecorder.start();
    recording = true;
    emptyEl.hidden = true;
    // Belt-and-suspenders reset: a prior recording that errored out (e.g.
    // nothing to transcribe) should already leave #results hidden, but
    // starting fresh here regardless means any stale results/failed-banner
    // state left over from an earlier failure can never bleed into a new
    // recording, no matter how it got left that way.
    resultsEl.hidden = true;
    newRecordingBtn.hidden = true;
    recordingHasSystemAudio = usingSystemAudio;
    micMuted = false;
    playRecordingAnimation(recordingSubtext());
    muteBtn.hidden = false;
    setMicMuted(false);
    if (!usingSystemAudio) maybeShowAudioTip();
    recordingStart = Date.now();
    recordBtn.textContent = "Stop";
    recordBtn.classList.add("recording");
    uploadLabel.hidden = true;
    recordingDotEl.hidden = false;
    timerEl.hidden = false;
    timerInterval = setInterval(() => {
      timerEl.textContent = formatTimer(Date.now() - recordingStart);
    }, 250);
    startMicMeter(micStream);
    setStatus("");
  } catch (err) {
    setStatus(`Could not access microphone: ${err.message}`, true);
  }
}

function stopRecording() {
  if (mediaRecorder && recording) {
    stopMicMeter();
    stopRecordingAnimation();
    [mediaRecorder, micRecorder, systemRecorder].forEach((r) => {
      if (r && r.state !== "inactive") r.stop();
    });
    recording = false;
    resetMicMute();
    recordBtn.textContent = "Record";
    recordBtn.classList.remove("recording");
    clearInterval(timerInterval);
    recordingDotEl.hidden = true;
    timerEl.hidden = true;
  }
}

muteBtn.addEventListener("click", () => {
  if (recording) setMicMuted(!micMuted);
});

recordBtn.addEventListener("click", () => {
  if (recording) {
    stopRecording();
  } else {
    startRecording();
  }
});

fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];
  if (file) {
    handleAudioBlob(file, file.name, null, null);
  }
  fileInput.value = "";
});

function showIdleControls(show) {
  recordBtn.hidden = !show;
  uploadLabel.hidden = !show;
}

function resetToNewRecording() {
  lastResult = null;
  speakerMergeHistory = [];
  renderSpeakerEditBar();
  closeSpeakerMenu();
  hideCoverageBar();
  lastFailedAudioArgs = null;
  resultsEl.hidden = true;
  transcribeErrorEl.hidden = true;
  newRecordingBtn.hidden = true;
  showIdleControls(true);
  emptyEl.hidden = false;
  meetingTitleEl.hidden = true;
  meetingTitleEl.textContent = "";
  summaryContent.textContent = "";
  notesContent.textContent = "";
  transcriptContent.innerHTML = "";
  notionSelect.innerHTML = '<option value="">Loading pages...</option>';
  setFileBtnDisabled(true);
  downloadBtn.disabled = true;
  fileStatus.textContent = "";
  switchTab("summary");
  setStatus("");
}

newRecordingBtn.addEventListener("click", resetToNewRecording);

async function handleAudioBlob(blob, filename, micBlob, systemBlob, startedAt = null) {
  transcriptRecordingStart = startedAt;
  emptyEl.hidden = true;
  transcribeErrorEl.hidden = true;
  stopRecordingAnimation();
  resultsEl.hidden = false;
  newRecordingBtn.hidden = true;
  showIdleControls(false);
  downloadBtn.disabled = true;
  setStatus("Transcribing locally (this can take a minute)...", false, true);
  // A fast failure (e.g. nothing usable was recorded) can come back in well
  // under a second — rendering the skeleton immediately meant it flashed in
  // and got yanked out again in that same instant, reading as a glitch
  // rather than a loading state. Delaying it means a fast round trip never
  // shows it at all; only a real wait does.
  const skeletonTimer = setTimeout(() => {
    renderSkeleton(summaryContent);
    renderSkeleton(notesContent);
    renderSkeleton(transcriptContent, 5);
  }, 500);

  const formData = new FormData();
  formData.append("audio", blob, filename);
  if (micBlob) formData.append("mic_audio", micBlob, "mic.webm");
  if (systemBlob) formData.append("system_audio", systemBlob, "system.webm");

  try {
    const res = await fetch("/api/transcribe", { method: "POST", body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Transcription failed");

    clearTimeout(skeletonTimer);
    renderTranscript(data);
    setStatus("Transcript ready. Generating summary...", false, true);
    await generateSummary(data.text);
  } catch (err) {
    // Transcription itself failed (e.g. nothing usable was recorded, or a
    // real backend error). Previously this landed on the normal Record/
    // Upload toolbar with an empty, still-visible #results panel behind an
    // error banner — a dead-end-looking screen with a full set of controls
    // that don't actually do anything useful about the failure in front of
    // you. A dedicated error state with a Retry button is more honest about
    // what actually happened and what to do about it: re-run the exact
    // same request (stored below) without needing to re-record or
    // re-select the file.
    clearTimeout(skeletonTimer);
    summaryContent.innerHTML = "";
    notesContent.innerHTML = "";
    transcriptContent.innerHTML = "";
    setStatus("");
    lastFailedAudioArgs = { blob, filename, micBlob, systemBlob, startedAt };
    resultsEl.hidden = true;
    transcribeErrorTextEl.textContent = err.message;
    transcribeErrorEl.hidden = false;
  }
}

retryTranscribeBtn.addEventListener("click", () => {
  if (!lastFailedAudioArgs) return;
  const { blob, filename, micBlob, systemBlob, startedAt } = lastFailedAudioArgs;
  handleAudioBlob(blob, filename, micBlob, systemBlob, startedAt);
});

transcribeErrorStartOverBtn.addEventListener("click", resetToNewRecording);

function renderTranscript(data) {
  lastResult = { ...lastResult, text: data.text, segments: data.segments };
  speakerMergeHistory = [];
  renderSpeakerEditBar();
  redrawTranscript();
  switchTab("transcript");
}

function redrawTranscript() {
  transcriptContent.innerHTML = "";
  let lastSpeaker = null;
  lastResult.segments.forEach((seg) => {
    const div = document.createElement("div");
    div.className = "transcript-segment";

    const timeSpan = document.createElement("span");
    timeSpan.className = "transcript-time";
    const mins = String(Math.floor(seg.start / 60)).padStart(2, "0");
    const secs = String(Math.floor(seg.start % 60)).padStart(2, "0");
    const elapsed = `${mins}:${secs}`;
    if (transcriptRecordingStart) {
      // Aligned to when the meeting actually started, not just elapsed
      // time into the recording — a real recording has a real wall-clock
      // start time to anchor to; an uploaded file doesn't, so it always
      // falls back to plain elapsed time instead.
      const wallClock = new Date(transcriptRecordingStart + seg.start * 1000);
      timeSpan.textContent = wallClock.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
      timeSpan.title = `${elapsed} into the recording`;
    } else {
      timeSpan.textContent = elapsed;
    }
    div.appendChild(timeSpan);

    if (seg.speaker && seg.speaker !== lastSpeaker) {
      div.appendChild(makeSpeakerLabel(seg.speaker));
      lastSpeaker = seg.speaker;
    }

    div.appendChild(document.createTextNode(seg.text));
    transcriptContent.appendChild(div);
  });
}

// --- Merging speaker labels -------------------------------------------
// Clustering can split one real person into two labels, and no threshold
// reliably tells that apart from two similar-sounding people, so the user,
// who knows who was in the meeting, gets to fix it by hand.
let speakerMergeHistory = []; // newest last: { from, to, indices }
let notesRegenerating = false;

// Same turn-building as format_transcript_with_speakers in the backend:
// consecutive segments from one speaker join into one turn, empty ones are
// skipped. The text sent to the summarizer, Notion and Markdown export is
// built from this, so it has to be rebuilt after every merge.
function formatTranscriptText(segments) {
  const turns = [];
  for (const seg of segments) {
    const text = (seg.text || "").trim();
    if (!text) continue;
    const last = turns[turns.length - 1];
    if (last && last.speaker === seg.speaker) last.text += " " + text;
    else turns.push({ speaker: seg.speaker, text });
  }
  return turns.map((t) => (t.speaker ? `${t.speaker}: ${t.text}` : t.text)).join("\n\n");
}

function makeSpeakerLabel(speaker) {
  // "You" is anchored to the mic recording itself, not a guess, so it can't
  // be merged away. Every other label is a guess worth correcting.
  if (speaker === "You") {
    const span = document.createElement("span");
    span.className = "transcript-speaker";
    span.textContent = `${speaker}: `;
    return span;
  }
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "transcript-speaker transcript-speaker-btn";
  btn.textContent = `${speaker}:`;
  btn.title = "Merge into another speaker";
  btn.setAttribute("aria-haspopup", "menu");
  btn.addEventListener("click", () => openSpeakerMenu(btn, speaker));
  return btn;
}

function closeSpeakerMenu() {
  speakerMenu.hidden = true;
}

function openSpeakerMenu(anchor, from) {
  if (notesRegenerating) return;
  const others = [...new Set(lastResult.segments.map((s) => s.speaker).filter((n) => n && n !== from))];
  if (!others.length) return;

  speakerMenu.innerHTML = "";
  const title = document.createElement("div");
  title.className = "speaker-menu-title";
  title.textContent = `Merge ${from} into`;
  speakerMenu.appendChild(title);
  others.forEach((name) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "speaker-menu-item";
    item.setAttribute("role", "menuitem");
    item.textContent = name;
    item.addEventListener("click", () => {
      closeSpeakerMenu();
      mergeSpeaker(from, name);
    });
    speakerMenu.appendChild(item);
  });

  speakerMenu.hidden = false;
  const rect = anchor.getBoundingClientRect();
  const menuRect = speakerMenu.getBoundingClientRect();
  let left = rect.left;
  let top = rect.bottom + 4;
  if (left + menuRect.width > window.innerWidth - 8) left = window.innerWidth - menuRect.width - 8;
  if (top + menuRect.height > window.innerHeight - 8) top = rect.top - menuRect.height - 4;
  speakerMenu.style.left = `${Math.max(8, left)}px`;
  speakerMenu.style.top = `${Math.max(8, top)}px`;
  speakerMenu.querySelector(".speaker-menu-item").focus();
}

function renderSpeakerEditBar() {
  if (!speakerMergeHistory.length) {
    speakerEditBar.hidden = true;
    return;
  }
  const last = speakerMergeHistory[speakerMergeHistory.length - 1];
  speakerEditText.textContent = `Merged ${last.from} into ${last.to}. The summary and notes still use the old speakers.`;
  speakerEditBar.hidden = false;
}

function afterSpeakerEdit() {
  lastResult.text = formatTranscriptText(lastResult.segments);
  const scrollTop = transcriptContent.scrollTop;
  redrawTranscript();
  transcriptContent.scrollTop = scrollTop;
  renderSpeakerEditBar();
}

function mergeSpeaker(from, to) {
  const indices = [];
  lastResult.segments.forEach((seg, i) => {
    if (seg.speaker === from) {
      seg.speaker = to;
      indices.push(i);
    }
  });
  if (!indices.length) return;
  speakerMergeHistory.push({ from, to, indices });
  afterSpeakerEdit();
}

function undoSpeakerMerge() {
  const last = speakerMergeHistory.pop();
  if (!last) return;
  last.indices.forEach((i) => {
    lastResult.segments[i].speaker = last.from;
  });
  afterSpeakerEdit();
}

document.addEventListener("mousedown", (e) => {
  if (!speakerMenu.hidden && !speakerMenu.contains(e.target)) closeSpeakerMenu();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !speakerMenu.hidden) closeSpeakerMenu();
});
transcriptContent.addEventListener("scroll", closeSpeakerMenu);
window.addEventListener("resize", closeSpeakerMenu);
speakerUndoBtn.addEventListener("click", undoSpeakerMerge);

regenerateNotesBtn.addEventListener("click", async () => {
  if (notesRegenerating || !lastResult) return;
  notesRegenerating = true;
  speakerUndoBtn.disabled = true;
  regenerateNotesBtn.disabled = true;
  setStatus("Regenerating notes...", false, true);
  const ok = await generateSummary(lastResult.text, { regenerating: true });
  notesRegenerating = false;
  speakerUndoBtn.disabled = false;
  regenerateNotesBtn.disabled = false;
  // Once the notes match the transcript again there is nothing left to
  // undo or regenerate. On failure the merges stay, so it can be retried.
  if (ok) {
    speakerMergeHistory = [];
    renderSpeakerEditBar();
  }
});

// --- Notes coverage warning ---------------------------------------------
// A summary can finish normally and still leave a whole topic out. The
// backend audits the finished notes against the transcript and returns what
// looks missing; this shows it, and lets the user add just those topics.
const SUMMARY_DETAIL_LEVELS = ["quick", "balanced", "detailed"];
const SUMMARY_DETAIL_LABELS = ["Quick", "Balanced", "Detailed"];
let coverageTopics = [];

function showCoverageBar(topics) {
  coverageTopics = topics;
  coverageList.innerHTML = "";
  topics.forEach((t) => {
    const li = document.createElement("li");
    const name = document.createElement("strong");
    name.textContent = t.topic;
    li.appendChild(name);
    if (t.detail) li.appendChild(document.createTextNode(`: ${t.detail}`));
    coverageList.appendChild(li);
  });
  coverageBar.hidden = topics.length === 0;
  coverageAddBtn.disabled = false;
  coverageDismissBtn.disabled = false;
}

function hideCoverageBar() {
  coverageTopics = [];
  coverageBar.hidden = true;
}

coverageDismissBtn.addEventListener("click", hideCoverageBar);

coverageAddBtn.addEventListener("click", async () => {
  if (!lastResult || !coverageTopics.length) return;
  coverageAddBtn.disabled = true;
  coverageDismissBtn.disabled = true;
  setStatus("Adding the missing topics to the notes...", false, true);
  try {
    const res = await fetch("/api/summarize/add-topics", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transcript: lastResult.text, notes: lastResult.notes, topics: coverageTopics }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Couldn't add topics");

    const count = coverageTopics.length;
    lastResult.notes = `${lastResult.notes}\n\n${data.addendum}`;
    notesContent.textContent = lastResult.notes;
    hideCoverageBar();
    setStatus("");
    switchTab("notes");
    showToast(`Added ${count} ${count === 1 ? "topic" : "topics"} to the notes`);
  } catch (err) {
    setStatus(`Couldn't add the topics: ${err.message}`, true);
    coverageAddBtn.disabled = false;
    coverageDismissBtn.disabled = false;
  }
});

// `regenerating` is for redoing the notes on an already-shown result (after
// merging speakers): the existing summary and notes stay on screen until the
// new ones arrive, and a failure leaves them alone instead of clearing them.
async function generateSummary(transcriptText, { regenerating = false } = {}) {
  hideCoverageBar();
  const skeletonTimer = setTimeout(() => {
    if (regenerating) return;
    renderSkeleton(summaryContent);
    renderSkeleton(notesContent);
  }, 500);
  try {
    const res = await fetch("/api/summarize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transcript: transcriptText }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Summarization failed");

    clearTimeout(skeletonTimer);
    lastResult.title = data.title;
    lastResult.summary = data.summary;
    lastResult.notes = data.notes;
    showCoverageBar(data.missing_topics || []);
    summaryContent.textContent = data.summary;
    notesContent.textContent = data.notes;
    if (data.title) {
      meetingTitleEl.textContent = data.title;
      meetingTitleEl.hidden = false;
    }
    switchTab("summary");
    // A truncated summary isn't a failure (everything up to the cutoff is
    // real and usable), but it may be silently missing something like a
    // deadline mentioned late in a long meeting — worth a visible, sticky
    // warning rather than the normal empty/cleared status, so it isn't
    // mistaken for a complete, trustworthy result.
    setStatus(
      data.truncated ? "Summary may be incomplete — the meeting was long enough to hit the response limit." : "",
      Boolean(data.truncated),
    );
    newRecordingBtn.hidden = false;
    downloadBtn.disabled = false;
    // Reloading the page list resets the chosen destination to the first
    // one, which would undo the user's pick just for redoing the notes.
    if (notionConfigured && !regenerating) loadNotionPages();
    checkUsageAlert();
    return true;
  } catch (err) {
    clearTimeout(skeletonTimer);
    if (regenerating) {
      setStatus(`Couldn't regenerate notes: ${err.message}`, true);
      return false;
    }
    summaryContent.textContent = "";
    notesContent.textContent = "";
    setStatus(`Summary error: ${err.message}`, true);
    showIdleControls(true);
    return false;
  }
}

function updateFileBtnLabel() {
  const selected = notionSelect.options[notionSelect.selectedIndex];
  fileBtn.textContent = selected && selected.value ? `File to ${selected.textContent}` : "File to Notion";
}

async function loadNotionPages() {
  notionSelect.innerHTML = '<option value="">Loading pages...</option>';
  setFileBtnDisabled(true);
  try {
    const res = await fetch("/api/notion/pages");
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to load Notion pages");

    // No placeholder option — the select defaults to its first entry, so
    // filing always defaults to the first page. The select itself is just
    // the caret half of a split button for changing that destination.
    notionSelect.innerHTML = "";
    data.pages.forEach((page) => {
      const opt = document.createElement("option");
      opt.value = page.id;
      opt.dataset.type = page.type;
      opt.textContent = page.type === "database" ? `${page.title} (database)` : page.title;
      notionSelect.appendChild(opt);
    });
    setFileBtnDisabled(data.pages.length === 0);
    if (data.pages.length === 0) {
      notionSelect.innerHTML = '<option value="">No pages shared</option>';
    }
    // Only one destination — there's nothing to actually choose between,
    // so drop the caret/dropdown entirely and just show a plain button.
    splitBtn.classList.toggle("split-btn-single", data.pages.length === 1);
    updateFileBtnLabel();
  } catch (err) {
    notionSelect.innerHTML = '<option value="">Unavailable</option>';
    setFileBtnDisabled(true);
    splitBtn.classList.remove("split-btn-single");
    fileStatus.textContent = err.message;
  }
}

notionSelect.addEventListener("change", updateFileBtnLabel);

fileBtn.addEventListener("click", async () => {
  if (!notionSelect.value || !lastResult) return;
  setFileBtnDisabled(true);
  fileStatus.textContent = "Filing to Notion...";
  const selectedOption = notionSelect.options[notionSelect.selectedIndex];
  try {
    const res = await fetch("/api/notion/file", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        parent_id: notionSelect.value,
        parent_type: selectedOption ? selectedOption.dataset.type : "page",
        title: lastResult.title,
        summary: lastResult.summary,
        notes: lastResult.notes,
        transcript: lastResult.text,
        recorded_at: transcriptRecordingStart,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Filing failed");
    fileStatus.textContent = "Filed to Notion.";
    if (data.url) {
      const link = document.createElement("a");
      link.href = data.url;
      link.textContent = "Open page";
      link.target = "_blank";
      fileStatus.appendChild(link);
    }
  } catch (err) {
    fileStatus.textContent = `Error: ${err.message}`;
    setFileBtnDisabled(false);
  }
});

function computeUsageStatus(data) {
  const cost = data.total_cost_usd || 0;
  const threshold = data.alert_threshold;
  const hasThreshold = typeof threshold === "number" && threshold > 0;
  const pct = hasThreshold ? Math.min(100, (cost / threshold) * 100) : 0;
  const over = hasThreshold && cost >= threshold;
  const near = hasThreshold && !over && pct >= 80;
  return { cost, threshold, hasThreshold, pct, near, over };
}

async function fetchUsage() {
  const res = await fetch("/api/usage");
  return res.json();
}

async function loadUsageDisplay() {
  try {
    const data = await fetchUsage();
    const { cost, threshold, hasThreshold, pct, near, over } = computeUsageStatus(data);
    usageValueText.textContent = `$${cost.toFixed(2)}`;

    usageRingFill.style.strokeDashoffset = `${USAGE_RING_CIRCUMFERENCE * (1 - pct / 100)}`;
    usageRingFill.classList.toggle("over-threshold", over);
    usageRingFill.classList.toggle("near-threshold", near);
    usagePill.classList.toggle("over-threshold", over);
    usagePill.classList.toggle("near-threshold", near);
    usagePill.textContent = hasThreshold ? `${Math.round(pct)}% used` : "No limit set";
    const summaryCount = data.call_count || 0;
    const summaryCountText = `${summaryCount} ${summaryCount === 1 ? "summary" : "summaries"}`;
    let statusSuffix = "";
    if (over) statusSuffix = " — exceeded";
    else if (near) statusSuffix = " — approaching";
    usageSubtext.textContent = hasThreshold
      ? `${summaryCountText} so far, $${threshold.toFixed(2)} threshold${statusSuffix}`
      : `${summaryCountText} so far`;
  } catch (err) {
    usageValueText.textContent = "—";
  }
}

async function checkUsageAlert() {
  try {
    const data = await fetchUsage();
    const { threshold, near, over } = computeUsageStatus(data);
    if (!near && !over) {
      usageAlertBanner.hidden = true;
      return;
    }
    usageAlertBanner.hidden = false;
    usageAlertBanner.classList.toggle("over-threshold", over);
    usageAlertBannerText.textContent = over
      ? `You've passed your $${threshold.toFixed(2)} spend alert threshold.`
      : `Approaching your $${threshold.toFixed(2)} spend alert threshold.`;
  } catch (err) {
    // Non-fatal — the banner just won't show.
  }
}

async function openSettings({ isFirstRun = false } = {}) {
  settingsIntro.hidden = !isFirstRun;
  switchSettingsCategory(isFirstRun ? "api-keys" : "general");
  try {
    const res = await fetch("/api/settings");
    const data = await res.json();
    cfgAnthropicKey.value = data.ANTHROPIC_API_KEY || "";
    cfgNotionKey.value = data.NOTION_API_KEY || "";
    cfgWhisperSize.value = data.WHISPER_MODEL_SIZE || "small";
    cfgVocabHints.value = data.VOCABULARY_HINTS || "";
    cfgOutputDevice.value = data.RECORDING_OUTPUT_DEVICE || "";
    cfgSpendThreshold.value = data.SPEND_ALERT_THRESHOLD || "";
    cfgDiarizationThreshold.value = data.DIARIZATION_THRESHOLD || "0.7";
    cfgDiarizationThresholdValue.textContent = Number(cfgDiarizationThreshold.value).toFixed(2);
    const detailIndex = SUMMARY_DETAIL_LEVELS.indexOf(data.SUMMARY_DETAIL_LEVEL);
    cfgSummaryDetail.value = String(detailIndex === -1 ? 1 : detailIndex);
    cfgSummaryDetailValue.textContent = SUMMARY_DETAIL_LABELS[cfgSummaryDetail.value];
    cfgShowMenuBarIcon.checked = data.SHOW_MENU_BAR_ICON !== "false";
    cfgDetectMeetings.checked = data.DETECT_MEETINGS !== "false";
    cfgCheckUpdates.checked = data.CHECK_FOR_UPDATES !== "false";
    loadUsageDisplay();
  } catch (err) {
    showToast(`Could not load current settings: ${err.message}`, true);
  }
  settingsModal.hidden = false;
  settingsModal.querySelector(".settings-panels").scrollTop = 0;
}

function closeSettings() {
  settingsModal.hidden = true;
}

settingsBtn.addEventListener("click", () => openSettings());
settingsCloseBtn.addEventListener("click", closeSettings);

// No Save button — each field saves itself as soon as you leave it (or,
// for a select, as soon as you pick something), like any other native
// settings screen. The toast is the only confirmation that a save happened.
settingsForm.addEventListener("submit", (e) => e.preventDefault());

async function saveSettings() {
  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ANTHROPIC_API_KEY: cfgAnthropicKey.value.trim(),
        NOTION_API_KEY: cfgNotionKey.value.trim(),
        WHISPER_MODEL_SIZE: cfgWhisperSize.value,
        VOCABULARY_HINTS: cfgVocabHints.value.trim(),
        RECORDING_OUTPUT_DEVICE: cfgOutputDevice.value.trim(),
        SPEND_ALERT_THRESHOLD: cfgSpendThreshold.value.trim(),
        DIARIZATION_THRESHOLD: cfgDiarizationThreshold.value,
        SUMMARY_DETAIL_LEVEL: SUMMARY_DETAIL_LEVELS[Number(cfgSummaryDetail.value)],
        SHOW_MENU_BAR_ICON: String(cfgShowMenuBarIcon.checked),
        DETECT_MEETINGS: String(cfgDetectMeetings.checked),
        CHECK_FOR_UPDATES: String(cfgCheckUpdates.checked),
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Save failed");
    applyNotionConfigured(Boolean(cfgNotionKey.value.trim()));
    if (notionConfigured && lastResult && resultsEl.hidden === false) loadNotionPages();
    loadUsageDisplay();
    showToast("Settings saved");
  } catch (err) {
    showToast(`Error: ${err.message}`, true);
  }
}

[
  cfgAnthropicKey,
  cfgNotionKey,
  cfgWhisperSize,
  cfgVocabHints,
  cfgOutputDevice,
  cfgSpendThreshold,
  cfgDiarizationThreshold,
  cfgSummaryDetail,
  cfgShowMenuBarIcon,
  cfgDetectMeetings,
  cfgCheckUpdates,
].forEach((el) => {
  el.addEventListener("change", saveSettings);
});

// Live-update the numeric label while dragging — "change" (used above for
// autosave) only fires once you let go, but the label should track the
// thumb in real time.
cfgDiarizationThreshold.addEventListener("input", () => {
  cfgDiarizationThresholdValue.textContent = Number(cfgDiarizationThreshold.value).toFixed(2);
});
cfgSummaryDetail.addEventListener("input", () => {
  cfgSummaryDetailValue.textContent = SUMMARY_DETAIL_LABELS[cfgSummaryDetail.value];
});

// First-run: if the essential keys aren't set yet, open Settings
// automatically instead of leaving the user to discover the gear icon.
// Also drives whether the Notion UI shows at all — it's an optional
// destination (Save Markdown always works without it), so there's no
// reason to show a picker that can only ever say "Unavailable".
(async function checkFirstRun() {
  try {
    const res = await fetch("/api/settings");
    const data = await res.json();
    applyNotionConfigured(Boolean(data.NOTION_API_KEY));
    if (!data.ANTHROPIC_API_KEY) {
      openSettings({ isFirstRun: true });
    }
    checkForUpdate(data);
  } catch (err) {
    // Non-fatal — settings just won't auto-open.
  }
  checkUsageAlert();
})();

usageAlertBannerBtn.addEventListener("click", () => openSettings());

usageResetBtn.addEventListener("click", async () => {
  if (!confirm("Reset tracked spend and summary count back to $0? This can't be undone.")) return;
  try {
    const res = await fetch("/api/usage/reset", { method: "POST" });
    if (!res.ok) throw new Error("Reset failed");
    loadUsageDisplay();
    checkUsageAlert();
    showToast("Usage reset");
  } catch (err) {
    showToast(`Error: ${err.message}`, true);
  }
});

downloadBtn.addEventListener("click", async () => {
  if (!lastResult) return;
  downloadBtn.disabled = true;
  fileStatus.textContent = "Choose where to save...";
  try {
    const res = await fetch("/api/download-markdown", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: lastResult.title,
        summary: lastResult.summary,
        notes: lastResult.notes,
        transcript: lastResult.text,
        recorded_at: transcriptRecordingStart,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Save failed");
    fileStatus.textContent = data.cancelled ? "" : `Saved to ${data.path}`;
  } catch (err) {
    fileStatus.textContent = `Error: ${err.message}`;
  } finally {
    downloadBtn.disabled = false;
  }
});
