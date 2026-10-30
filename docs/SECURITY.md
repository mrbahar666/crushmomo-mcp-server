# Crush Momo MCP — Security

## Threat model in one paragraph

Anyone on the internet can reach `https://mcp.crushmomo.com/mcp`, but without
a valid token they get 401 and no tool list, no data, and no system info.
The token is the only key. The code is public; the data and the keys are not.

## Layers

1. **Network:** HTTPS only, separate subdomain, main crushmomo.com untouched.
   The MCP service listens on localhost only (127.0.0.1) on the VPS and is
   reached through the OpenLiteSpeed reverse proxy. No WP plugin is installed.
2. **Admin:** `https://mcp.crushmomo.com/admin` needs the owner's PIN/pass.
   The PIN is stored as a PBKDF2 hash only. Sessions last 2 hours.
   5 failed logins from one IP lock that IP out for 15 minutes.
   There is NO web endpoint to set the first PIN — it is set with
   `scripts/set-admin-pin.py` on the VPS only, so nobody can claim the admin
   panel from the web before the owner does.
3. **Tokens:** Per-client, shown once at creation, stored as SHA-256 hashes.
   Expiry is set at creation (default 365 days, owner-chosen). Any token can be
   revoked from the admin panel in one click. OAuth tokens from the ChatGPT
   flow are shorter: access 1 hour, refresh 30 days.
4. **Readonly, three ways:** (a) the code has no write/file/plugin/theme/version
   tool at all — the allowlist is the whole tool list in `docs/USAGE.md`;
   (b) the production DB account is SELECT-only; (c) the server never calls
   a WordPress write API. An agent can transform data in its answer; it cannot
   write back to the site through this server.
5. **Query safety:** Tool arguments are validated (integers clamped, dates
   matched to `YYYY-MM-DD`, statuses checked against a fixed list, search
   strings length-limited and escaped). The agent never supplies SQL.
   No tool reads `wp-config`, options, users, plugins, themes, or files.
6. **Logs:** Every MCP call is logged (token name, tool, time, row count, IP,
   success/fail). Log parameters are masked: email/phone/token/PIN values are
   never stored in full. Logs are visible only in the admin panel.
7. **Repo safety:** This public repo contains no secrets, no passwords, no
   tokens, no DB credentials, no customer data, and no real `.env`.
   Before every push, run `scripts/secret-scan.sh` (grep for password/token/
   secret/key patterns and for `.env` files). Deployment secrets live only
   on the VPS in mode-600 files (see the private deploy repo).
8. **Rate limiting:** 100 MCP calls/minute/token, 429 beyond that.

## What to do if a token leaks

Revoke it from the admin panel immediately, generate a replacement token for
that client, and check the admin call log for calls made with the old token.
Do not keep using a leaked token "until later".
