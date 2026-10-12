"""Generate the stable MCP catalog consumed by the Rust transport."""

import argparse
import inspect
import json
from pathlib import Path

from dia_mcp.server import build_server


def catalog():
    server = build_server(None)
    return {
        "tools": [
            {
                "name": tool.name,
                "description": inspect.cleandoc(tool.description or ""),
                "inputSchema": tool.parameters,
                "annotations": tool.annotations.model_dump(exclude_none=True),
            }
            for tool in server._tool_manager.list_tools()
        ],
        "resources": [
            {
                "uri": str(resource.uri),
                "name": resource.name,
                "description": resource.description,
                "mimeType": resource.mime_type,
            }
            for resource in server._resource_manager.list_resources()
        ],
        "resourceTemplates": [
            {
                "uriTemplate": str(resource.uri_template),
                "name": resource.name,
                "description": resource.description,
                "mimeType": resource.mime_type,
            }
            for resource in server._resource_manager.list_templates()
        ],
        "prompts": [
            {
                "name": prompt.name,
                "description": prompt.description,
                "arguments": [
                    argument.model_dump(exclude_none=True) for argument in prompt.arguments
                ],
            }
            for prompt in server._prompt_manager.list_prompts()
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = Path(__file__).parents[2] / "protocol-catalog.json"
    content = json.dumps(catalog(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if path.read_text() != content:
            parser.error("protocol-catalog.json is stale; regenerate it")
    else:
        path.write_text(content)


if __name__ == "__main__":
    main()
