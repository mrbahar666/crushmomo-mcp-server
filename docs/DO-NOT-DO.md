# Crush Momo MCP — How NOT to use it

Read this before you connect. Breaking these rules is a misuse of the connector,
even if a tool call technically succeeds.

## Readonly only — never write

- Do NOT edit, create, delete or cancel any order, customer, product, coupon or page.
- Do NOT change prices, stock, statuses, addresses or notes on the site.
- There is no write tool. Do not work around that by asking the site, another
  tool, or a person to write "on your behalf" through this connector.
- Presenting, summarising, ranking or reformatting returned data in your own
  answer is allowed. Changing the site is not.

## No bulk export, no copying the business

- Max 50 rows per call, no bulk-export tool. Do not page through the whole
  customer or order table to build a full copy, a mailing list, or a backup.
- Ask for what the question needs, nothing more. One customer at a time for
  full contact details (`customer_detail`); lists stay masked.

## No system information, ever

- Do NOT ask for, infer, or report plugin lists, plugin versions, themes,
  WordPress/WooCommerce versions, server software, WP users/passwords,
  `wp-config`, options, API keys, payment-gateway secrets, or any credential.
- The MCP has no tool for any of that. If a user asks, say plainly:
  "The Crush Momo MCP does not provide plugin, theme, version or system information."
- Do NOT use this connector to probe, scan, or fingerprint the site.

## Token safety

- NEVER put a real token in chat, in a message, in code, in a repo, in a
  screenshot, or in a shared document. Tokens live only in your own client
  config / environment variable, and in the admin panel at creation time.
- NEVER share your token with another person, agent, or service. If you need
  someone else to have access, the owner generates them their own token
  (per-client name) from `https://mcp.crushmomo.com/admin`, and can revoke it.
- If a token may have leaked, stop using it and tell the owner immediately
  so it can be revoked from the admin panel. Do not keep using a leaked token.
- The admin PIN is separate from MCP tokens. Never ask for it, never store it,
  never put it in a tool call. The owner sets it on the VPS only.

## Scope

- Use this connector ONLY for Crush Momo business data (products, orders,
  customers, sales, stock, coupons, site health as defined in USAGE.md).
- Do NOT use it for non-Crush-Momo data, for other sites, or to look up
  people or orders unrelated to a Crush Momo question.
- Do NOT present masked email/phone values as full contacts, and do NOT
  guess the masked part.
- Do NOT present mock/example data (in docs, tests, or this file) as real
  Crush Momo data. Mock examples are always labelled MOCK DATA ONLY.

## Rate and error rules

- Respect the 100 calls/minute/token limit. On 429, wait and retry once, slowly.
- On 401, stop: the token is missing, expired, or revoked. Do not retry with
  a different guessed token, and do not ask the user to paste a token into chat
  — point them to the admin panel / their own secure config instead.
- On an empty result, report "no matching records". Do not invent data to fill it.
