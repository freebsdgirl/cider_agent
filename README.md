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
- `CIDER_AGENT_RESPONSE_DETAIL`
- `CIDER_AGENT_SESSION_RECENT_TRACKS_LIMIT`
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
cider-agent preferences remember like "k-pop" --category genre
cider-agent recommend --play
```

A2A server:

```bash
cider-agent-serve
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
- `play_session`, `steer_session`, `session_status`, `stop_session`
- `seek`, `set_volume`
- `get_queue`, `move_queue_item`, `remove_queue_item`, `clear_queue`
- `search`, `search_catalog`, `search_library`, `search_library_tracks`
- `list_library_playlists`, `get_library_playlist_tracks`
- `remember_preference`, `list_preferences`, `forget_preference`
- `recommend`, `play_recommendation`

## Notes

- The RPC client sends both `apptoken` and `apitoken` headers because shipped Cider builds vary.
- Generic `search` uses `default_search_source` from config, which defaults to `catalog`.
- Text requests go through the configured resolver backend. `fallback` only supports tiny direct commands like `play` and `pause`; `openai_compatible` sends chat-completions requests to a configurable OpenAI-style endpoint, including local endpoints such as Ollama when they expose the same API shape.
- The intended A2A usage is text-first. Structured action payloads exist as an advanced path, but upstream conversational agents do not need to know them to use `cider_agent`.
- Generic or descriptive `play` requests now start an adaptive long-form session instead of only picking one song. The service stores one active session, keeps a bounded recent-track history, and refills the Cider queue incrementally while the long-running server is running.
- Artist-only or vibe-based requests are treated as adaptive sessions; specific track requests still resolve to one-shot playback.
- Mid-session steering requests such as "more pop" or "more of this artist" update the active session and refill the queue against that new direction.
- `resolver_include_reasoning` is a debug-only option. When enabled, `cider_agent` will include model-provided reasoning text in output if the resolver backend returns it.
- `resolver_include_raw_output` is another debug-only option. When enabled, `cider_agent` will include the resolver's exact raw `message.content` string as `resolver_raw_content`, plus the parsed JSON object as `resolver_raw_action`.
- `include_timing_debug` is another debug-only option. When enabled, `cider_agent` will attach timing breakdowns to text requests and adaptive session execution so you can see whether latency is coming from resolver calls, Cider RPC state snapshots, catalog lookups, or playback actions.
- `response_detail` defaults to `compact`, which trims tool-facing execution results down to compact summaries instead of returning full raw Apple Music and Cider payloads. Set it to `debug` during development if you want the larger result objects back.
- `session_recent_tracks_limit` controls how many previously played session tracks are provided back to the resolver to discourage repeats. The default is `20`.
- `global_recent_tracks_limit` controls how many recently played tracks across all sessions are fed back into adaptive planning and exclusion logic to reduce repetitive starter picks across separate play requests. The default is `50`.
- The default request timeout is 60 seconds to accommodate slower local models and Cider RPC calls.
- Live verification against a current Cider build showed `/api/v1/amapi/run-v3` behaves as a read-only `path` passthrough. Playlist creation and add-track mutation are therefore not exposed in this version of `cider_agent`.
- The web UI is intentionally not part of v1, but the service layer is transport-agnostic so a future local UI can reuse the same operations.
