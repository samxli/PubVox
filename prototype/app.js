const books = [
  {
    id: "long-way-home",
    title: "The Long Way Home",
    author: "Mira Chen",
    progress: 42,
    synced: "2 min ago",
    currentChapter: 3,
    chapters: [
      { title: "Departures", duration: "18:22", ready: true },
      { title: "Night Signals", duration: "24:10", ready: true },
      { title: "Platform Lights", duration: "21:36", ready: true },
      { title: "A Rainy Platform", duration: "30:10", ready: true },
      { title: "The Last Train", duration: "26:04", ready: false },
    ],
  },
  {
    id: "city-under-glass",
    title: "City Under Glass",
    author: "Arun Patel",
    progress: 68,
    synced: "Yesterday",
    currentChapter: 8,
    chapters: [
      { title: "Archive Door", duration: "19:04", ready: true },
      { title: "Tunnels", duration: "27:44", ready: true },
      { title: "The Glass Market", duration: "32:19", ready: true },
      { title: "Static", duration: "22:48", ready: true },
    ],
  },
  {
    id: "small-vps",
    title: "Small VPS Field Guide",
    author: "Nora Kim",
    progress: 12,
    synced: "Just now",
    currentChapter: 0,
    chapters: [
      { title: "One Container", duration: "16:42", ready: true },
      { title: "SQLite on Disk", duration: "20:15", ready: true },
      { title: "Reverse Proxy Basics", duration: "28:03", ready: false },
    ],
  },
];

const state = {
  activeBookId: localStorage.getItem("pubvox.activeBookId") || books[0].id,
  isPlaying: false,
const savedElapsedPercent = localStorage.getItem("pubvox.elapsedPercent");

const state = {
  activeBookId: localStorage.getItem("pubvox.activeBookId") || books[0].id,
  isPlaying: false,
  elapsedPercent: savedElapsedPercent !== null ? Number(savedElapsedPercent) : 42,
  processingTimer: null,
  playbackTimer: null,
};
  processingTimer: null,
  playbackTimer: null,
};

const dom = {
  bookList: document.querySelector("#book-list"),
  chapterList: document.querySelector("#chapter-list"),
  nowTitle: document.querySelector("#now-title"),
  nowMeta: document.querySelector("#now-meta"),
  bookProgress: document.querySelector("#book-progress"),
  playerTitle: document.querySelector("#player-title"),
  playerChapter: document.querySelector("#player-chapter"),
  playToggle: document.querySelector("#play-toggle"),
  timeline: document.querySelector("#timeline"),
  elapsed: document.querySelector("#elapsed"),
  duration: document.querySelector("#duration"),
  uploadInput: document.querySelector("#upload-input"),
  processingCard: document.querySelector("#processing-card"),
  processingTitle: document.querySelector("#processing-title"),
  processingPercent: document.querySelector("#processing-percent"),
  processingBar: document.querySelector("#processing-bar"),
  processingStep: document.querySelector("#processing-step"),
};

function activeBook() {
  return books.find((book) => book.id === state.activeBookId) || books[0];
}

function currentChapter(book = activeBook()) {
  return book.chapters[book.currentChapter] || book.chapters[0];
}

function render() {
  const book = activeBook();
  const chapter = currentChapter(book);

  dom.nowTitle.textContent = book.title;
  dom.nowMeta.textContent = `Chapter ${book.currentChapter + 1} - ${chapter.title}`;
  dom.bookProgress.textContent = `${book.progress}%`;
  dom.playerTitle.textContent = book.title;
  dom.playerChapter.textContent = `Chapter ${book.currentChapter + 1} - ${chapter.title}`;
  dom.duration.textContent = chapter.duration;
  dom.timeline.value = state.elapsedPercent;
  dom.elapsed.textContent = timeFromPercent(state.elapsedPercent, chapter.duration);
  dom.playToggle.classList.toggle("is-playing", state.isPlaying);
  dom.playToggle.setAttribute("aria-label", state.isPlaying ? "Pause" : "Play");

  renderBooks(book);
  renderChapters(book);
  updateMediaSession(book, chapter);
}

function renderBooks(active) {
  dom.bookList.innerHTML = "";

  books.forEach((book) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `book-card${book.id === active.id ? " active" : ""}`;
    button.innerHTML = `
      <span class="book-cover" aria-hidden="true"></span>
      <span>
        <h3>${book.title}</h3>
        <span class="muted">${book.author} - synced ${book.synced}</span>
      </span>
      <span class="book-progress">
        <strong>${book.progress}%</strong>
        <span class="muted">done</span>
      </span>
    `;
    button.addEventListener("click", () => selectBook(book.id));
    dom.bookList.appendChild(button);
  });
}

function renderChapters(book) {
  dom.chapterList.innerHTML = "";

  book.chapters.forEach((chapter, index) => {
    const item = document.createElement("li");
    item.className = `chapter-item${index === book.currentChapter ? " current" : ""}`;
    item.innerHTML = `
      <span>
        <strong>Chapter ${index + 1}: ${chapter.title}</strong>
        <span class="muted">${chapter.ready ? "Audio ready" : "Queued for TTS"}</span>
      </span>
      <span class="muted">${chapter.duration}</span>
    `;
    dom.chapterList.appendChild(item);
  });
}

function selectBook(id) {
  state.activeBookId = id;
  state.elapsedPercent = books.find((book) => book.id === id)?.progress || 0;
  localStorage.setItem("pubvox.activeBookId", id);
  render();
}

function setPlaying(isPlaying) {
  state.isPlaying = isPlaying;
  clearInterval(state.playbackTimer);

  if (state.isPlaying) {
    state.playbackTimer = setInterval(() => {
      state.elapsedPercent = Math.min(100, state.elapsedPercent + 0.4);
      localStorage.setItem("pubvox.elapsedPercent", String(state.elapsedPercent));

      if (state.elapsedPercent >= 100) {
        setPlaying(false);
      }

      render();
    }, 1000);
  }

  render();
}

function skip(delta) {
  state.elapsedPercent = Math.max(0, Math.min(100, state.elapsedPercent + delta));
  localStorage.setItem("pubvox.elapsedPercent", String(state.elapsedPercent));
  render();
}

function timeFromPercent(percent, duration) {
  const [minutes, seconds] = duration.split(":").map(Number);
  const totalSeconds = minutes * 60 + seconds;
  const elapsedSeconds = Math.floor(totalSeconds * (percent / 100));
  return `${Math.floor(elapsedSeconds / 60)}:${String(elapsedSeconds % 60).padStart(2, "0")}`;
}

function simulateUpload(fileName) {
  const safeName = fileName?.replace(/\.epub$/i, "") || "New ePub";
  const steps = [
    "Saving ePub to volume...",
    "Extracting metadata and chapters...",
    "Queueing Edge TTS generation...",
    "Generating chapter audio chunks...",
    "Ready for streaming playback.",
  ];
  let progress = 0;

  clearInterval(state.processingTimer);
  dom.processingCard.classList.remove("hidden");
  dom.processingTitle.textContent = safeName;

  state.processingTimer = setInterval(() => {
    progress = Math.min(100, progress + 8);
    const stepIndex = Math.min(steps.length - 1, Math.floor(progress / 22));

    dom.processingPercent.textContent = `${progress}%`;
    dom.processingBar.style.width = `${progress}%`;
    dom.processingStep.textContent = steps[stepIndex];

    if (progress >= 100) {
      clearInterval(state.processingTimer);
    }
  }, 350);
}

function updateMediaSession(book, chapter) {
  if (!("mediaSession" in navigator)) {
    return;
  }

  navigator.mediaSession.metadata = new MediaMetadata({
    title: chapter.title,
    artist: book.author,
    album: book.title,
  });

  navigator.mediaSession.setActionHandler("play", () => setPlaying(true));
  navigator.mediaSession.setActionHandler("pause", () => setPlaying(false));
  navigator.mediaSession.setActionHandler("seekbackward", () => skip(-8));
  navigator.mediaSession.setActionHandler("seekforward", () => skip(12));
}

dom.playToggle.addEventListener("click", () => setPlaying(!state.isPlaying));
document.querySelector("#skip-back").addEventListener("click", () => skip(-8));
document.querySelector("#skip-forward").addEventListener("click", () => skip(12));
document.querySelector("#sort-toggle").addEventListener("click", () => {
  books.reverse();
  render();
});
dom.timeline.addEventListener("input", (event) => {
  state.elapsedPercent = Number(event.target.value);
  localStorage.setItem("pubvox.elapsedPercent", String(state.elapsedPercent));
  render();
});
dom.uploadInput.addEventListener("change", (event) => {
  simulateUpload(event.target.files[0]?.name);
});

render();
