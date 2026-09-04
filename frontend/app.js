const recordBtn = document.getElementById("recordBtn");
const fileInput = document.getElementById("fileInput");
const timerEl = document.getElementById("timer");
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
const downloadBtn = document.getElementById("downloadBtn");
const fileStatus = document.getElementById("fileStatus");

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
  waveformTimer = setInterval(() => {
    waveformAnalyser.getByteTimeDomainData(data);
    let sumSquares = 0;
    for (let i = 0; i < data.length; i++) {
      const v = (data[i] - 128) / 128;
      sumSquares += v * v;
    }
    const rms = Math.sqrt(sumSquares / data.length);
    // Normal conversational volume rarely pushes RMS anywhere near 1.0, so
    // scaling linearly kept movement subtle even with real signal — sqrt
    // boosts quieter/typical speech levels to make movement obvious rather
    // than only reacting to shouting.
    const level = Math.sqrt(rms);
    waveformBars.forEach((bar, i) => {
      const height = MIN_HEIGHT + level * (MAX_HEIGHT - MIN_HEIGHT) * barMultipliers[i];
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

    const micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    activeStreams = [micStream];

    let usingSystemAudio = false;
    let systemStream = null;
    const blackHoleId = await findBlackHoleDeviceId();
    let mixedStream = micStream;

    if (blackHoleId) {
      try {
        systemStream = await navigator.mediaDevices.getUserMedia({
          audio: { deviceId: { exact: blackHoleId } },
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
    recordingStart = Date.now();
    recordBtn.textContent = "Stop";
    recordBtn.classList.add("recording");
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

async function handleAudioBlob(blob, filename, micBlob, systemBlob) {
  emptyEl.hidden = true;
  resultsEl.hidden = false;
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
    loadNotionPages();
  } catch (err) {
    summaryContent.textContent = "";
    notesContent.textContent = "";
    setStatus(`Summary error: ${err.message}`, true);
  }
}

async function loadNotionPages() {
  notionSelect.innerHTML = '<option value="">Loading pages...</option>';
  try {
    const res = await fetch("/api/notion/pages");
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to load Notion pages");

    notionSelect.innerHTML = '<option value="">Select a page...</option>';
    data.pages.forEach((page) => {
      const opt = document.createElement("option");
      opt.value = page.id;
      opt.dataset.type = page.type;
      opt.textContent = page.type === "database" ? `${page.title} (database)` : page.title;
      notionSelect.appendChild(opt);
    });
    fileBtn.disabled = false;
  } catch (err) {
    notionSelect.innerHTML = '<option value="">Unavailable</option>';
    fileStatus.textContent = err.message;
  }
}

notionSelect.addEventListener("change", () => {
  fileBtn.disabled = !notionSelect.value;
});

fileBtn.addEventListener("click", async () => {
  if (!notionSelect.value || !lastResult) return;
  fileBtn.disabled = true;
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
      link.textContent = " Open page";
      link.target = "_blank";
      fileStatus.appendChild(link);
    }
  } catch (err) {
    fileStatus.textContent = `Error: ${err.message}`;
    fileBtn.disabled = false;
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
