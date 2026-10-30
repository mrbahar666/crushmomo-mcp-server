# crushmomo-mcp-server

Readonly MCP server for the live Crush Momo WordPress/WooCommerce site
(crushmomo.com), so an AI agent can read live business data — sales, orders,
customers, products, stock, coupons, site health — without ever writing to the site.

- MCP URL: `https://mcp.crushmomo.com/mcp`
- Admin (tokens + call log): `https://mcp.crushmomo.com/admin`
- Connector name in clients: `crushmomo-mcp`
- Currency: BDT · Timezone: Asia/Dhaka · Max 50 rows per call · Readonly only

## Start here

- **How to use (every tool, params, returns, field meanings, mock examples):**
  [`docs/USAGE.md`](docs/USAGE.md)
- **How NOT to use (readonly rules, no bulk export, no system info, token safety):**
  [`docs/DO-NOT-DO.md`](docs/DO-NOT-DO.md)
- **How to install / connect (Muse, Claude Code, Codex, ChatGPT OAuth/PIN,
  Groq agent example, any standard MCP client, stdio wrapper):**
  [`docs/INSTALL.md`](docs/INSTALL.md)
- **Security:** [`docs/SECURITY.md`](docs/SECURITY.md)
- **AI skill (short version for agents):** [`SKILL.md`](SKILL.md)

## Server

`server/server.py` — Python 3.12, **stdlib only, zero pip dependencies**.
It speaks Streamable HTTP MCP (`initialize`, `tools/list`, `tools/call`, `ping`),
plus an OAuth/PIN layer for ChatGPT (protected-resource + authorization-server
metadata, authorize + token endpoints). The service listens on localhost only
and is reached through the OpenLiteSpeed reverse proxy on the VPS.

Production data comes from a SELECT-only database account whose credentials
live only on the VPS in a mode-600 file. **This repo contains no secrets, no
passwords, no tokens, no DB credentials, no customer data, and no real `.env`.**
Run `scripts/secret-scan.sh` before every push.

Mock mode (tests/docs only, never production):
```bash
MCP_MOCK=1 MCP_STATE_DIR=/tmp/cmcp-test-state python3 server/server.py
MCP_MOCK=1 MCP_STATE_DIR=/tmp/cmcp-test-state python3 tests/test_mock.py
```

## Tools (14, allowlist only)

`ping`, `sales_summary`, `orders_search`, `order_detail`, `customers_search`,
`customer_detail`, `customer_orders`, `repeat_customers`, `products_list`,
`product_detail`, `categories_list`, `stock_list`, `coupons_list`, `site_health`.

There is deliberately **no** plugin tool, theme tool, version tool, WP user tool,
`wp-config`/options tool, file-read tool, or any write tool. See `docs/USAGE.md`
for the exact parameters and returns of each tool — the docs are verified
against the tool definitions in `server/server.py`.
