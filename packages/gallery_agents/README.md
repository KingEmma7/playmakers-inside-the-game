# gallery-agents

Phase 2A runs a Microsoft Agent Framework Director workflow: Stats → parallel
Tactics/Storyline Agents → Compliance → Graphics → Audience.

`python -m gallery_agents demo --seed 7 --speed 50 --persona analyst` prints cues and traces
and writes framework checkpoints to `data/checkpoints`. Use `--limit 10 --speed 0` for a smoke check.
Default models are credential-free deterministic mock clients. Azure/Foundry selection,
MCP configuration and remaining Phase 2B features are described in the root README.

`python -m gallery_agents.export_schemas` refreshes the committed v1 overlay and trace schemas.
