#!/usr/bin/env python3
"""Mock tests for crushmomo-mcp. Run: MCP_MOCK=1 MCP_STATE_DIR=/tmp/cmcp-test-state python3 tests/test_mock.py
No live DB, no real customer data, no network."""
import os, sys
os.environ["MCP_MOCK"] = "1"
os.environ.setdefault("MCP_STATE_DIR", "/tmp/cmcp-test-state")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
import server

def main():
    names = [t[0] for t in server.TOOLS]
    assert names == list(server.TOOL_FUNCS), "tool list != tool functions"
    assert "plugins" not in str(names) and "theme" not in str(names), "forbidden tool present"
    for name, fn in server.TOOL_FUNCS.items():
        args = {}
        if name == "order_detail": args = {"order_id": 5001}
        if name in ("customer_detail", "customer_orders"): args = {"customer_id": 101}
        if name == "product_detail": args = {"product_id": 201}
        fn(args)
    assert server.mask_email("a@example.test") == "a***@example.test"
    assert server.mask_phone("01712345678").endswith("78")
    assert server.clamp_int(999, 20, 1, 50) == 50, "limit clamp failed"
    assert server.valid_date("2026-10-30") is not None
    assert server.valid_date("30-10-2026") is None
    assert server.esc("o'brien") == "o''brien"
    print(f"OK: {len(names)} tools, masking, validation, limits")

if __name__ == "__main__":
    main()
