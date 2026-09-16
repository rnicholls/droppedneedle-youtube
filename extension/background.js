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
  const text = await response.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!response.ok) {
    throw new Error(`DroppedNeedle returned ${response.status}${text ? `: ${text.slice(0, 120)}` : ""}`);
  }
  return body;
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "DROPPEDNEEDLE_API") return;
  dnFetch(message.path, message.options || {})
    .then((body) => sendResponse({ ok: true, body }))
    .catch((error) => sendResponse({ ok: false, error: error.message || "DroppedNeedle request failed." }));
  return true;
});
