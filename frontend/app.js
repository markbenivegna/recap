const recordBtn = document.getElementById("recordBtn");
const fileInput = document.getElementById("fileInput");
const timerEl = document.getElementById("timer");
const recordingDotEl = document.getElementById("recordingDot");
const waveformEl = document.getElementById("waveform");
const waveformBars = waveformEl.querySelectorAll(".waveform-bar");
const statusEl = document.getElementById("status");
const statusTextEl = document.getElementById("statusText");
const statusSpinnerEl = document.getElementById("statusSpinner");
const emptyEl = document.getElementById("empty");
const resultsEl = document.getElementById("results");
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

let lastResult = null; // { summary, notes, text, segments }

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

let activeStreams = [];
let audioCtx = null;
let waveformAnalyser = null;
let waveformTimer = null;

function startWaveform(stream) {
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  }
  waveformAnalyser = audioCtx.createAnalyser();
  waveformAnalyser.fftSize = 256;
  audioCtx.createMediaStreamSource(stream).connect(waveformAnalyser);

  // Frequency-bin-per-bar (an earlier approach) meant most bars landed on
  // higher-frequency bins where voice has almost no energy, so only the
  // first bar ever visibly moved. Use one overall volume level (RMS of the
  // time-domain signal) instead, applied to every bar with a small fixed
  // per-bar multiplier for natural-looking variation — all bars react
  // together to actual signal.
  //
  // Driven by setInterval, not requestAnimationFrame: rAF is spec'd to stop
  // firing whenever the page isn't considered "visible", and pywebview's
  // native window doesn't always wire up the Page Visibility API the way a
  // real browser tab does — so rAF can silently never run at all here, even
  // though the window is genuinely on screen. setInterval isn't gated by
  // that.
  const barMultipliers = Array.from(waveformBars, () => 0.7 + Math.random() * 0.6);
  const data = new Uint8Array(waveformAnalyser.fftSize);
  const MIN_HEIGHT = 4;
  const MAX_HEIGHT = 32;

  function rms() {
    waveformAnalyser.getByteTimeDomainData(data);
    let sumSquares = 0;
    for (let i = 0; i < data.length; i++) {
      const v = (data[i] - 128) / 128;
      sumSquares += v * v;
    }
    return Math.sqrt(sumSquares / data.length);
  }

  // A flat sqrt curve on raw RMS (a prior version of this) boosted quiet
  // levels so aggressively that ambient/background noise flickered the
  // bars too, while actual speech barely stood out above that already-
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

  waveformTimer = setInterval(() => {
    const level = rms();
    if (calibrating) {
      calibrationSamples.push(level);
      return; // hold at baseline while sampling ambient noise
    }
    const ceiling = Math.max(noiseFloor + 0.05, 0.22);
    const gated = Math.max(0, level - noiseFloor);
    const normalized = Math.min(1, gated / (ceiling - noiseFloor));
    const scaled = Math.sqrt(normalized);
    waveformBars.forEach((bar, i) => {
      const height = MIN_HEIGHT + scaled * (MAX_HEIGHT - MIN_HEIGHT) * barMultipliers[i];
      bar.style.height = `${Math.max(MIN_HEIGHT, Math.min(MAX_HEIGHT, height))}px`;
    });
  }, 60);
  waveformEl.hidden = false;
}

function stopWaveform() {
  if (waveformTimer) {
    clearInterval(waveformTimer);
    waveformTimer = null;
  }
  waveformAnalyser = null;
  waveformEl.hidden = true;
  waveformBars.forEach((bar) => (bar.style.height = "4px"));
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
      handleAudioBlob(blob, "recording.webm", micBlob, systemBlob);
    });

    mediaRecorder.start();
    if (micRecorder) micRecorder.start();
    if (systemRecorder) systemRecorder.start();
    recording = true;
    emptyEl.hidden = true;
    recordingStart = Date.now();
    recordBtn.textContent = "Stop";
    recordBtn.classList.add("recording");
    uploadLabel.hidden = true;
    recordingDotEl.hidden = false;
    timerEl.hidden = false;
    timerInterval = setInterval(() => {
      timerEl.textContent = formatTimer(Date.now() - recordingStart);
    }, 250);
    startWaveform(mixedStream);
    setStatus(usingSystemAudio ? "Recording (mic + system audio)..." : "Recording...");
  } catch (err) {
    setStatus(`Could not access microphone: ${err.message}`, true);
  }
}

function stopRecording() {
  if (mediaRecorder && recording) {
    stopWaveform();
    [mediaRecorder, micRecorder, systemRecorder].forEach((r) => {
      if (r && r.state !== "inactive") r.stop();
    });
    recording = false;
    recordBtn.textContent = "Record";
    recordBtn.classList.remove("recording");
    clearInterval(timerInterval);
    recordingDotEl.hidden = true;
    timerEl.hidden = true;
  }
}

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
  resultsEl.hidden = true;
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
  fileStatus.textContent = "";
  switchTab("summary");
  setStatus("");
}

newRecordingBtn.addEventListener("click", resetToNewRecording);

async function handleAudioBlob(blob, filename, micBlob, systemBlob) {
  emptyEl.hidden = true;
  resultsEl.hidden = false;
  newRecordingBtn.hidden = true;
  showIdleControls(false);
  setStatus("Transcribing locally (this can take a minute)...", false, true);

  const formData = new FormData();
  formData.append("audio", blob, filename);
  if (micBlob) formData.append("mic_audio", micBlob, "mic.webm");
  if (systemBlob) formData.append("system_audio", systemBlob, "system.webm");

  try {
    const res = await fetch("/api/transcribe", { method: "POST", body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Transcription failed");

    renderTranscript(data);
    setStatus("Transcript ready. Generating summary...", false, true);
    await generateSummary(data.text);
  } catch (err) {
    setStatus(`Error: ${err.message}`, true);
    showIdleControls(true);
  }
}

function renderTranscript(data) {
  lastResult = { ...lastResult, text: data.text, segments: data.segments };
  transcriptContent.innerHTML = "";
  let lastSpeaker = null;
  data.segments.forEach((seg) => {
    const div = document.createElement("div");
    div.className = "transcript-segment";

    const timeSpan = document.createElement("span");
    timeSpan.className = "transcript-time";
    const mins = String(Math.floor(seg.start / 60)).padStart(2, "0");
    const secs = String(Math.floor(seg.start % 60)).padStart(2, "0");
    timeSpan.textContent = `${mins}:${secs}`;
    div.appendChild(timeSpan);

    if (seg.speaker && seg.speaker !== lastSpeaker) {
      const speakerSpan = document.createElement("span");
      speakerSpan.className = "transcript-speaker";
      speakerSpan.textContent = `${seg.speaker}: `;
      div.appendChild(speakerSpan);
      lastSpeaker = seg.speaker;
    }

    div.appendChild(document.createTextNode(seg.text));
    transcriptContent.appendChild(div);
  });
  switchTab("transcript");
}

async function generateSummary(transcriptText) {
  summaryContent.textContent = "Generating summary with Claude...";
  notesContent.textContent = "Generating notes with Claude...";
  try {
    const res = await fetch("/api/summarize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transcript: transcriptText }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Summarization failed");

    lastResult.title = data.title;
    lastResult.summary = data.summary;
    lastResult.notes = data.notes;
    summaryContent.textContent = data.summary;
    notesContent.textContent = data.notes;
    if (data.title) {
      meetingTitleEl.textContent = data.title;
      meetingTitleEl.hidden = false;
    }
    switchTab("summary");
    setStatus("");
    newRecordingBtn.hidden = false;
    if (notionConfigured) loadNotionPages();
    checkUsageAlert();
  } catch (err) {
    summaryContent.textContent = "";
    notesContent.textContent = "";
    setStatus(`Summary error: ${err.message}`, true);
    showIdleControls(true);
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
    updateFileBtnLabel();
  } catch (err) {
    notionSelect.innerHTML = '<option value="">Unavailable</option>';
    setFileBtnDisabled(true);
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
    loadUsageDisplay();
  } catch (err) {
    showToast(`Could not load current settings: ${err.message}`, true);
  }
  settingsModal.hidden = false;
  settingsModal.querySelector(".modal-body").scrollTop = 0;
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
].forEach((el) => {
  el.addEventListener("change", saveSettings);
});

// Live-update the numeric label while dragging — "change" (used above for
// autosave) only fires once you let go, but the label should track the
// thumb in real time.
cfgDiarizationThreshold.addEventListener("input", () => {
  cfgDiarizationThresholdValue.textContent = Number(cfgDiarizationThreshold.value).toFixed(2);
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
