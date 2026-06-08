# Cider Agent

`cider_agent` is a standalone Python service that owns audio control for the Cider Apple Music client. It gives other agents a text-first A2A endpoint for delegating music tasks, plus a local CLI for direct use.

V1 includes:

- playback control
- queue inspection and mutation
- Apple Music catalog and library search
- library playlist browse
- explicit preference memory in SQLite
- deterministic preference-based recommendations with a pluggable recommender seam
- optional OpenAI-compatible text resolver for natural-language requests

## Requirements

- Python 3.12+
- Cider running locally
- Cider external application access enabled
- a Cider API token if your Cider build requires one

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cp config.example.json config.json
```

## Configuration

Config resolution order:

1. `CIDER_AGENT_CONFIG_PATH`
2. `./config.json`
3. `~/.config/cider-agent/config.json`

Environment variable overrides are available for every field:

- `CIDER_AGENT_HTTP_HOST`
- `CIDER_AGENT_HTTP_PORT`
- `CIDER_AGENT_PUBLIC_BASE_URL`
- `CIDER_AGENT_CIDER_BASE_URL`
- `CIDER_AGENT_CIDER_API_TOKEN`
- `CIDER_AGENT_DEFAULT_SEARCH_SOURCE`
- `CIDER_AGENT_RESOLVER_BACKEND`
- `CIDER_AGENT_RESOLVER_BASE_URL`
- `CIDER_AGENT_RESOLVER_MODEL`
- `CIDER_AGENT_RESOLVER_API_KEY`
- `CIDER_AGENT_RESOLVER_INCLUDE_REASONING`
- `CIDER_AGENT_RESOLVER_INCLUDE_RAW_OUTPUT`
- `CIDER_AGENT_RESOLVER_DEBUG_LOG_PATH`
- `CIDER_AGENT_INCLUDE_TIMING_DEBUG`
- `CIDER_AGENT_RESPONSE_DETAIL`
- `CIDER_AGENT_SESSION_RECENT_TRACKS_LIMIT`
- `CIDER_AGENT_GLOBAL_RECENT_TRACKS_LIMIT`
- `CIDER_AGENT_REQUEST_TIMEOUT_SECONDS`
- `CIDER_AGENT_VERIFY_TLS`
- `CIDER_AGENT_LOG_LEVEL`
- `CIDER_AGENT_DATABASE_PATH`

## Run

CLI:

```bash
cider-agent status
cider-agent now-playing
cider-agent search default "k-pop"
cider-agent search library "k-pop"
cider-agent search catalog "k-pop"
cider-agent ask "play some kep1er"
cider-agent ask "play something upbeat for the morning"
cider-agent session status
cider-agent session refill
cider-agent ask "i don't like this"
cider-agent preferences remember like "k-pop" --category genre
cider-agent recommend --play
cider-agent serve
```

A2A server:

```bash
cider-agent-serve
# or
cider-agent serve
```

Published endpoints:

- `POST /a2a`
- `GET /.well-known/agent.json`
- `GET /.well-known/agent-card.json`
- `GET /healthz`

## A2A integration

The intended integration path is plain-language text requests over A2A. Upstream conversational agents do not need to know the internal action schema. In the common case, they only need to know:

- `cider_agent` exists
- it accepts natural-language music requests
- it returns compact structured results

Recommended request shape:

```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "method": "message/send",
  "params": {
    "message": {
      "kind": "message",
      "messageId": "msg-1",
      "role": "user",
      "parts": [
        {
          "kind": "text",
          "text": "play upbeat morning music"
        }
      ]
    }
  }
}
```

Typical text requests:

- `play upbeat morning music`
- `add some KATSEYE`
- `more pop`
- `i don't like this`
- `what's playing?`

Responses include a compact `summary` field for tool-friendly consumption, plus the structured execution payload.

## Advanced structured actions

Structured requests still exist for advanced integrations and testing, but they are not required for ordinary use.

Structured requests should send a `data` part:

```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "method": "message/send",
  "params": {
    "message": {
      "kind": "message",
      "messageId": "msg-1",
      "role": "user",
      "parts": [
        {
          "kind": "data",
          "data": {
            "action": "play_session",
            "parameters": {
              "request": "play upbeat morning music"
            }
          }
        }
      ]
    }
  }
}
```

Common structured actions:

- `status`
- `get_now_playing`
- `play`, `pause`, `playpause`, `stop`, `next_track`, `previous_track`
- `play_session`, `steer_session`, `reject_current_track`, `session_status`, `stop_session`, `refill_session`
- `seek`, `set_volume`
- `get_queue`, `move_queue_item`, `remove_queue_item`, `clear_queue`
- `search`, `search_catalog`, `search_catalog_tracks`, `search_library`, `search_library_tracks`
- `list_library_playlists`, `search_library_playlists`, `get_library_playlist`, `get_library_playlist_tracks`
- `list_recently_played`
- `create_playlist`, `add_playlist_tracks`
- `remember_preference`, `list_preferences`, `forget_preference`
- `recommend`, `play_recommendation`

Playlist mutation actions are part of the structured surface, but current Cider RPC builds do not expose working mutation endpoints through `/api/v1/amapi/run-v3`, so `create_playlist` and `add_playlist_tracks` currently fail with a clear RPC error instead of mutating anything.

## Notes

- The RPC client sends both `apptoken` and `apitoken` headers because shipped Cider builds vary.
- Generic `search` uses `default_search_source` from config, which defaults to `catalog`.
- Text requests go through the configured resolver backend. `fallback` only supports tiny direct commands like `play` and `pause`; `openai_compatible` sends chat-completions requests to a configurable OpenAI-style endpoint, including local endpoints such as Ollama when they expose the same API shape.
- The intended A2A usage is text-first. Structured action payloads exist as an advanced path, but upstream conversational agents do not need to know them to use `cider_agent`.
- Generic or descriptive `play` requests start an adaptive session instead of only picking one song. Artist-only, genre-only, and vibe-based requests are usually treated as adaptive sessions; specific track requests still resolve to one-shot playback.
- The adaptive session runtime stores per-query search pools, not one flat shared candidate list. Each active query pool caches up to 100 real catalog tracks, fetched as two paginated catalog-search calls of 50 because current Cider RPC builds reject larger per-request search limits.
- Track selection is cache-driven. The resolver only sees the next eligible window of 6 tracks from the current pool cursor, and cache entry state drives repeat avoidance and retry behavior.
- Each cached track entry is tracked as `fresh`, `played`, `screened_out`, or `rejected`.
- `played` means the track was selected and played in the current cache lifecycle.
- `screened_out` means the resolver saw that track in a 6-track window and returned `selected_index = -1` for that window.
- `rejected` means the user explicitly rejected the current track. Rejected entries stay unavailable until the query pool is replaced.
- When a pool runs out of `fresh` candidates, the service first resets `screened_out`, then later resets `played` after full-pass exhaustion. If all entries in a pool become effectively unusable, the service can replan or rebuild pools before finally giving up with `No playable candidate match could be resolved.`
- Mid-session steering requests such as "more pop" or "more of this artist" update persistent session steering state. `steer_session` also accepts an optional `search_update` object with `mode` of `preserve`, `add`, or `replace`.
- `preserve` keeps the current query pools and only changes future selection behavior.
- `add` keeps the current pools and adds newly planned search pools alongside them.
- `replace` discards the current pools and rebuilds from the replacement query set.
- `reject_current_track` is the "skip this one, keep the vibe" action. It marks the current cached entry as rejected and immediately advances within the active session.
- `resolver_include_reasoning` is a debug-only option. When enabled, `cider_agent` will include model-provided reasoning text in output if the resolver backend returns it.
- `resolver_include_raw_output` is another debug-only option. When enabled, `cider_agent` will include the resolver's exact raw `message.content` string as `resolver_raw_content`, plus the parsed JSON object as `resolver_raw_action`.
- `resolver_debug_log_path` is another debug-only option. When set, `cider_agent` keeps a plain-text resolver trace file for the current resolver episode, wiping it each time a new episode starts and appending every resolver prompt/response involved in that episode. That includes session start, manual refill, reject-current, and automatic background-worker advance after a track ends.
- `include_timing_debug` is another debug-only option. When enabled, `cider_agent` will attach timing breakdowns to text requests and adaptive session execution so you can see whether latency is coming from resolver calls, Cider RPC state snapshots, catalog lookups, or playback actions.
- `response_detail` defaults to `compact`, which trims tool-facing execution results down to compact summaries instead of returning full raw Apple Music and Cider payloads. Set it to `debug` during development if you want the larger result objects back.
- `session_recent_tracks_limit` controls how many recent session tracks are returned in status-style responses and summaries. It does not drive adaptive track selection; the session cache does that now.
- `global_recent_tracks_limit` controls how many recently played tracks across all sessions are used when building brand-new, additive, or replacement adaptive query pools. It does not act as a hard exclusion against an already-built in-session cache. The default is `10`.
- Resolver session prompts are intentionally compact now. Session planning no longer includes recent session tracks, and session selection no longer includes recent/global track history or bulky track metadata like artwork URLs, ISRCs, or raw play params.
- The default request timeout is 60 seconds to accommodate slower local models and Cider RPC calls.
- Live verification against a current Cider build showed `/api/v1/amapi/run-v3` behaves as a read-only `path` passthrough. Playlist creation and add-track mutation are therefore not exposed in this version of `cider_agent`.
- The web UI is intentionally not part of v1, but the service layer is transport-agnostic so a future local UI can reuse the same operations.
