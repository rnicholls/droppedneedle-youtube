"""DroppedNeedle Plugin API v1 adapter for identifying a YouTube video's song."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from infrastructure.plugins.protocols import PluginRouteResponse

_NOISE = re.compile(r"\s*[\[(](?:official(?:\s+music)?\s+video|official\s+audio|audio|lyrics?|lyric\s+video|visuali[sz]er|hd|4k)[^\])]*[\])]\s*", re.IGNORECASE)
_TRAILING_NOISE = re.compile(r"(?:\s*[-–—|:]?\s*)(?:official(?:\s+music)?\s+video|official\s+audio|audio|lyrics?|lyric\s+video|visuali[sz]er|hd|4k)\s*$", re.IGNORECASE)
_COMPILATION_HINTS = ("various artists", "mastermix", "now that's what i call", "now dance", "greatest hits", "best of", "chart hits", "club hits", "dance hits", "hits 20", "hits 19", "hits 18", "hits 17", "hits 16", "hits 15")
_REMIX_HINTS = (" remix", " mix)", " mix]", " edit", " version", " instrumental", " karaoke")


class YouTubeLinkPlugin:
    def __init__(self, context): self.ctx = context

    async def handle_route(self, method: str, subpath: str, query: dict, body: object) -> PluginRouteResponse:
        if method != "POST" or subpath != "identify": return PluginRouteResponse(status=404, body={"error": "not_found"})
        if not isinstance(body, dict): return PluginRouteResponse(status=400, body={"error": "invalid_body"})
        title, channel = str(body.get("title") or "").strip(), str(body.get("channel") or "").strip()
        if not title: return PluginRouteResponse(status=400, body={"error": "title_required"})
        artist_hint, title_hint = self._parse_youtube_title(title, channel)
        if not artist_hint or not title_hint:
            return PluginRouteResponse(status=200, body={"input": self._input(title, channel, artist_hint, title_hint), "matches": [], "warning": "Could not determine both artist and track title from this video."})
        try:
            matches = await self._droppedneedle_recording_search(artist_hint, title_hint)
        except Exception as exc:
            self.ctx.logger.exception("DroppedNeedle recording search failed: %s", exc)
            return PluginRouteResponse(status=200, body={"input": self._input(title, channel, artist_hint, title_hint), "matches": [], "warning": "DroppedNeedle could not search its music catalogue right now."})
        return PluginRouteResponse(status=200, body={"input": self._input(title, channel, artist_hint, title_hint), "matches": matches})

    @staticmethod
    def _input(title, channel, artist, track): return {"title": title, "channel": channel, "artist_hint": artist, "title_hint": track}

    @staticmethod
    def _clean_title_noise(value: str) -> str:
        return re.sub(r"\s+", " ", _TRAILING_NOISE.sub("", _NOISE.sub(" ", value))).strip(" -–—|\t")

    @classmethod
    def _parse_youtube_title(cls, title: str, channel: str) -> tuple[str, str]:
        normalized = re.sub(r"\s+", " ", title).strip()
        for separator in (" - ", " – ", " — ", " | "):
            if separator in normalized:
                artist, track = normalized.split(separator, 1)
                return cls._clean_title_noise(artist), cls._clean_title_noise(track)
        artist = re.sub(r"(?:VEVO|Official|Music)$", "", channel, flags=re.IGNORECASE).strip()
        return artist, cls._clean_title_noise(normalized)

    async def _droppedneedle_recording_search(self, artist: str, title: str) -> list[dict[str, Any]]:
        from core.dependencies.repo_providers import get_musicbrainz_repository
        from core.dependencies.service_providers import get_library_manager
        repo, library = get_musicbrainz_repository(), get_library_manager()
        recordings = await repo.search_recordings(artist, title, limit=8)
        if recordings:
            return await self._map_internal_recordings(recordings, library, artist, title)
        self.ctx.logger.info("Configured MusicBrainz source returned no recordings for %s - %s; trying official MusicBrainz", artist, title)
        return await self._official_musicbrainz_search(artist, title, library)

    async def _map_internal_recordings(self, recordings, library, artist, title):
        matches = []
        for recording in recordings:
            release = self._best_release(list(recording.release_groups or []), title)
            mb_score = self._score(recording.score)
            recording_mbid = recording.recording_mbid
            matches.append({"recording_mbid": recording_mbid, "artist": recording.artist or artist, "artist_mbid": None, "title": recording.title or title, "duration_seconds": None, "album": release.release_group_title if release else None, "year": self._year(release.release_date if release else None), "release_id": release.release_mbid if release else None, "release_group_mbid": release.release_group_mbid if release else None, "score": mb_score, "rank_score": round(self._rank_score(recording, release, artist, title, mb_score), 4), "recommended": False, "in_library": await self._in_library(library, recording_mbid)})
        return self._finish(matches)

    async def _official_musicbrainz_search(self, artist: str, title: str, library) -> list[dict[str, Any]]:
        """Fallback only: query official MB when DroppedNeedle's configured source has no result."""
        import httpx
        from repositories.musicbrainz_base import build_recording_search_query
        query = build_recording_search_query(title, artist)
        headers = {"User-Agent": "DroppedNeedle-YouTube/0.2 (https://github.com/rnicholls/droppedneedle-youtube)"}
        async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
            response = await client.get("https://musicbrainz.org/ws/2/recording", params={"query": query, "limit": 8, "fmt": "json"})
            response.raise_for_status()
            data = response.json()
        matches = []
        for recording in data.get("recordings", []):
            mbid = recording.get("id")
            credits = recording.get("artist-credit") or []
            artist_name = "".join((c.get("name") or (c.get("artist") or {}).get("name") or "") + (c.get("joinphrase") or "") for c in credits).strip() or artist
            artist_mbid = (credits[0].get("artist") or {}).get("id") if len(credits) == 1 else None
            releases = recording.get("releases") or []
            best = self._best_official_release(releases, title)
            score = self._score(recording.get("score"))
            rec_title = recording.get("title") or title
            rank = score * .55 + self._similarity(rec_title, title) * .25 + self._similarity(artist_name, artist) * .15
            if best and self._norm((best.get("release-group") or {}).get("title") or best.get("title") or "") == self._norm(title): rank += .12
            if self._is_variant(rec_title) and not self._is_variant(title): rank -= .15
            rg = (best or {}).get("release-group") or {}
            matches.append({"recording_mbid": mbid, "artist": artist_name, "artist_mbid": artist_mbid, "title": rec_title, "duration_seconds": round(recording["length"] / 1000) if recording.get("length") else None, "album": rg.get("title") or (best or {}).get("title"), "year": self._year((best or {}).get("date") or rg.get("first-release-date")), "release_id": (best or {}).get("id"), "release_group_mbid": rg.get("id"), "score": score, "rank_score": round(rank, 4), "recommended": False, "in_library": await self._in_library(library, mbid)})
        return self._finish(matches)

    @classmethod
    def _best_official_release(cls, releases, title):
        if not releases: return None
        target = cls._norm(title)
        return min(releases, key=lambda r: (0 if cls._norm((r.get("release-group") or {}).get("title") or r.get("title") or "") == target else 1, 1 if cls._looks_compilation((r.get("release-group") or {}).get("title") or r.get("title") or "") else 0, r.get("date") or "9999"))

    async def _in_library(self, library, mbid):
        try: return bool(mbid and await library.has_track(mbid))
        except Exception as exc:
            self.ctx.logger.warning("Library lookup failed for %s: %s", mbid, exc); return False

    @staticmethod
    def _finish(matches):
        matches.sort(key=lambda x: x["rank_score"], reverse=True); matches = matches[:5]
        if matches: matches[0]["recommended"] = True
        return matches

    @classmethod
    def _best_release(cls, releases, track_title):
        if not releases: return None
        target = cls._norm(track_title)
        return min(releases, key=lambda r: (0 if cls._norm(r.release_group_title) == target else 1, 1 if cls._looks_compilation(r.release_group_title) else 0, 0 if (r.primary_type or "").casefold() in {"single", "album", "ep"} else 1, r.release_date or "9999"))

    @classmethod
    def _rank_score(cls, recording, release, artist, title, mb_score):
        score = mb_score * .55 + cls._similarity(recording.title or "", title) * .25 + cls._similarity(recording.artist or "", artist) * .15
        if release:
            if cls._norm(release.release_group_title or "") == cls._norm(title): score += .12
            if cls._looks_compilation(release.release_group_title or ""): score -= .12
        if cls._is_variant(recording.title or "") and not cls._is_variant(title): score -= .15
        return score

    @staticmethod
    def _norm(value): return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()
    @classmethod
    def _similarity(cls, left, right): return SequenceMatcher(None, cls._norm(left), cls._norm(right)).ratio()
    @staticmethod
    def _looks_compilation(value): return any(h in (value or "").casefold() for h in _COMPILATION_HINTS)
    @staticmethod
    def _is_variant(value): return any(h in (value or "").casefold() for h in _REMIX_HINTS)
    @staticmethod
    def _score(value):
        try: score = float(value or 0)
        except (TypeError, ValueError): return 0.0
        if score > 1: score /= 100.0
        return max(0.0, min(1.0, score))
    @staticmethod
    def _year(date):
        try: return int(str(date or "")[:4]) if len(str(date or "")) >= 4 else None
        except ValueError: return None
