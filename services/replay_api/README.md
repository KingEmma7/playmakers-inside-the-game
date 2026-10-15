# Replay API

```bash
uvicorn replay_api.main:app --reload --port 8000
curl -N "http://localhost:8000/playmakers/sse?seed=7&speed=50&kill=tactics@20"
```

`/replay/sse` and `/replay/ws` stream synthetic match events. `/playmakers/sse` and
`/playmakers/ws` stream flat event, cue and trace messages (`type` discriminates).
Playmakers parameters: seed, speed, persona, language, favourite_team_id,
favourite_player_id, kill, whatif_rollouts. Speed 0 skips replay waits.
Stats MCP is mounted at `/stats-mcp/`; CORS allows `http://localhost:5173`.
Each playmakers connection has isolated ephemeral state and file checkpoints.
See the root README for offline setup, personalization and kill/recovery details.
