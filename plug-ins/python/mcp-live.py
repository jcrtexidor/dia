# Optional external package; normal Dia and snapshot startup do not depend on MCP.
try:
    from dia_mcp.live.plugin import enable
except ModuleNotFoundError as exc:
    if exc.name not in {"dia_mcp", "dia_mcp.live", "dia_mcp.live.plugin"}:
        raise
else:
    enable()
