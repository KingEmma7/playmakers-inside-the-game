# replay-api

FastAPI service that replays a deterministic PitchSim match stream over:

- Server-Sent Events: `GET /replay/sse?seed=123&speed=10`
- WebSocket: `WS /replay/ws?seed=123&speed=10`

