"""Private JSON-lines operations worker for the Rust MCP transport."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .backend import NativeBackend
from .live.client import LiveClient
from .server import build_server
from .service import Operations


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--dia-binary", default="dia")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--live-socket", type=Path)
    args = parser.parse_args()
    if not 0 < args.timeout <= 300:
        parser.error("--timeout must be between 0 and 300 seconds")
    operations = Operations(
        NativeBackend(args.dia_binary, args.timeout),
        args.workspace,
        live=LiveClient(args.live_socket, min(args.timeout, 30)) if args.live_socket else None,
    )
    server = build_server(operations)
    sys.stdout.write('{"ready":true}\n')
    sys.stdout.flush()

    async def dispatch(request):
        kind = request["kind"]
        if kind == "tool":
            result = await server._tool_manager.call_tool(
                request["name"], request.get("arguments") or {}
            )
            return {"value": result}
        if kind == "resource":
            resource = await server._resource_manager.get_resource(request["uri"])
            if resource is None:
                raise ValueError("Unknown resource")
            content = await resource.read()
            return {"value": content}
        if kind == "prompt":
            result = await server._prompt_manager.render_prompt(
                request["name"], request.get("arguments") or {}
            )
            return {"value": [message.model_dump(mode="json") for message in result]}
        raise ValueError("Unknown request kind")

    for line in sys.stdin:
        try:
            response = asyncio.run(dispatch(json.loads(line)))
        except Exception as exc:
            response = {"error": str(exc)}
        sys.stdout.write(json.dumps(response, default=str) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
