#!/usr/bin/env python3
"""Set (or reset) the MCP admin PIN on the VPS only. Run on the VPS, never in chat.
Usage: MCP_STATE_DIR=/var/lib/crushmomo-mcp python3 scripts/set-admin-pin.py
Prompts for the PIN twice (getpass, never echoed, never printed, never logged).
The PIN is stored only as a PBKDF2 hash in state.sqlite3. There is no web setup
endpoint on purpose: if anyone could set the first PIN from the web, they could
take over the admin panel before the owner does."""
import getpass, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
import server
def main():
    db = server.state_db()
    pin = getpass.getpass("New admin PIN: ")
    pin2 = getpass.getpass("Repeat admin PIN: ")
    if not pin or pin != pin2:
        print("PINs do not match or are empty. Nothing changed.")
        return 1
    with server._lock:
        db.execute("INSERT OR REPLACE INTO admin (key, value) VALUES ('pin_hash', ?)", (server.hash_pin(pin),))
        db.commit()
    print("Admin PIN saved (hash only). Restart the service if it was already running.")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
