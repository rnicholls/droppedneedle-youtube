const DN_ID = "droppedneedle-youtube-action";
let lastVideoId = null;

function getVideoMetadata() {
  const url = new URL(window.location.href);
  if (url.pathname !== "/watch" || !url.searchParams.get("v")) return null;

  const title =
    document.querySelector("h1.ytd-watch-metadata yt-formatted-string")?.textContent?.trim() ||
    document.querySelector("meta[name='title']")?.content ||
    document.title.replace(/\s*-\s*YouTube\s*$/, "");
  const channel =
    document.querySelector("ytd-watch-metadata ytd-channel-name a")?.textContent?.trim() ||
    document.querySelector("link[itemprop='name']")?.getAttribute("content") || "";

  return { url: window.location.href, videoId: url.searchParams.get("v"), title, channel };
}

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
    throw new Error(`DroppedNeedle returned ${response.status}${body ? `: ${body.slice(0, 100)}` : ""}`);
  }
  return response.json();
}

function closePanel(root) {
  root.querySelector(".dn-panel")?.remove();
  root.querySelector(".dn-add-button")?.classList.remove("dn-open");
}

function showPanel(root, video) {
  closePanel(root);
  const panel = document.createElement("div");
  panel.className = "dn-panel";
  panel.innerHTML = `
    <div class="dn-panel-head"><strong>DroppedNeedle</strong><button class="dn-close" aria-label="Close">×</button></div>
    <div class="dn-video-title"></div>
    <div class="dn-status">Finding song…</div>
    <div class="dn-results"></div>`;
  panel.querySelector(".dn-video-title").textContent = video.title;
  panel.querySelector(".dn-close").addEventListener("click", () => closePanel(root));
  root.append(panel);
  identify(root, panel, video);
}

async function identify(root, panel, video) {
  const status = panel.querySelector(".dn-status");
  const results = panel.querySelector(".dn-results");
  try {
    const data = await dnFetch("/api/v1/plugins/ext/youtube-link/identify", {
      method: "POST", body: JSON.stringify(video)
    });
    const matches = data.matches || [];
    if (!matches.length) {
      status.textContent = data.warning || "No matches found.";
      return;
    }
    status.textContent = matches.length === 1 ? "Possible match" : "Choose a match";
    matches.forEach((match, index) => results.append(renderMatch(root, panel, match, index)));
  } catch (error) {
    status.textContent = error.message || "Couldn't contact DroppedNeedle.";
  }
}

function renderMatch(root, panel, match, index) {
  const item = document.createElement("div");
  item.className = `dn-result${match.recommended ? " dn-recommended" : ""}`;

  const heading = document.createElement("div");
  heading.className = "dn-result-heading";
  const title = document.createElement("strong");
  title.textContent = `${match.artist || "Unknown artist"} — ${match.title}`;
  heading.append(title);
  if (match.recommended) {
    const badge = document.createElement("span");
    badge.className = "dn-badge";
    badge.textContent = "Best match";
    heading.append(badge);
  }

  const meta = document.createElement("div");
  meta.className = "dn-meta";
  meta.textContent = [match.album, match.year, match.score != null ? `${Math.round(match.score * 100)}%` : null]
    .filter(Boolean).join(" · ");

  const button = document.createElement("button");
  button.className = "dn-request";
  button.textContent = index === 0 ? "Add track" : "Add this version";
  button.addEventListener("click", () => requestTrack(root, panel, match, button));
  item.append(heading, meta, button);
  return item;
}

async function requestTrack(root, panel, match, button) {
  const status = panel.querySelector(".dn-status");
  button.disabled = true;
  button.textContent = "Adding…";
  status.textContent = "Sending to DroppedNeedle…";
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
    if (result.status === "already_in_library") {
      button.textContent = "Already in library ✓";
      status.textContent = "This track is already in your library.";
    } else if (result.status === "awaiting_approval") {
      button.textContent = "Requested ✓";
      status.textContent = "Request submitted and awaiting approval.";
    } else {
      button.textContent = "Queued ✓";
      status.textContent = "DroppedNeedle is finding and downloading the track.";
    }
    root.querySelector(".dn-add-button").textContent = "DroppedNeedle ✓";
  } catch (error) {
    button.disabled = false;
    button.textContent = "Try again";
    status.textContent = error.message || "Couldn't request track.";
  }
}

function injectButton() {
  const video = getVideoMetadata();
  if (!video) return;
  if (document.getElementById(DN_ID)) return;

  const actions = document.querySelector("#top-level-buttons-computed") ||
    document.querySelector("ytd-menu-renderer #top-level-buttons-computed");
  if (!actions) return;

  const root = document.createElement("div");
  root.id = DN_ID;
  const button = document.createElement("button");
  button.className = "dn-add-button";
  button.innerHTML = `<span class="dn-note">♪</span><span>Add to DroppedNeedle</span>`;
  button.addEventListener("click", () => {
    if (root.querySelector(".dn-panel")) closePanel(root);
    else {
      button.classList.add("dn-open");
      showPanel(root, getVideoMetadata());
    }
  });
  root.append(button);
  actions.append(root);
}

function refreshForNavigation() {
  const video = getVideoMetadata();
  if (!video) {
    document.getElementById(DN_ID)?.remove();
    lastVideoId = null;
    return;
  }
  if (video.videoId !== lastVideoId) {
    document.getElementById(DN_ID)?.remove();
    lastVideoId = video.videoId;
  }
  injectButton();
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "DROPPEDNEEDLE_GET_VIDEO") sendResponse({ ok: true, video: getVideoMetadata() });
});

document.addEventListener("yt-navigate-finish", () => setTimeout(refreshForNavigation, 300));
const observer = new MutationObserver(() => refreshForNavigation());
observer.observe(document.documentElement, { childList: true, subtree: true });
refreshForNavigation();
