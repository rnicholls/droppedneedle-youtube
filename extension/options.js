const baseUrl = document.querySelector("#baseUrl");
const token = document.querySelector("#token");
const status = document.querySelector("#status");

async function load() {
  const saved = await chrome.storage.sync.get({
    baseUrl: "https://droppedneedle.nodehaven.ca",
    token: ""
  });
  baseUrl.value = saved.baseUrl;
  token.value = saved.token;
}

document.querySelector("#save").addEventListener("click", async () => {
  await chrome.storage.sync.set({
    baseUrl: baseUrl.value.trim().replace(/\/$/, ""),
    token: token.value.trim()
  });
  status.textContent = "Saved.";
  setTimeout(() => { status.textContent = ""; }, 1500);
});

load();
