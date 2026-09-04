const recordBtn = document.getElementById("recordBtn");
const fileInput = document.getElementById("fileInput");
const timerEl = document.getElementById("timer");
const statusEl = document.getElementById("status");
const emptyEl = document.getElementById("empty");
const resultsEl = document.getElementById("results");
const meetingTitleEl = document.getElementById("meetingTitle");
const summaryContent = document.getElementById("summaryContent");
const notesContent = document.getElementById("notesContent");
const transcriptContent = document.getElementById("transcriptContent");
const notionSelect = document.getElementById("notionSelect");
const fileBtn = document.getElementById("fileBtn");
const fileStatus = document.getElementById("fileStatus");

let mediaRecorder = null;
let recordedChunks = [];
let recording = false;
let timerInterval = null;
let recordingStart = null;

let lastResult = null; // { summary, notes, text, segments }

function setStatus(message, isError = false) {
  if (!message) {
    statusEl.hidden = true;
    return;
  }
  statusEl.hidden = false;
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
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
    const micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    activeStreams = [micStream];

    let usingSystemAudio = false;
    const blackHoleId = await findBlackHoleDeviceId();
    let mixedStream = micStream;

    if (blackHoleId) {
      try {
        const systemStream = await navigator.mediaDevices.getUserMedia({
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
      }
    }

    recordedChunks = [];
    mediaRecorder = new MediaRecorder(mixedStream);
    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) recordedChunks.push(e.data);
    };
    mediaRecorder.onstop = () => {
      activeStreams.forEach((s) => s.getTracks().forEach((track) => track.stop()));
      activeStreams = [];
      if (audioCtx) {
        audioCtx.close();
        audioCtx = null;
      }
      const blob = new Blob(recordedChunks, { type: "audio/webm" });
      handleAudioBlob(blob, "recording.webm");
    };
    mediaRecorder.start();
    recording = true;
    recordingStart = Date.now();
    recordBtn.textContent = "Stop";
    recordBtn.classList.add("recording");
    timerEl.hidden = false;
    timerInterval = setInterval(() => {
      timerEl.textContent = formatTimer(Date.now() - recordingStart);
    }, 250);
    setStatus(usingSystemAudio ? "Recording (mic + system audio)..." : "Recording...");
  } catch (err) {
    setStatus(`Could not access microphone: ${err.message}`, true);
  }
}

function stopRecording() {
  if (mediaRecorder && recording) {
    mediaRecorder.stop();
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
    handleAudioBlob(file, file.name);
  }
  fileInput.value = "";
});

async function handleAudioBlob(blob, filename) {
  emptyEl.hidden = true;
  resultsEl.hidden = false;
  setStatus("Transcribing locally (this can take a minute)...");

  const formData = new FormData();
  formData.append("audio", blob, filename);

  try {
    const res = await fetch("/api/transcribe", { method: "POST", body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Transcription failed");

    renderTranscript(data);
    setStatus("Transcript ready. Generating summary...");
    await generateSummary(data.text);
  } catch (err) {
    setStatus(`Error: ${err.message}`, true);
  }
}

function renderTranscript(data) {
  lastResult = { ...lastResult, text: data.text, segments: data.segments };
  transcriptContent.innerHTML = "";
  data.segments.forEach((seg) => {
    const div = document.createElement("div");
    div.className = "transcript-segment";
    const mins = String(Math.floor(seg.start / 60)).padStart(2, "0");
    const secs = String(Math.floor(seg.start % 60)).padStart(2, "0");
    div.innerHTML = `<span class="transcript-time">${mins}:${secs}</span>${seg.text}`;
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
