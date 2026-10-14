# Replay API

```bash
uvicorn replay_api.main:app --reload --port 8000
curl -N "http://localhost:8000/gallery/sse?seed=7&speed=50&kill=tactics@20"
```

`/replay/sse` and `/replay/ws` stream synthetic match events. `/gallery/sse` and
`/gallery/ws` stream flat event, cue and trace messages (`type` discriminates).
Gallery parameters: seed, speed, persona, language, favourite_team_id,
favourite_player_id, kill, whatif_rollouts. Speed 0 skips replay waits.
Stats MCP is mounted at `/stats-mcp/`; CORS allows `http://localhost:5173`.
Each gallery connection has isolated ephemeral state and file checkpoints.
See the root README for offline setup, personalization and kill/recovery details.
