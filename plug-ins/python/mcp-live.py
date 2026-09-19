# Optional external package; normal Dia startup does not depend on MCP.
import os

if os.environ.get("DIA_MCP_LIVE") == "1":
    from dia_mcp.live.plugin import enable

    enable()
