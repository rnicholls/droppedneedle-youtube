function getVideoMetadata() {
  const url = new URL(window.location.href);
  if (url.pathname !== "/watch" || !url.searchParams.get("v")) return null;

  const title =
    document.querySelector("h1.ytd-watch-metadata yt-formatted-string")?.textContent?.trim() ||
    document.querySelector("meta[name='title']")?.content ||
    document.title.replace(/\s*-\s*YouTube\s*$/, "");

  const channel =
    document.querySelector("ytd-watch-metadata ytd-channel-name a")?.textContent?.trim() ||
    document.querySelector("link[itemprop='name']")?.getAttribute("content") ||
    "";

  return {
    url: window.location.href,
    videoId: url.searchParams.get("v"),
    title,
    channel
  };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "DROPPEDNEEDLE_GET_VIDEO") {
    sendResponse({ ok: true, video: getVideoMetadata() });
  }
});
