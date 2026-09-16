"""DroppedNeedle Plugin API v1 adapter for identifying a YouTube video's song."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from infrastructure.plugins.protocols import PluginRouteResponse

_NOISE = re.compile(
    r"\s*[\[(](?:official(?:\s+music)?\s+video|official\s+audio|audio|lyrics?|lyric\s+video|visuali[sz]er|hd|4k)[^\])]*[\])]\s*",
    re.IGNORECASE,
)
_TRAILING_NOISE = re.compile(
    r"(?:\s*[-–—|:]?\s*)(?:official(?:\s+music)?\s+video|official\s+audio|audio|lyrics?|lyric\s+video|visuali[sz]er|hd|4k)\s*$",
    re.IGNORECASE,
)
_COMPILATION_HINTS = (
    "various artists", "mastermix", "now that's what i call", "now dance",
    "greatest hits", "best of", "chart hits", "club hits", "dance hits",
    "hits 20", "hits 19", "hits 18", "hits 17", "hits 16", "hits 15",
)
_REMIX_HINTS = (" remix", " mix)", " mix]", " edit", " version", " instrumental", " karaoke")


class YouTubeLinkPlugin:
    def __init__(self, context):
        self.ctx = context

    async def handle_route(self, method: str, subpath: str, query: dict, body: object) -> PluginRouteResponse:
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
            return PluginRouteResponse(status=200, body={
                "input": self._input(title, channel, artist_hint, title_hint),
                "matches": [],
                "warning": "Could not determine both artist and track title from this video.",
            })

        try:
            matches = await self._droppedneedle_recording_search(artist_hint, title_hint)
        except Exception as exc:
            self.ctx.logger.exception("DroppedNeedle recording search failed: %s", exc)
            return PluginRouteResponse(status=200, body={
                "input": self._input(title, channel, artist_hint, title_hint),
                "matches": [],
                "warning": "DroppedNeedle could not search its music catalogue right now.",
            })

        return PluginRouteResponse(status=200, body={
            "input": self._input(title, channel, artist_hint, title_hint),
            "matches": matches,
        })

    @staticmethod
    def _input(title: str, channel: str, artist: str, track: str) -> dict[str, str]:
        return {"title": title, "channel": channel, "artist_hint": artist, "title_hint": track}

    @staticmethod
    def _clean_title_noise(value: str) -> str:
        cleaned = _NOISE.sub(" ", value)
        cleaned = _TRAILING_NOISE.sub("", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip(" -–—|\t")

    @classmethod
    def _parse_youtube_title(cls, title: str, channel: str) -> tuple[str, str]:
        # Split the original title first, then clean artist/track independently.
        # This prevents bracketed labels such as "Kid Ink - Trim [Audio]" from
        # surviving when YouTube uses slightly unusual whitespace/Unicode.
        normalized = re.sub(r"\s+", " ", title).strip()
        for separator in (" - ", " – ", " — ", " | "):
            if separator in normalized:
                artist, track = normalized.split(separator, 1)
                return cls._clean_title_noise(artist), cls._clean_title_noise(track)

        cleaned = cls._clean_title_noise(normalized)
        artist = re.sub(r"(?:VEVO|Official|Music)$", "", channel, flags=re.IGNORECASE).strip()
        return artist, cleaned

    async def _droppedneedle_recording_search(self, artist: str, title: str) -> list[dict[str, Any]]:
        from core.dependencies.repo_providers import get_musicbrainz_repository
        from core.dependencies.service_providers import get_library_manager

        repo = get_musicbrainz_repository()
        library = get_library_manager()
        recordings = await repo.search_recordings(artist, title, limit=8)
        matches: list[dict[str, Any]] = []

        for recording in recordings:
            release_groups = list(recording.release_groups or [])
            release = self._best_release(release_groups, title)
            mb_score = self._score(recording.score)
            rank_score = self._rank_score(recording, release, artist, title, mb_score)
            recording_mbid = recording.recording_mbid
            try:
                in_library = bool(recording_mbid and await library.has_track(recording_mbid))
            except Exception as exc:
                self.ctx.logger.warning("Library lookup failed for %s: %s", recording_mbid, exc)
                in_library = False
            matches.append({
                "recording_mbid": recording_mbid,
                "artist": recording.artist or artist,
                "artist_mbid": None,
                "title": recording.title or title,
                "duration_seconds": None,
                "album": release.release_group_title if release else None,
                "year": self._year(release.release_date if release else None),
                "release_id": release.release_mbid if release else None,
                "release_group_mbid": release.release_group_mbid if release else None,
                "score": mb_score,
                "rank_score": round(rank_score, 4),
                "recommended": False,
                "in_library": in_library,
            })

        matches.sort(key=lambda item: item["rank_score"], reverse=True)
        matches = matches[:5]
        if matches:
            matches[0]["recommended"] = True
        return matches

    @classmethod
    def _best_release(cls, releases: list[Any], track_title: str):
        if not releases:
            return None
        target = cls._norm(track_title)
        return min(releases, key=lambda release: (
            0 if cls._norm(release.release_group_title) == target else 1,
            1 if cls._looks_compilation(release.release_group_title) else 0,
            0 if (release.primary_type or "").casefold() in {"single", "album", "ep"} else 1,
            release.release_date or "9999",
        ))

    @classmethod
    def _rank_score(cls, recording: Any, release: Any, artist: str, title: str, mb_score: float) -> float:
        rec_title = recording.title or ""
        rec_artist = recording.artist or ""
        score = mb_score * 0.55
        score += cls._similarity(rec_title, title) * 0.25
        score += cls._similarity(rec_artist, artist) * 0.15
        if release:
            album = release.release_group_title or ""
            if cls._norm(album) == cls._norm(title):
                score += 0.12
            if cls._looks_compilation(album):
                score -= 0.12
        if cls._is_variant(rec_title) and not cls._is_variant(title):
            score -= 0.15
        return score

    @staticmethod
    def _norm(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()

    @classmethod
    def _similarity(cls, left: str, right: str) -> float:
        return SequenceMatcher(None, cls._norm(left), cls._norm(right)).ratio()

    @staticmethod
    def _looks_compilation(value: str) -> bool:
        lowered = (value or "").casefold()
        return any(hint in lowered for hint in _COMPILATION_HINTS)

    @staticmethod
    def _is_variant(value: str) -> bool:
        lowered = (value or "").casefold()
        return any(hint in lowered for hint in _REMIX_HINTS)

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
