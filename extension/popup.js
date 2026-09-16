let currentVideo = null;

const statusEl = document.querySelector("#status");
const identifyButton = document.querySelector("#identify");
const videoEl = document.querySelector("#video");
const titleEl = document.querySelector("#video-title");
const channelEl = document.querySelector("#video-channel");
const resultsEl = document.querySelector("#results");

document.querySelector("#settings").addEventListener("click", (event) => {
  event.preventDefault();
  chrome.runtime.openOptionsPage();
});

async function settings() {
  return chrome.storage.sync.get({
    baseUrl: "https://droppedneedle.nodehaven.ca",
    token: ""
  });
}

async function loadVideo() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || !tab.url?.includes("youtube.com/watch")) {
    statusEl.textContent = "Open a YouTube video first.";
    return;
  }

  try {
    const response = await chrome.tabs.sendMessage(tab.id, { type: "DROPPEDNEEDLE_GET_VIDEO" });
    currentVideo = response?.video;
  } catch {
    statusEl.textContent = "Reload this YouTube tab after installing the extension.";
    return;
  }

  if (!currentVideo) {
    statusEl.textContent = "Couldn't read this video.";
    return;
  }

  titleEl.textContent = currentVideo.title;
  channelEl.textContent = currentVideo.channel;
  videoEl.hidden = false;
  statusEl.textContent = "Ready to identify this song.";
  identifyButton.disabled = false;
}

identifyButton.addEventListener("click", async () => {
  const { baseUrl, token } = await settings();
  if (!baseUrl) {
    statusEl.textContent = "Set your DroppedNeedle URL in Settings.";
    return;
  }

  identifyButton.disabled = true;
  statusEl.textContent = "Finding song…";
  resultsEl.replaceChildren();

  try {
    const headers = { "Content-Type": "application/json" };
    if (token) headers.Authorization = `Bearer ${token}`;

    const response = await fetch(`${baseUrl.replace(/\/$/, "")}/api/v1/plugins/ext/youtube-link/identify`, {
      method: "POST",
      headers,
      credentials: "include",
      body: JSON.stringify(currentVideo)
    });

    if (!response.ok) throw new Error(`DroppedNeedle returned ${response.status}`);
    const data = await response.json();
    renderResults(data.matches || []);
  } catch (error) {
    statusEl.textContent = error.message || "Couldn't contact DroppedNeedle.";
  } finally {
    identifyButton.disabled = false;
  }
});

function renderResults(matches) {
  if (!matches.length) {
    statusEl.textContent = "No confident matches found.";
    return;
  }

  statusEl.textContent = matches.length === 1 ? "Possible match" : "Possible matches";
  for (const match of matches) {
    const item = document.createElement("div");
    item.className = "result";
    const title = document.createElement("div");
    title.className = "result-title";
    title.textContent = `${match.artist || "Unknown artist"} — ${match.title}`;
    const meta = document.createElement("div");
    meta.className = "result-meta";
    meta.textContent = [match.album, match.year, match.score != null ? `${Math.round(match.score * 100)}%` : null]
      .filter(Boolean)
      .join(" · ");
    item.append(title, meta);
    resultsEl.append(item);
  }
}

loadVideo();
