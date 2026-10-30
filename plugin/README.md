# Install from the GitHub URL — Dots / local agents

This is the flow the owner asked for: give the agent the public repo URL,
tell it to install, then give it a token. It works for a LOCAL agent
(Dots with its computer online, Claude Code, Codex, Muse) — it does NOT
work by telling normal ChatGPT chat to self-install, because ChatGPT chat
cannot change its own Settings or add a connector from a chat prompt.

Repo (public, no secrets in it):
`https://github.com/mrbahar666/crushmomo-mcp-server`

## Dots / local agent install (token-only, no PIN)

1. Clone the repo on the agent's computer:
   `git clone https://github.com/mrbahar666/crushmomo-mcp-server`
2. Generate one token in `https://mcp.crushmomo.com/admin`, named for that
   agent (for example `ChatGPT Dots`). Copy it once into the agent's own
   config / environment only — NEVER into chat, and never into the repo.
   Example env var: `CRUSHMOMO_MCP_TOKEN`
3. Run the stdio wrapper from this repo, or use Streamable HTTP directly:
   - Stdio: `python3 clients/stdio-wrapper.py` with
     `CRUSHMOMO_MCP_TOKEN` set in the environment.
   - HTTP: URL `https://mcp.crushmomo.com/mcp`, header
     `Authorization: Bearer <your token>`.
4. Test: `ping`, then `products_list` with `limit: 5`.
   If `ping` returns 401, the token is missing, expired, or revoked.

## ChatGPT web (Plugins UI — different path, still token-only after v1.0.2)

Normal ChatGPT web cannot install from a GitHub URL in chat. Use either:
- Plugins → New Plugin → upload `plugin/crushmomo-mcp.zip` from this repo,
  then connect; OR
- Plugins → Add custom MCP server → URL `https://mcp.crushmomo.com/mcp`,
  Authentication OAuth. On the approve page, enter the admin PIN **or**
  an admin token from /admin — either one alone is enough (v1.0.2).
  Revoking that admin token also revokes the OAuth tokens issued from it.
