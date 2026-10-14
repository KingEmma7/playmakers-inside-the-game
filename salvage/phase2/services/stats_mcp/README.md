# stats-mcp

Streamable HTTP MCP server exposing deterministic stats tools for Gallery.

Run:

```bash
python -m pip install -e services/stats_mcp -e packages/gallery_stats -e packages/gallery_schema
python -m stats_mcp --port 43124
```

MCP endpoint: `http://127.0.0.1:43124/mcp`

