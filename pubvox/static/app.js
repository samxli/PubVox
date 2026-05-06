/**
 * Browser controller for the PubVox PWA.
 *
 * The frontend keeps only transient playback state locally. Book/chapter data,
 * upload processing, and progress persistence flow through the FastAPI JSON API.
 */
const state = {
  books: [],
  activeBookId: localStorage.getItem("pubvox.activeBookId"),
  elapsedSeconds: 0,
  isPlaying: false,
  isSeekingFromState: false,
  pollTimer: null,
  syncTimer: null,
};

const dom = {
  audio: document.querySelector("#audio"),
  bookList: document.querySelector("#book-list"),
  chapterList: document.querySelector("#chapter-list"),
  nowTitle: document.querySelector("#now-title"),
  nowMeta: document.querySelector("#now-meta"),
  bookProgress: document.querySelector("#book-progress"),
  progressRing: document.querySelector("#progress-ring"),
  playerTitle: document.querySelector("#player-title"),
  playerChapter: document.querySelector("#player-chapter"),
  playToggle: document.querySelector("#play-toggle"),
  timeline: document.querySelector("#timeline"),
  elapsed: document.querySelector("#elapsed"),
  duration: document.querySelector("#duration"),
  uploadDropzone: document.querySelector("#upload-dropzone"),
  uploadInput: document.querySelector("#upload-input"),
  processingCard: document.querySelector("#processing-card"),
  processingTitle: document.querySelector("#processing-title"),
  processingPercent: document.querySelector("#processing-percent"),
  processingBar: document.querySelector("#processing-bar"),
  processingStep: document.querySelector("#processing-step"),
};

/** Fetch JSON from the backend and normalize API errors for the UI. */
async function api(path, options = {}) {
  const response = await fetch(path, options);

  if (!response.ok) {
    let message = `Request failed with ${response.status}`;
    try {
      const error = await response.json();
      message = error.detail || message;
    } catch {
      // Keep the status-based message when the response is not JSON.
    }
    throw new Error(message);
  }

  return response.json();
}

/** Refresh the library, restore the active book, and configure playback. */
async function loadBooks() {
  state.books = await api("/api/books");

  if (!state.books.some((book) => book.id === state.activeBookId)) {
    state.activeBookId = state.books[0]?.id || null;
  }

  const book = activeBook();
  if (book?.resume && state.elapsedSeconds === 0) {
    book.currentChapter = book.resume.chapter_index ?? book.currentChapter;
    state.elapsedSeconds = Number(book.resume.elapsed_seconds || 0);
  }

  localStorage.setItem("pubvox.activeBookId", state.activeBookId || "");
  render();
  configureAudio();
  updatePolling();
}

function activeBook() {
  return state.books.find((book) => book.id === state.activeBookId) || state.books[0] || null;
}

function currentChapter(book = activeBook()) {
  if (!book?.chapters?.length) {
    return null;
  }
  return book.chapters[Math.min(book.currentChapter || 0, book.chapters.length - 1)];
}

/** Render the active book, player, library, and chapter queue. */
function render() {
  const book = activeBook();
  const chapter = currentChapter(book);

  if (!book || !chapter) {
    renderEmpty();
    return;
  }

  const chapterLabel = `Chapter ${chapter.position + 1} - ${chapter.title}`;
  const progress = Math.max(0, Math.min(100, book.progress || 0));
  const duration = playbackDuration(chapter);

  dom.nowTitle.textContent = book.title;
  dom.nowMeta.textContent = `${chapterLabel} (${statusLabel(chapter.status)})`;
  dom.bookProgress.textContent = `${progress}%`;
  dom.progressRing.style.background = `
    radial-gradient(circle at center, var(--panel-strong) 0 58%, transparent 59%),
    conic-gradient(var(--accent) 0 ${progress}%, rgba(255, 255, 255, 0.14) ${progress}% 100%)
  `;
  dom.playerTitle.textContent = book.title;
  dom.playerChapter.textContent = chapterLabel;
  dom.duration.textContent = formatTime(duration);
  dom.elapsed.textContent = formatTime(state.elapsedSeconds);
  dom.timeline.max = Math.max(1, Math.floor(duration));
  dom.timeline.value = Math.min(Number(dom.timeline.max), Math.floor(state.elapsedSeconds));
  dom.playToggle.disabled = !chapter.audioUrl;
  dom.playToggle.classList.toggle("is-playing", state.isPlaying);
  dom.playToggle.setAttribute("aria-label", state.isPlaying ? "Pause" : "Play");

  renderBooks(book);
  renderChapters(book);
  updateMediaSession(book, chapter);
}

function renderEmpty() {
  dom.nowTitle.textContent = "No book selected";
  dom.nowMeta.textContent = "Upload an ePub to begin.";
  dom.bookProgress.textContent = "0%";
  dom.playerTitle.textContent = "No book selected";
  dom.playerChapter.textContent = "Upload an ePub to begin.";
  dom.elapsed.textContent = "0:00";
  dom.duration.textContent = "0:00";
  dom.timeline.value = 0;
  dom.playToggle.disabled = true;
  dom.bookList.replaceChildren(emptyState("Your library is empty. Upload an ePub to create chapter records."));
  dom.chapterList.replaceChildren();
}

function renderBooks(active) {
  const cards = state.books.map((book) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `book-card${book.id === active.id ? " active" : ""}`;
    button.addEventListener("click", () => selectBook(book.id));

    const cover = document.createElement("span");
    cover.className = "book-cover";
    cover.setAttribute("aria-hidden", "true");

    const details = document.createElement("span");
    const title = document.createElement("h3");
    title.textContent = book.title;
    const meta = document.createElement("span");
    meta.className = "muted";
    meta.textContent = `${book.author} - ${book.chapters.length} chapters`;
    details.append(title, meta);

    const status = document.createElement("span");
    status.className = "book-status";
    const pill = document.createElement("span");
    pill.className = `status-pill${book.status === "failed" ? " failed" : ""}`;
    pill.textContent = statusLabel(book.status);
    const progress = document.createElement("span");
    progress.className = "muted";
    progress.textContent = `${book.progress || 0}% done`;
    status.append(pill, progress);

    button.append(cover, details, status);
    return button;
  });

  dom.bookList.replaceChildren(...cards);
}

function renderChapters(book) {
  const items = book.chapters.map((chapter) => {
    const item = document.createElement("li");
    item.className = `chapter-item${chapter.position === book.currentChapter ? " current" : ""}`;

    const details = document.createElement("span");
    const title = document.createElement("strong");
    title.textContent = `Chapter ${chapter.position + 1}: ${chapter.title}`;
    const status = document.createElement("span");
    status.className = "muted";
    status.textContent = chapter.audioUrl ? "Audio ready" : statusLabel(chapter.status);
    details.append(title, status);

    const duration = document.createElement("span");
    duration.className = "muted";
    duration.textContent = formatTime(chapter.durationSeconds || 0);

    item.append(details, duration);
    item.addEventListener("click", () => selectChapter(chapter.position));
    return item;
  });

  dom.chapterList.replaceChildren(...items);
}

function emptyState(message) {
  const element = document.createElement("div");
  element.className = "empty-state muted";
  element.textContent = message;
  return element;
}

function selectBook(id) {
  state.activeBookId = id;
  localStorage.setItem("pubvox.activeBookId", id);
  state.elapsedSeconds = activeBook()?.resume?.elapsed_seconds || 0;
  setPlaying(false);
  render();
  configureAudio();
}

function selectChapter(position) {
  const book = activeBook();
  if (!book) {
    return;
  }

  book.currentChapter = position;
  state.elapsedSeconds = 0;
  setPlaying(false);
  render();
  configureAudio();
  syncProgress();
}

function configureAudio() {
  const chapter = currentChapter();
  const nextSource = chapter?.audioUrl || "";

  if (dom.audio.dataset.source !== nextSource) {
    dom.audio.dataset.source = nextSource;
    dom.audio.src = nextSource;
    dom.audio.load();
    return;
  }

  seekAudioToState();
}

async function setPlaying(isPlaying) {
  const chapter = currentChapter();
  if (isPlaying && !chapter?.audioUrl) {
    return;
  }

  if (isPlaying) {
    try {
      seekAudioToState();
      await dom.audio.play();
    } catch (error) {
      showProcessing("Playback", 100, error.message);
    }
  } else {
    dom.audio.pause();
  }
}

function skip(seconds) {
  const duration = playbackDuration();
  const nextTime = Math.max(0, Math.min(duration, state.elapsedSeconds + seconds));
  state.elapsedSeconds = nextTime;

  if (currentChapter()?.audioUrl) {
    dom.audio.currentTime = nextTime;
  }

  render();
  syncProgress();
}

async function advanceToNextChapter(shouldResume) {
  const book = activeBook();
  const chapter = currentChapter(book);
  if (!book || !chapter) {
    return;
  }

  const nextChapter = book.chapters[chapter.position + 1];
  if (!nextChapter) {
    state.elapsedSeconds = playbackDuration(chapter);
    render();
    await syncProgress();
    await setPlaying(false);
    return;
  }

  book.currentChapter = nextChapter.position;
  state.elapsedSeconds = 0;
  render();
  configureAudio();
  await syncProgress();

  if (shouldResume && nextChapter.audioUrl) {
    await setPlaying(true);
  }
}

function playbackDuration(chapter = currentChapter()) {
  if (chapter?.audioUrl && Number.isFinite(dom.audio.duration)) {
    return dom.audio.duration;
  }
  return chapter?.durationSeconds || 0;
}

function seekAudioToState() {
  const chapter = currentChapter();
  if (!chapter?.audioUrl || dom.audio.readyState < 1 || !Number.isFinite(dom.audio.duration)) {
    return;
  }

  const target = Math.max(0, Math.min(dom.audio.duration, state.elapsedSeconds));
  if (Math.abs(dom.audio.currentTime - target) < 0.5) {
    return;
  }

  state.isSeekingFromState = true;
  dom.audio.currentTime = target;
  state.isSeekingFromState = false;
}

function progressPercent(book, chapter, elapsedSeconds) {
  if (!book?.chapters?.length || !chapter) {
    return 0;
  }

  const totalDuration = book.chapters.reduce((total, item) => total + (item.durationSeconds || 0), 0);
  if (!totalDuration) {
    return 0;
  }

  const completedDuration = book.chapters
    .slice(0, chapter.position)
    .reduce((total, item) => total + (item.durationSeconds || 0), 0);

  return Math.max(0, Math.min(100, Math.round(((completedDuration + elapsedSeconds) / totalDuration) * 100)));
}

/** Persist the current chapter and elapsed time for cross-device resume. */
async function syncProgress() {
  const payload = progressPayload();
  if (!payload) {
    return;
  }

  try {
    const updated = await api(`/api/books/${payload.book.id}/progress`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload.body),
    });
    replaceBook(updated);
    render();
  } catch (error) {
    console.warn("Unable to sync progress", error);
  }
}

function progressPayload() {
  const book = activeBook();
  const chapter = currentChapter(book);
  if (!book || !chapter) {
    return null;
  }

  return {
    book,
    body: {
      chapterIndex: chapter.position,
      elapsedSeconds: state.elapsedSeconds,
      progressPercent: progressPercent(book, chapter, state.elapsedSeconds),
    },
  };
}

function syncProgressBeforeUnload() {
  const payload = progressPayload();
  if (!payload) {
    return;
  }

  const url = `/api/books/${payload.book.id}/progress`;
  const body = JSON.stringify(payload.body);

  if (navigator.sendBeacon) {
    const blob = new Blob([body], { type: "application/json" });
    if (navigator.sendBeacon(url, blob)) {
      return;
    }
  }

  fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    keepalive: true,
  }).catch((error) => console.warn("Unable to sync progress before unload", error));
}

/** Upload an ePub and insert the returned book into the local library view. */
async function uploadFile(file) {
  if (!file) {
    return;
  }

  const formData = new FormData();
  formData.append("file", file);
  showProcessing(file.name, 15, "Uploading ePub...");

  try {
    const book = await api("/api/books", { method: "POST", body: formData });
    replaceBook(book);
    state.activeBookId = book.id;
    localStorage.setItem("pubvox.activeBookId", book.id);
    state.elapsedSeconds = 0;
    showProcessing(book.title, 100, book.status === "ready" ? "Ready for playback." : "Chapters queued for TTS.");
    render();
    configureAudio();
    setTimeout(loadBooks, 1000);
  } catch (error) {
    showProcessing(file.name, 100, error.message);
  } finally {
    dom.uploadInput.value = "";
  }
}

function replaceBook(book) {
  const index = state.books.findIndex((item) => item.id === book.id);
  if (index >= 0) {
    state.books.splice(index, 1, book);
  } else {
    state.books.unshift(book);
  }
}

function showProcessing(title, percent, step) {
  dom.processingCard.classList.remove("hidden");
  dom.processingTitle.textContent = title;
  dom.processingPercent.textContent = `${percent}%`;
  dom.processingBar.style.width = `${percent}%`;
  dom.processingStep.textContent = step;
}

function updatePolling() {
  clearInterval(state.pollTimer);

  if (!state.books.some((book) => book.status === "processing")) {
    return;
  }

  state.pollTimer = setInterval(loadBooks, 3000);
}

function statusLabel(status) {
  const labels = {
    queued: "Queued",
    processing: "Processing",
    ready: "Ready",
    failed: "Failed",
  };
  return labels[status] || "Unknown";
}

function formatTime(seconds) {
  const safeSeconds = Math.max(0, Math.floor(seconds || 0));
  return `${Math.floor(safeSeconds / 60)}:${String(safeSeconds % 60).padStart(2, "0")}`;
}

/** Register mobile lock-screen and Bluetooth media controls when available. */
function updateMediaSession(book, chapter) {
  if (!("mediaSession" in navigator) || !book || !chapter) {
    return;
  }

  navigator.mediaSession.metadata = new MediaMetadata({
    title: chapter.title,
    artist: book.author,
    album: book.title,
  });

  navigator.mediaSession.setActionHandler("play", () => setPlaying(true));
  navigator.mediaSession.setActionHandler("pause", () => setPlaying(false));
  navigator.mediaSession.setActionHandler("seekbackward", () => skip(-15));
  navigator.mediaSession.setActionHandler("seekforward", () => skip(30));
}

dom.playToggle.addEventListener("click", () => setPlaying(!state.isPlaying));
document.querySelector("#skip-back").addEventListener("click", () => skip(-15));
document.querySelector("#skip-forward").addEventListener("click", () => skip(30));
document.querySelector("#refresh-books").addEventListener("click", loadBooks);
dom.timeline.addEventListener("input", (event) => {
  state.elapsedSeconds = Number(event.target.value);
  if (currentChapter()?.audioUrl) {
    dom.audio.currentTime = state.elapsedSeconds;
  }
  render();
});
dom.timeline.addEventListener("change", syncProgress);
dom.uploadInput.addEventListener("change", (event) => uploadFile(event.target.files[0]));
dom.uploadDropzone.addEventListener("dragover", (event) => {
  event.preventDefault();
  dom.uploadDropzone.classList.add("dragging");
});
dom.uploadDropzone.addEventListener("dragleave", () => dom.uploadDropzone.classList.remove("dragging"));
dom.uploadDropzone.addEventListener("drop", (event) => {
  event.preventDefault();
  dom.uploadDropzone.classList.remove("dragging");
  uploadFile(event.dataTransfer.files[0]);
});
dom.audio.addEventListener("play", () => {
  state.isPlaying = true;
  render();
});
dom.audio.addEventListener("pause", () => {
  state.isPlaying = false;
  render();
  syncProgress();
});
dom.audio.addEventListener("timeupdate", () => {
  if (state.isSeekingFromState) {
    return;
  }

  state.elapsedSeconds = dom.audio.currentTime;
  render();
});
dom.audio.addEventListener("loadedmetadata", () => {
  seekAudioToState();
  render();
});
dom.audio.addEventListener("ended", () => advanceToNextChapter(true));
window.addEventListener("pagehide", syncProgressBeforeUnload);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") {
    syncProgressBeforeUnload();
  }
});
state.syncTimer = setInterval(syncProgress, 5000);

loadBooks().catch((error) => {
  dom.bookList.replaceChildren(emptyState(error.message));
});
