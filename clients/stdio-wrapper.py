#!/usr/bin/env python3
"""Stdio wrapper for local-only MCP clients (no HTTP transport).

The client talks stdio JSON-RPC to this script; the script forwards each
request over HTTPS to https://mcp.crushmomo.com/mcp with the Bearer token
from the CRUSHMOMO_MCP_TOKEN environment variable (never hardcode it here).

Usage in a stdio-only client config:
  "command": "python3", "args": ["/path/to/stdio-wrapper.py"],
  "env": {"CRUSHMOMO_MCP_TOKEN": "PASTE_TOKEN_HERE_IN_YOUR_OWN_CONFIG_ONLY"}
"""
import json, os, sys, urllib.request
URL = os.environ.get("CRUSHMOMO_MCP_URL", "https://mcp.crushmomo.com/mcp")
TOKEN = os.environ.get("CRUSHMOMO_MCP_TOKEN", "")
def main():
    if not TOKEN:
        print("CRUSHMOMO_MCP_TOKEN is not set", file=sys.stderr)
        return 1
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = urllib.request.Request(URL, data=line.encode(),
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                     "Authorization": "Bearer " + TOKEN})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                sys.stdout.write(r.read().decode() + "\n"); sys.stdout.flush()
        except Exception as e:
            # MCP notifications have no id and need no response; still answer JSON-RPC errors plainly.
            try:
                obj = json.loads(line)
                if obj.get("id") is not None:
                    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": obj["id"], "error": {"code": -32000, "message": str(e)}}) + "\n"); sys.stdout.flush()
            except Exception:
                pass
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
