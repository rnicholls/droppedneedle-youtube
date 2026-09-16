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
    statusEl.textContent = "Reload this YouTube tab after updating the extension.";
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

identifyButton.addEventListener("click", identify);

async function identify() {
  identifyButton.disabled = true;
  identifyButton.textContent = "Finding…";
  statusEl.textContent = "Finding song…";
  resultsEl.replaceChildren();
  try {
    const data = await dnFetch("/api/v1/plugins/ext/youtube-link/identify", {
      method: "POST",
      body: JSON.stringify(currentVideo)
    });
    if (data.warning && !(data.matches || []).length) {
      statusEl.textContent = data.warning;
      return;
    }
    renderResults(data.matches || []);
  } catch (error) {
    statusEl.textContent = error.message || "Couldn't contact DroppedNeedle.";
  } finally {
    identifyButton.disabled = false;
    identifyButton.textContent = "Find song";
  }
}

function renderResults(matches) {
  if (!matches.length) {
    statusEl.textContent = "No matches found.";
    return;
  }

  statusEl.textContent = matches.length === 1
    ? "Found a likely match."
    : "Best match first — choose another if needed.";

  for (const [index, match] of matches.entries()) {
    const item = document.createElement("div");
    item.className = `result${match.recommended || index === 0 ? " recommended" : ""}`;

    if (match.recommended || index === 0) {
      const badge = document.createElement("div");
      badge.className = "recommended-badge";
      badge.textContent = "Best match";
      item.append(badge);
    }

    const title = document.createElement("div");
    title.className = "result-title";
    title.textContent = `${match.artist || "Unknown artist"} — ${match.title}`;

    const meta = document.createElement("div");
    meta.className = "result-meta";
    meta.textContent = [match.album, match.year, match.score != null ? `${Math.round(match.score * 100)}% MB match` : null]
      .filter(Boolean).join(" · ");

    const add = document.createElement("button");
    add.type = "button";
    add.className = "add-track";
    add.textContent = "Add to DroppedNeedle";
    add.addEventListener("click", () => requestTrack(match, add));

    item.append(title, meta, add);
    resultsEl.append(item);
  }
}

async function requestTrack(match, button) {
  const buttons = [...resultsEl.querySelectorAll(".add-track")];
  buttons.forEach((candidate) => { candidate.disabled = true; });
  button.textContent = "Sending…";
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

    switch (result.status) {
      case "already_in_library":
        button.textContent = "Already in library ✓";
        statusEl.textContent = "This track is already in your DroppedNeedle library.";
        break;
      case "awaiting_approval":
        button.textContent = "Awaiting approval ✓";
        statusEl.textContent = "Request submitted and awaiting approval in DroppedNeedle.";
        break;
      case "queued":
        button.textContent = "Queued ✓";
        statusEl.textContent = "Track queued for acquisition in DroppedNeedle.";
        break;
      default:
        button.textContent = "Requested ✓";
        statusEl.textContent = "Track request sent to DroppedNeedle.";
        break;
    }
  } catch (error) {
    buttons.forEach((candidate) => { candidate.disabled = false; });
    button.textContent = "Add to DroppedNeedle";
    statusEl.textContent = error.message || "Couldn't request track.";
  }
}

loadVideo();
