# stats-mcp

Run `python -m stats_mcp` after the root README editable installs.
Streamable HTTP endpoint: `http://127.0.0.1:8765/mcp`.
The replay API mounts the same server factory at `http://127.0.0.1:8000/stats-mcp/`.

Tools: `ingest_event`, `possession`, `pressure_index`, `pass_difficulty`, `xg`,
`momentum`, `control_vs_chaos`. All outputs have Pydantic contracts and evidence.
Match IDs must agree with ingested events; sequences must increase within each match.
