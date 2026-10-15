# stats-mcp

Streamable HTTP MCP server exposing deterministic stats tools for Playmakers.

Run:

```bash
python -m pip install -e services/stats_mcp -e packages/playmakers_stats -e packages/playmakers_schema
python -m stats_mcp --port 43124
```

MCP endpoint: `http://127.0.0.1:43124/mcp`

