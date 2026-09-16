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
  return chrome.storage.sync.get({ baseUrl: "https://droppedneedle.nodehaven.ca" });
}

async function dnFetch(path, options = {}) {
  const { baseUrl } = await settings();
  const response = await fetch(`${baseUrl.replace(/\/$/, "")}${path}`, {
    ...options,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) }
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`DroppedNeedle returned ${response.status}${body ? `: ${body.slice(0, 120)}` : ""}`);
  }
  return response.json();
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
  identifyButton.disabled = true;
  statusEl.textContent = "Finding song…";
  resultsEl.replaceChildren();
  try {
    const data = await dnFetch("/api/v1/plugins/ext/youtube-link/identify", {
      method: "POST",
      body: JSON.stringify(currentVideo)
    });
    renderResults(data.matches || []);
  } catch (error) {
    statusEl.textContent = error.message || "Couldn't contact DroppedNeedle.";
  } finally {
    identifyButton.disabled = false;
  }
});

function renderResults(matches) {
  if (!matches.length) {
    statusEl.textContent = "No matches found.";
    return;
  }
  statusEl.textContent = matches.length === 1 ? "Possible match" : "Choose a match";
  for (const match of matches) {
    const item = document.createElement("div");
    item.className = "result";

    const title = document.createElement("div");
    title.className = "result-title";
    title.textContent = `${match.artist || "Unknown artist"} — ${match.title}`;

    const meta = document.createElement("div");
    meta.className = "result-meta";
    meta.textContent = [match.album, match.year, match.score != null ? `${Math.round(match.score * 100)}%` : null]
      .filter(Boolean).join(" · ");

    const add = document.createElement("button");
    add.type = "button";
    add.className = "add-track";
    add.textContent = "Add Track";
    add.addEventListener("click", () => requestTrack(match, add));

    item.append(title, meta, add);
    resultsEl.append(item);
  }
}

async function requestTrack(match, button) {
  button.disabled = true;
  button.textContent = "Adding…";
  statusEl.textContent = "Sending track to DroppedNeedle…";
  try {
    const result = await dnFetch(`/api/v1/tracks/${encodeURIComponent(match.recording_mbid)}/request`, {
      method: "POST",
      body: JSON.stringify({
        artist_name: match.artist,
        track_title: match.title,
        album_title: match.album || null,
        duration_seconds: match.duration_seconds || null,
        release_group_mbid: match.release_group_mbid || null,
        artist_mbid: match.artist_mbid || null,
        release_id: match.release_id || null
      })
    });
    button.textContent = result.status === "already_in_library" ? "Already in library" : "Added ✓";
    statusEl.textContent = result.status === "awaiting_approval"
      ? "Request submitted and awaiting approval."
      : result.status === "already_in_library"
        ? "That track is already in your library."
        : "Track added to DroppedNeedle.";
  } catch (error) {
    button.disabled = false;
    button.textContent = "Add Track";
    statusEl.textContent = error.message || "Couldn't request track.";
  }
}

loadVideo();
