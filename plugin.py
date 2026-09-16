"""DroppedNeedle Plugin API v1 adapter for identifying a YouTube video's song."""

from __future__ import annotations

import re
from typing import Any

from infrastructure.plugins.protocols import PluginRouteResponse

_NOISE = re.compile(
    r"\s*[\[(](?:official(?:\s+music)?\s+video|official\s+audio|audio|lyrics?|lyric\s+video|visuali[sz]er|hd|4k)[^\])]*[\])]\s*",
    re.IGNORECASE,
)


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
        if not artist_hint or not title_hint:
            return PluginRouteResponse(
                status=200,
                body={
                    "input": self._input(title, channel, artist_hint, title_hint),
                    "matches": [],
                    "warning": "Could not determine both artist and track title from this video.",
                },
            )

        try:
            matches = await self._droppedneedle_recording_search(artist_hint, title_hint)
        except Exception as exc:
            self.ctx.logger.exception("DroppedNeedle recording search failed: %s", exc)
            return PluginRouteResponse(
                status=200,
                body={
                    "input": self._input(title, channel, artist_hint, title_hint),
                    "matches": [],
                    "warning": "DroppedNeedle could not search its music catalogue right now.",
                },
            )

        return PluginRouteResponse(
            status=200,
            body={
                "input": self._input(title, channel, artist_hint, title_hint),
                "matches": matches,
            },
        )

    @staticmethod
    def _input(title: str, channel: str, artist: str, track: str) -> dict[str, str]:
        return {
            "title": title,
            "channel": channel,
            "artist_hint": artist,
            "title_hint": track,
        }

    @staticmethod
    def _parse_youtube_title(title: str, channel: str) -> tuple[str, str]:
        cleaned = _NOISE.sub(" ", title).strip(" -–—|\t")
        cleaned = re.sub(r"\s+", " ", cleaned)

        for separator in (" - ", " – ", " — ", " | "):
            if separator in cleaned:
                artist, track = cleaned.split(separator, 1)
                return artist.strip(), track.strip()

        artist = re.sub(
            r"(?:VEVO|Official|Music)$", "", channel, flags=re.IGNORECASE
        ).strip()
        return artist, cleaned

    async def _droppedneedle_recording_search(
        self, artist: str, title: str
    ) -> list[dict[str, Any]]:
        # Plugin API v1 intentionally exposes no catalogue-search method on
        # PluginContext. Because plugins execute in-process, use DroppedNeedle's
        # singleton repository so this request follows the instance's configured
        # MusicBrainz/BrainzMash source, limiter, cache and degradation handling.
        from core.dependencies.repo_providers import get_musicbrainz_repository

        repo = get_musicbrainz_repository()
        recordings = await repo.search_recordings(artist, title, limit=8)

        matches: list[dict[str, Any]] = []
        for recording in recordings[:5]:
            release_groups = list(recording.release_groups or [])
            release = release_groups[0] if release_groups else None
            matches.append(
                {
                    "recording_mbid": recording.recording_mbid,
                    "artist": recording.artist or artist,
                    "artist_mbid": None,
                    "title": recording.title or title,
                    "duration_seconds": None,
                    "album": release.release_group_title if release else None,
                    "year": self._year(release.release_date if release else None),
                    "release_id": release.release_mbid if release else None,
                    "release_group_mbid": (
                        release.release_group_mbid if release else None
                    ),
                    "score": self._score(recording.score),
                }
            )

        matches.sort(key=lambda item: item["score"], reverse=True)
        return matches

    @staticmethod
    def _score(value: object) -> float:
        try:
            score = float(value or 0)
        except (TypeError, ValueError):
            return 0.0
        if score > 1:
            score /= 100.0
        return max(0.0, min(1.0, score))

    @staticmethod
    def _year(date: object) -> int | None:
        value = str(date or "")
        try:
            return int(value[:4]) if len(value) >= 4 else None
        except ValueError:
            return None
