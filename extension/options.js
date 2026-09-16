const baseUrl = document.querySelector("#baseUrl");
const status = document.querySelector("#status");

async function load() {
  const saved = await chrome.storage.sync.get({
    baseUrl: "https://droppedneedle.nodehaven.ca"
  });
  baseUrl.value = saved.baseUrl;
}

document.querySelector("#save").addEventListener("click", async () => {
  await chrome.storage.sync.set({
    baseUrl: baseUrl.value.trim().replace(/\/$/, "")
  });
  status.textContent = "Saved.";
  setTimeout(() => { status.textContent = ""; }, 1500);
});

load();
