"""Search planning and queue materialization for
:class:`vesper.session.SessionEngine`.

Extracted behavior-preservingly from ``SessionEngine`` (issue #34). Covers
normalizing queue policy, computing the effective session request, materializing
the persisted session queue from planned sources, applying queue policies
(source-order/shuffle), claiming the next queue track, marking items played,
restoring current-item runtime on reconcile, and filtering the remaining queue.

Combined into ``SessionEngine`` via cooperative inheritance; ``self`` is the
engine instance and reads ``self._host``, ``self._preferences``,
``self._session_runtime``/``self._session_runtime_lock``, ``self._random``, and
the ``self._debug_candidate_*`` counters exactly as before. Cross-mixin calls
(e.g. ``self._normalize_search_sources``/``self._build_session_query_pool``)
resolve against the combined class.
"""

from __future__ import annotations

from typing import Any

from .resolver import (
    SessionQueryPlan,
    SessionQueueDecision,
    SessionSearchSource,
    SessionTrackSelection,
    _normalize_eligible_indices,
)
from .service import _clean_id


class SessionQueueMixin:
    """Normalize queue policy, compute the effective session request, plan a
    session query, materialize/append/filter the persisted session queue, and
    claim the next queue track.

    Expects the combined ``SessionEngine`` to provide ``self._host``,
    ``self._preferences``, ``self._session_runtime``/``self._session_runtime_lock``,
    ``self._random``, ``self._session_queue_batch_size``, and the
    ``self._debug_candidate_*`` counters.
    """

    def _normalize_queue_policy(self, value: Any) -> str:
        policy = str(value or "source_order").strip().lower()
        return policy if policy in {"source_order", "shuffle"} else "source_order"

    def _session_effective_request(self, session: dict[str, Any]) -> str:
        steering = session.get("steering_history", [])
        if not steering:
            return str(session.get("request_text", "")).strip()
        steering_text = " ".join(str(item).strip() for item in steering if str(item).strip())
        if not steering_text:
            return str(session.get("request_text", "")).strip()
        return f"{session.get('request_text', '').strip()} Current steering: {steering_text}".strip()

    def _ensure_materialized_session_queue(self, session: dict[str, Any], plan: SessionQueryPlan) -> None:
        existing = self._preferences.list_session_queue(session["id"], limit=1)
        if existing:
            return
        sources = self._plan_search_sources(plan)
        self._materialize_session_queue(
            session,
            sources,
            queue_policy=self._normalize_queue_policy(getattr(plan, "queue_policy", "source_order")),
        )

    def _copy_queue_materialization_timings(self, timings: dict[str, Any]) -> None:
        timings["candidate_track_search_count"] = getattr(self, "_debug_candidate_track_search_count", 0)
        timings["candidate_track_search_ms"] = round(getattr(self, "_debug_candidate_track_search_ms", 0.0), 2)
        timings["candidate_artist_search_count"] = getattr(self, "_debug_candidate_artist_search_count", 0)
        timings["candidate_artist_search_ms"] = round(getattr(self, "_debug_candidate_artist_search_ms", 0.0), 2)
        timings["candidate_query_search_count"] = getattr(self, "_debug_candidate_query_search_count", 0)
        timings["candidate_query_search_ms"] = round(getattr(self, "_debug_candidate_query_search_ms", 0.0), 2)
        timings["selection_candidate_count"] = 0

    def _materialize_session_queue(
        self,
        session: dict[str, Any],
        search_sources: list[SessionSearchSource],
        *,
        queue_policy: str,
        preserve_history: bool = False,
    ) -> None:
        queue_items = self._queue_items_for_sources(session, search_sources)
        queue_items = self._apply_queue_policy(queue_items, queue_policy)
        self._preferences.replace_session_queue(
            session["id"],
            queue_items,
            preserve_history=preserve_history,
        )
        self._set_session_runtime(
            session["id"],
            active_search_sources=self._host._sources_payload(self._normalize_search_sources(search_sources)),
        )
        self._host.append_session_debug_log(
            stage="session_queue_materialized",
            payload={
                "session_id": session.get("id"),
                "queue_policy": queue_policy,
                "queue_count": len(queue_items),
                "sources": self._host._sources_payload(self._normalize_search_sources(search_sources)),
            },
        )

    def _append_session_sources_to_queue(
        self,
        session: dict[str, Any],
        search_sources: list[SessionSearchSource],
        *,
        queue_policy: str,
    ) -> None:
        queue_items = self._apply_queue_policy(self._queue_items_for_sources(session, search_sources), queue_policy)
        self._preferences.append_session_queue(session["id"], queue_items)
        self._host.append_session_debug_log(
            stage="session_queue_appended",
            payload={
                "session_id": session.get("id"),
                "queue_policy": queue_policy,
                "queue_count": len(queue_items),
                "sources": self._host._sources_payload(self._normalize_search_sources(search_sources)),
            },
        )

    def _queue_items_for_sources(
        self,
        session: dict[str, Any],
        search_sources: list[SessionSearchSource],
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        runtime = self._get_session_runtime(session["id"])
        pools: dict[str, dict[str, Any]] = self._normalize_session_query_pools(runtime.get("query_pools"))
        for source in self._normalize_search_sources(search_sources):
            if source.kind == "preference":
                self._bootstrap_preference_seeded_session(session)
                runtime = self._get_session_runtime(session["id"])
                pools = self._normalize_session_query_pools(runtime.get("query_pools"))
                pool = pools.get(self._session_source_key(source)) or {
                    "source": {"kind": source.kind, "term": source.term},
                    "entries": [],
                }
            else:
                pool = self._build_session_query_pool(session, source)
            source_payload = {"kind": source.kind, "term": source.term}
            source_key = self._session_source_key(source)
            pools[source_key] = pool
            for entry in pool.get("entries", []):
                track = dict(entry.get("track") or {})
                track_id = _clean_id(track.get("id")) or _clean_id(track.get("play_params", {}).get("id"))
                if not track_id or track_id in seen_ids:
                    continue
                seen_ids.add(track_id)
                items.append({"source": source_payload, "source_key": source_key, "track": track})
        if pools:
            self._set_session_runtime(session["id"], query_pools=pools)
        return items

    def _apply_queue_policy(self, queue_items: list[dict[str, Any]], queue_policy: str) -> list[dict[str, Any]]:
        items = list(queue_items)
        if self._normalize_queue_policy(queue_policy) == "shuffle":
            self._random.shuffle(items)
        return items

    def _claim_session_queue_track(
        self,
        session: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], SessionSearchSource, SessionTrackSelection, dict[str, Any] | None]:
        self._mark_current_queue_item_played(session["id"])
        queue_item = self._preferences.claim_next_session_queue_item(session["id"])
        if queue_item is None:
            return [], SessionSearchSource(kind="vibe", term=""), SessionTrackSelection(selected_index=0, resolver="session-queue"), None
        source_values = queue_item.get("source")
        sources = self._normalize_search_sources([source_values] if isinstance(source_values, dict) else [])
        source = sources[0] if sources else SessionSearchSource(kind="vibe", term=str(queue_item.get("source_term") or ""))
        track = dict(queue_item.get("track") or {})
        track.setdefault("id", queue_item.get("track_id"))
        track.setdefault("title", queue_item.get("title"))
        track.setdefault("artist", queue_item.get("artist"))
        track.setdefault("album", queue_item.get("album"))
        track.setdefault("href", queue_item.get("href"))
        self._set_session_runtime(
            session["id"],
            current_pool_query=queue_item.get("source_key") or source.term,
            current_seed_query=str(track.get("_seed_query", "")).strip() or source.term,
            current_track_id=_clean_id(track.get("id")) or _clean_id(track.get("play_params", {}).get("id")),
        )
        return [track], source, SessionTrackSelection(selected_index=0, resolver="session-queue"), queue_item

    def _mark_current_queue_item_played(self, session_id: int) -> None:
        runtime = self._get_session_runtime(session_id)
        queue_item_id = runtime.get("current_queue_item_id")
        if isinstance(queue_item_id, int):
            self._preferences.mark_session_queue_item(queue_item_id, "played")
            self._set_session_runtime(session_id, current_queue_item_id=None)

    def _restore_current_queue_item_runtime(self, session_id: int, *, playback: dict[str, Any]) -> None:
        current = playback.get("track", {})
        current_track_id = _clean_id(current.get("track_id")) if isinstance(current, dict) else ""
        if not current_track_id:
            return
        for item in self._preferences.list_session_queue(session_id, limit=25, include_history=True):
            if item.get("state") != "playing":
                continue
            if _clean_id(item.get("track_id")) != current_track_id:
                continue
            self._set_session_runtime(session_id, current_queue_item_id=item["id"])
            return

    def _filter_remaining_session_queue(self, session: dict[str, Any]) -> None:
        remaining = self._preferences.list_session_queue(session["id"], limit=1000)
        if not remaining:
            return
        kept_items: list[dict[str, Any]] = []
        resolved_policy = "source_order"
        chooser = getattr(self._host._resolver, "filter_session_queue", None)
        for start in range(0, len(remaining), self._session_queue_batch_size):
            batch = remaining[start : start + self._session_queue_batch_size]
            candidates = [dict(item.get("track") or {}) for item in batch]
            decision = (
                chooser(self._session_effective_request(session), self._host, session, candidates)
                if callable(chooser)
                else SessionQueueDecision(eligible_indices=list(range(len(batch))), resolver="fallback")
            )
            eligible = _normalize_eligible_indices(getattr(decision, "eligible_indices", []), len(batch))
            resolved_policy = self._normalize_queue_policy(getattr(decision, "queue_policy", resolved_policy))
            for index in eligible:
                item = batch[index]
                kept_items.append(
                    {
                        "source": item.get("source"),
                        "source_key": item.get("source_key"),
                        "track": item.get("track"),
                    }
                )
        self._preferences.replace_session_queue(
            session["id"],
            self._apply_queue_policy(kept_items, resolved_policy),
            preserve_history=True,
        )
        self._host.append_session_debug_log(
            stage="session_queue_filtered",
            payload={
                "session_id": session.get("id"),
                "input_count": len(remaining),
                "output_count": len(kept_items),
                "queue_policy": resolved_policy,
            },
        )
