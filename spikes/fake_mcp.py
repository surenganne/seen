"""Minimal stdio MCP server for P0-12: one tool returning synthetic PII text."""
import json, sys

def reply(i, result):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": i, "result": result}) + "\n")
    sys.stdout.flush()

for line in sys.stdin:
    m = json.loads(line)
    meth, i = m.get("method"), m.get("id")
    if meth == "initialize":
        reply(i, {"protocolVersion": m["params"].get("protocolVersion", "2025-06-18"),
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "fakecrm", "version": "0.0.1"}})
    elif meth == "tools/list":
        reply(i, {"tools": [{"name": "lookup_customer", "description": "Look up a customer record by id",
                             "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}}]})
    elif meth == "tools/call":
        reply(i, {"content": [{"type": "text", "text": "Customer MCP-SENTINEL-55: email mcp.sentinel@fakecrm.test, PAN ABCPE1234F"}]})
    elif i is not None:
        reply(i, {})
