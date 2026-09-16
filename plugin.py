"""DroppedNeedle Plugin API v1 adapter for identifying a YouTube video's song."""

from __future__ import annotations

import re
from typing import Any

from infrastructure.plugins.protocols import PluginRouteResponse

_MB_RECORDING_SEARCH = "https://musicbrainz.org/ws/2/recording/"
_NOISE = re.compile(
    r"\s*[\[(](?:official(?:\s+music)?\s+video|official\s+audio|audio|lyrics?|lyric\s+video|visuali[sz]er|hd|4k)[^\])]*[\])]\s*",
    re.IGNORECASE,
)
_FEAT = re.compile(r"\s+(?:ft\.?|feat\.?)\s+", re.IGNORECASE)


class YouTubeLinkPlugin:
    def __init__(self, context):
        self.ctx = context

    async def handle_route(
        self, method: str, subpath: str, query: dict, body: object
    ) -> PluginRouteResponse:
        if method != "POST" or subpath != "identify":
            return PluginRouteResponse(status=404, body={"error": "not_found"})
        if not isinstance(body, dict):
            return PluginRouteResponse(status=400, body={"error": "invalid_body"})

        title = str(body.get("title") or "").strip()
        channel = str(body.get("channel") or "").strip()
        if not title:
            return PluginRouteResponse(status=400, body={"error": "title_required"})

        artist_hint, title_hint = self._parse_youtube_title(title, channel)
        matches = await self._musicbrainz_search(artist_hint, title_hint)
        return PluginRouteResponse(
            status=200,
            body={
                "input": {
                    "title": title,
                    "channel": channel,
                    "artist_hint": artist_hint,
                    "title_hint": title_hint,
                },
                "matches": matches,
            },
        )

    @staticmethod
    def _parse_youtube_title(title: str, channel: str) -> tuple[str, str]:
        cleaned = _NOISE.sub(" ", title).strip(" -–—|\t")
        cleaned = re.sub(r"\s+", " ", cleaned)

        for separator in (" - ", " – ", " — ", " | "):
            if separator in cleaned:
                artist, track = cleaned.split(separator, 1)
                return artist.strip(), track.strip()

        artist = re.sub(r"(?:VEVO|Official|Music)$", "", channel, flags=re.IGNORECASE).strip()
        return artist, cleaned

    async def _musicbrainz_search(self, artist: str, title: str) -> list[dict[str, Any]]:
        query_parts = [f'recording:"{self._lucene(title)}"']
        if artist:
            query_parts.append(f'artist:"{self._lucene(artist)}"')

        response = await self.ctx.http.get(
            _MB_RECORDING_SEARCH,
            params={"query": " AND ".join(query_parts), "fmt": "json", "limit": 8},
        )
        response.raise_for_status()
        payload = response.json()

        matches: list[dict[str, Any]] = []
        seen: set[str] = set()
        for recording in payload.get("recordings", []):
            recording_id = recording.get("id")
            if not recording_id or recording_id in seen:
                continue
            seen.add(recording_id)

            credits = recording.get("artist-credit") or []
            artist_name = "".join(
                str(part.get("name") or part.get("artist", {}).get("name") or "")
                + str(part.get("joinphrase") or "")
                for part in credits
                if isinstance(part, dict)
            ).strip()
            artist_mbid = next(
                (
                    part.get("artist", {}).get("id")
                    for part in credits
                    if isinstance(part, dict) and part.get("artist", {}).get("id")
                ),
                None,
            )

            release = self._best_release(recording.get("releases") or [])
            score = max(0.0, min(1.0, float(recording.get("score") or 0) / 100.0))
            matches.append(
                {
                    "recording_mbid": recording_id,
                    "artist": artist_name or artist,
                    "artist_mbid": artist_mbid,
                    "title": recording.get("title") or title,
                    "duration_seconds": self._duration(recording.get("length")),
                    "album": release.get("title"),
                    "year": self._year(release.get("date")),
                    "release_id": release.get("id"),
                    "release_group_mbid": (release.get("release-group") or {}).get("id"),
                    "score": score,
                }
            )

        matches.sort(key=lambda item: item["score"], reverse=True)
        return matches[:5]

    @staticmethod
    def _best_release(releases: list[dict[str, Any]]) -> dict[str, Any]:
        if not releases:
            return {}
        return sorted(
            releases,
            key=lambda release: (
                0 if (release.get("status") or "").casefold() == "official" else 1,
                release.get("date") or "9999",
            ),
        )[0]

    @staticmethod
    def _duration(length_ms: object) -> int | None:
        try:
            return round(int(length_ms) / 1000) if length_ms is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _year(date: object) -> int | None:
        value = str(date or "")
        try:
            return int(value[:4]) if len(value) >= 4 else None
        except ValueError:
            return None

    @staticmethod
    def _lucene(value: str) -> str:
        value = _FEAT.split(value, 1)[0]
        return value.replace("\\", " ").replace('"', " ").strip()
