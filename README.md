# DroppedNeedle YouTube

One-click **Add to DroppedNeedle** from YouTube.

This project is being built as two pieces:

- a DroppedNeedle Plugin API v1 plugin for identifying a YouTube video's song and handing it to DroppedNeedle's normal request flow;
- a Manifest V3 browser extension that captures the current YouTube video and presents the match/confirmation UI.

## Status

Initial scaffold. The DroppedNeedle plugin contract is stable at `api_version = 1`; the exact host request integration is being wired against DroppedNeedle's current API.

## Intended flow

1. Open a YouTube video.
2. Click the DroppedNeedle extension.
3. The extension sends the URL/title/channel to the DroppedNeedle plugin.
4. The plugin normalizes the video metadata and searches for likely music matches.
5. The extension shows the best match/candidates.
6. Confirm **Add Track**.
7. DroppedNeedle handles acquisition, verification, and library import normally.

The plugin does **not** download or rip YouTube audio.
