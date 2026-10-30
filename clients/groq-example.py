#!/usr/bin/env python3
"""Groq agent example (MOCK-friendly, no Groq call by default).

Groq's chat UI has no MCP button, so this is how Groq works here: an agent
program uses a Groq model AND an MCP client. This script shows only the MCP
half (ping + sales_summary) so the pattern is clear without spending Groq
tokens. Set CRUSHMOMO_MCP_TOKEN in your own environment, never in this file.
Run: CRUSHMOMO_MCP_TOKEN=... python3 clients/groq-example.py
Then pass `result` to your Groq model call as context and let it answer.
"""
import json, os, urllib.request
URL = "https://mcp.crushmomo.com/mcp"
TOKEN = os.environ.get("CRUSHMOMO_MCP_TOKEN", "")
def call(method, params=None, rid=1):
    body = json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json",
        "Accept": "application/json, text/event-stream", "Authorization": "Bearer " + TOKEN})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())
if __name__ == "__main__":
    print(json.dumps(call("tools/call", {"name": "ping", "arguments": {}}), indent=2))
    print(json.dumps(call("tools/call", {"name": "sales_summary", "arguments": {"period": "today"}}, rid=2), indent=2))
