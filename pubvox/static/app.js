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
  chapterSelectionSeq: 0,
  playbackRequestSeq: 0,
  pollTimer: null,
  syncTimer: null,
  initialLoadComplete: false,
};

const RESUME_CACHE_KEY = "pubvox.resumeCache";

// Parsed cache payload held in memory while `state.books` is still loading.
// Set by `restoreResumeCache()` on bootstrap, consulted by `render()` and
// `setPlaying()` to keep the cached UI alive, cleared by `loadBooks()` once
// the real library data takes over.
let cachedSnapshot = null;

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
    throw new Error(await responseErrorMessage(response));
  }

  return response.json();
}

async function responseErrorMessage(response) {
  let message = `Request failed with ${response.status}`;

  try {
    const error = await response.clone().json();
    return error.detail || message;
  } catch {
    // Try plain text next; otherwise keep the status-based message.
  }

  try {
    const text = await response.text();
    return text || message;
  } catch {
    return message;
  }
}

/** Refresh the library, restore the active book, and configure playback. */
async function loadBooks() {
  const elapsedAtFetchStart = state.elapsedSeconds;
  state.books = await api("/api/books");
  // Live data takes over from the optimistic cache snapshot now that we have
  // real books to render against; subsequent calls hit the normal code paths.
  cachedSnapshot = null;

  if (!state.books.some((book) => book.id === state.activeBookId)) {
    state.activeBookId = state.books[0]?.id || null;
  }

  const book = activeBook();
  // The server's resume is authoritative for cross-device sync, but if the
  // user moved the elapsed position during the fetch (e.g. tapped play in the
  // cache window and the audio advanced via `timeupdate`), their action wins.
  // 0.5s of tolerance absorbs float jitter from seek-induced timeupdates.
  const userMovedElapsed = Math.abs(state.elapsedSeconds - elapsedAtFetchStart) > 0.5;
  // Apply the server's resume value on the first call (it overrides any
  // cache-prefilled position) or whenever local state was reset since (e.g.
  // after upload). Later polling refreshes leave live playback alone.
  if (
    book?.resume
    && !userMovedElapsed
    && (!state.initialLoadComplete || state.elapsedSeconds === 0)
  ) {
    book.currentChapter = book.resume.chapter_index ?? book.currentChapter;
    state.elapsedSeconds = Number(book.resume.elapsed_seconds || 0);
  }
  state.initialLoadComplete = true;

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
    // During the cache window (books still loading) the player chrome was
    // already painted by `restoreResumeCache()`. Refresh only the dynamic
    // bits so play/timeupdate handlers don't wipe the cached labels.
    if (state.books.length === 0 && cachedSnapshot) {
      paintCachedPlayer();
      return;
    }
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
  saveResumeCache(book, chapter);
}

/**
 * Persist enough of the active book/chapter to paint the player instantly on
 * the next page load, before the `/api/books` round trip resolves.
 */
function saveResumeCache(book, chapter) {
  try {
    localStorage.setItem(
      RESUME_CACHE_KEY,
      JSON.stringify({
        bookId: book.id,
        bookTitle: book.title,
        bookAuthor: book.author,
        bookProgress: book.progress || 0,
        chapterPosition: chapter.position,
        chapterTitle: chapter.title,
        chapterStatus: chapter.status,
        chapterDurationSeconds: chapter.durationSeconds || 0,
        elapsedSeconds: state.elapsedSeconds,
        audioUrl: chapter.audioUrl || "",
      }),
    );
  } catch {
    // localStorage may be full or disabled (private mode); the cache is
    // strictly a perf optimization, so swallow the error.
  }
}

/**
 * Paint the player from the last-known snapshot before `loadBooks()` resolves
 * so refreshes don't flash 0:00 for the duration of the network request. The
 * server's resume value still overrides this once the real data arrives.
 */
function restoreResumeCache() {
  let cached;
  try {
    const raw = localStorage.getItem(RESUME_CACHE_KEY);
    if (!raw) {
      return;
    }
    cached = JSON.parse(raw);
  } catch {
    return;
  }
  if (!cached?.bookId || cached.bookId !== state.activeBookId) {
    return;
  }

  cachedSnapshot = cached;
  state.elapsedSeconds = Number(cached.elapsedSeconds) || 0;

  const chapterPosition = Number(cached.chapterPosition) || 0;
  const chapterLabel = `Chapter ${chapterPosition + 1} - ${cached.chapterTitle || ""}`;
  const duration = Number(cached.chapterDurationSeconds) || 0;
  const progress = Math.max(0, Math.min(100, cached.bookProgress || 0));

  dom.nowTitle.textContent = cached.bookTitle || "";
  dom.nowMeta.textContent = `${chapterLabel} (${statusLabel(cached.chapterStatus)})`;
  dom.bookProgress.textContent = `${progress}%`;
  dom.progressRing.style.background = `
    radial-gradient(circle at center, var(--panel-strong) 0 58%, transparent 59%),
    conic-gradient(var(--accent) 0 ${progress}%, rgba(255, 255, 255, 0.14) ${progress}% 100%)
  `;
  dom.playerTitle.textContent = cached.bookTitle || "";
  dom.playerChapter.textContent = chapterLabel;
  dom.duration.textContent = formatTime(duration);
  dom.elapsed.textContent = formatTime(state.elapsedSeconds);
  dom.timeline.max = Math.max(1, Math.floor(duration));
  dom.timeline.value = Math.min(Number(dom.timeline.max), Math.floor(state.elapsedSeconds));

  if (!cached.audioUrl) {
    return;
  }

  // Enable the play button so the user can resume immediately; index.html
  // ships it disabled and the cache-restore path never runs `render()`'s
  // full body which would otherwise toggle it for us.
  dom.playToggle.disabled = false;

  // Start preloading the audio now so playback can begin the moment the user
  // taps play, instead of waiting for loadBooks() + a fresh load() cycle.
  dom.audio.dataset.source = cached.audioUrl;
  dom.audio.src = cached.audioUrl;
  dom.audio.load();

  const seekToCached = () => {
    const target = Math.max(0, Math.min(dom.audio.duration, state.elapsedSeconds));
    if (Number.isFinite(target) && Math.abs(dom.audio.currentTime - target) >= 0.5) {
      state.isSeekingFromState = true;
      dom.audio.currentTime = target;
      state.isSeekingFromState = false;
    }
  };

  if (hasAudioMetadata()) {
    seekToCached();
  } else {
    dom.audio.addEventListener("loadedmetadata", seekToCached, { once: true });
  }
}

/**
 * Refresh just the dynamic portions of the player chrome from `state` +
 * `cachedSnapshot`. Used while books are still loading so render() can react
 * to play/pause/timeupdate without falling through to `renderEmpty()`.
 */
function paintCachedPlayer() {
  if (!cachedSnapshot) {
    return;
  }
  const fallbackDuration = Number(cachedSnapshot.chapterDurationSeconds) || 0;
  const duration = Number.isFinite(dom.audio.duration) && dom.audio.duration > 0
    ? dom.audio.duration
    : fallbackDuration;
  const max = Math.max(1, Math.floor(duration));

  dom.duration.textContent = formatTime(duration);
  dom.elapsed.textContent = formatTime(state.elapsedSeconds);
  dom.timeline.max = max;
  dom.timeline.value = Math.min(max, Math.floor(state.elapsedSeconds));
  dom.playToggle.disabled = !cachedSnapshot.audioUrl;
  dom.playToggle.classList.toggle("is-playing", state.isPlaying);
  dom.playToggle.setAttribute("aria-label", state.isPlaying ? "Pause" : "Play");
}

/**
 * Resolves the current playback target, falling back to the cached snapshot
 * during the bootstrap window when `state.books` is still empty. Returns
 * `null` only when there is genuinely nothing to play.
 */
function activePlaybackTarget() {
  const chapter = currentChapter();
  if (chapter?.audioUrl) {
    return chapter.audioUrl;
  }
  if (state.books.length === 0 && cachedSnapshot?.audioUrl) {
    return cachedSnapshot.audioUrl;
  }
  return null;
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

async function selectBook(id) {
  await setPlaying(false);
  state.activeBookId = id;
  localStorage.setItem("pubvox.activeBookId", id);
  state.elapsedSeconds = activeBook()?.resume?.elapsed_seconds || 0;
  render();
  configureAudio();
}

async function selectChapter(position) {
  const sequence = ++state.chapterSelectionSeq;
  const book = activeBook();
  if (!book) {
    return;
  }

  const shouldResume = state.isPlaying;
  await setPlaying(false);
  book.currentChapter = position;
  state.elapsedSeconds = 0;
  render();
  configureAudio();
  // Progress persistence is best-effort and should not block local playback.
  syncProgress();

  if (shouldResume && sequence === state.chapterSelectionSeq && book.currentChapter === position) {
    await setPlaying(true);
  }
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
  const sequence = ++state.playbackRequestSeq;
  // Fall back to the cached snapshot's audio URL during the bootstrap window
  // so a user tap on the now-enabled play button isn't dropped just because
  // `currentChapter()` is still null pending `loadBooks()`.
  if (isPlaying && !activePlaybackTarget()) {
    state.isPlaying = false;
    render();
    return;
  }

  if (isPlaying) {
    state.isPlaying = true;
    render();

    try {
      await waitForAudioMetadata();
      if (sequence !== state.playbackRequestSeq || !state.isPlaying) {
        return;
      }

      seekAudioToState();
      await dom.audio.play();
    } catch (error) {
      if (sequence !== state.playbackRequestSeq) {
        return;
      }

      state.isPlaying = false;
      render();
      showProcessing("Playback", 100, error.message);
    }
  } else {
    dom.audio.pause();
    state.isPlaying = false;
    render();
  }
}

function hasAudioMetadata() {
  return dom.audio.readyState >= 1 && Number.isFinite(dom.audio.duration);
}

function waitForAudioMetadata() {
  if (hasAudioMetadata()) {
    return Promise.resolve();
  }

  return new Promise((resolve, reject) => {
    const cleanup = () => {
      dom.audio.removeEventListener("loadedmetadata", handleReady);
      dom.audio.removeEventListener("canplay", handleReady);
      dom.audio.removeEventListener("error", handleError);
    };
    const handleReady = () => {
      cleanup();
      resolve();
    };
    const handleError = () => {
      cleanup();
      reject(new Error("Audio metadata failed to load."));
    };

    dom.audio.addEventListener("loadedmetadata", handleReady, { once: true });
    dom.audio.addEventListener("canplay", handleReady, { once: true });
    dom.audio.addEventListener("error", handleError, { once: true });
  });
}

function skip(seconds) {
  const chapter = currentChapter();
  // Skip needs a known chapter duration to clamp against; during the bootstrap
  // window we don't have one yet (cached durationSeconds is just an estimate),
  // so ignore presses rather than risk truncating the cached elapsed to 0.
  if (!chapter) {
    return;
  }
  const duration = playbackDuration(chapter);
  const nextTime = Math.max(0, Math.min(duration, state.elapsedSeconds + seconds));
  state.elapsedSeconds = nextTime;

  if (chapter.audioUrl) {
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
  if (!chapter?.audioUrl || !hasAudioMetadata()) {
    return;
  }

  const target = Math.max(0, Math.min(dom.audio.duration, state.elapsedSeconds));
  const stateChanged = Math.abs(state.elapsedSeconds - target) >= 0.5;
  state.elapsedSeconds = target;

  if (Math.abs(dom.audio.currentTime - target) < 0.5) {
    if (stateChanged) {
      render();
    }
    return;
  }

  state.isSeekingFromState = true;
  dom.audio.currentTime = target;
  state.isSeekingFromState = false;

  if (stateChanged) {
    render();
  }
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
  })
    .then(async (response) => {
      if (!response.ok) {
        console.warn("Unable to sync progress before unload", await responseErrorMessage(response));
      }
    })
    .catch((error) => console.warn("Unable to sync progress before unload", error));
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
  const chapter = currentChapter();
  // See `skip()`: ignore drags until the real chapter is available so we don't
  // clobber the cached UI with `renderEmpty()`.
  if (!chapter) {
    return;
  }
  state.elapsedSeconds = Number(event.target.value);
  if (chapter.audioUrl) {
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
  // Suppress pre-seek timeupdates fired during the cache-window audio load
  // (currentTime starts at 0 before the cached seek lands). Once the user
  // taps play, isPlaying flips true and `timeupdate` drives the UI normally.
  if (!state.books.length && !state.isPlaying) {
    return;
  }

  state.elapsedSeconds = dom.audio.currentTime;
  render();
});
dom.audio.addEventListener("loadedmetadata", () => {
  // The cache-restore path attaches a one-shot seeker for the bootstrap
  // window; here we just sync the audio element to the live `state` and
  // repaint. `render()` handles the cache-window case via `paintCachedPlayer()`.
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

restoreResumeCache();
loadBooks().catch((error) => {
  dom.bookList.replaceChildren(emptyState(error.message));
});
