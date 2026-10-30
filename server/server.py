#!/usr/bin/env python3
"""Crush Momo readonly MCP server — Python 3.12 stdlib only, zero pip deps.

Public repo code. No secrets live here. Configuration comes only from
environment variables / files on the server (see README.md).
Readonly by construction:
  * there is no write tool, no file tool, no plugin/theme/version tool;
  * every tool maps to a fixed, validated SELECT query (or mock data);
  * the DB account used in production must be SELECT-only.
Data: live WooCommerce (HPOS) tables, currency BDT, timezone Asia/Dhaka (+06:00).
"""
import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

VERSION = "1.0.0"
SERVER_NAME = "crushmomo-mcp"
PROTOCOL_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]
DHAKA = timezone(timedelta(hours=6))
MAX_ROWS = 50
MAX_BODY = 1024 * 1024

# ---------------------------------------------------------------- config
def env(name, default=""):
    return os.environ.get(name, default)

HOST = env("MCP_HOST", "127.0.0.1")
PORT = int(env("MCP_PORT", "8765"))
DB_NAME = env("MCP_DB_NAME", "")
DB_PREFIX = env("MCP_DB_PREFIX", "crushmomo")
MYSQL_CNF = env("MCP_MYSQL_CNF", "")
STATE_DIR = env("MCP_STATE_DIR", "/var/lib/crushmomo-mcp")
MOCK = env("MCP_MOCK", "0") == "1"
BASE_URL = env("MCP_BASE_URL", "https://mcp.crushmomo.com").rstrip("/")

# ---------------------------------------------------------------- helpers
def sha256_hex(s):
    return hashlib.sha256(s.encode()).hexdigest()

def hash_pin(pin, salt=None):
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 200000)
    return salt.hex() + ":" + dk.hex()

def check_pin(pin, stored):
    try:
        salt_hex, dk_hex = stored.split(":", 1)
        dk = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt_hex), 200000)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False

def mask_email(e):
    if not e or "@" not in str(e):
        return None
    local, dom = str(e).split("@", 1)
    return (local[:1] + "***@" + dom) if local else ("***@" + dom)

def mask_phone(p):
    if not p:
        return None
    digits = re.sub(r"\D", "", str(p))
    if len(digits) <= 2:
        return "***"
    return "***" + digits[-2:]

def mask_value(v):
    if v is None:
        return None
    s = str(v)
    if "@" in s and re.search(r"\S+@\S+\.\S+", s):
        return mask_email(s)
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 9 and digits.startswith(("01", "8801")):
        return mask_phone(s)
    return s

def mask_params(params):
    out = {}
    for k, v in (params or {}).items():
        kl = str(k).lower()
        if "phone" in kl or "email" in kl or "token" in kl or "pin" in kl or "password" in kl:
            out[k] = "***" if v is not None else None
        elif isinstance(v, str):
            out[k] = mask_value(v)
        else:
            out[k] = v
    return out

def clamp_int(v, default, lo, hi):
    try:
        return max(lo, min(hi, int(v)))
    except Exception:
        return default

def valid_date(s):
    if not isinstance(s, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def esc(s):
    """Escape a validated search string for a MySQL string literal. Only used
    after length/character checks in the tool layer; never for identifiers."""
    s = str(s)[:100]
    s = "".join(ch for ch in s if ch >= " " and ch != "\x7f")
    return s.replace("\\", "\\\\").replace("'", "''")

def like_esc(s):
    return esc(s).replace("%", "\\%").replace("_", "\\_")

def dhaka_today():
    return (datetime.now(timezone.utc) + timedelta(hours=6)).date()

def period_range(period, start_date=None, end_date=None):
    today = dhaka_today()
    if period == "yesterday":
        s = e = today - timedelta(days=1)
    elif period == "this_month":
        s = today.replace(day=1)
        e = today
    elif period == "last_month":
        first = today.replace(day=1)
        e = first - timedelta(days=1)
        s = e.replace(day=1)
    elif period == "date_range":
        s = valid_date(start_date)
        e = valid_date(end_date)
        if not s or not e or e < s or (e - s).days > 366:
            raise ValueError("date_range needs start_date/end_date YYYY-MM-DD, max 366 days, end >= start")
    else:  # today (default)
        s = e = today
    # Dhaka day [s 00:00, e+1 00:00) == GMT [s-6h, e+1-6h)
    gmt_start = datetime(s.year, s.month, s.day) - timedelta(hours=6)
    gmt_end = datetime(e.year, e.month, e.day) + timedelta(days=1) - timedelta(hours=6)
    return s, e, gmt_start.strftime("%Y-%m-%d %H:%M:%S"), gmt_end.strftime("%Y-%m-%d %H:%M:%S")

# ---------------------------------------------------------------- state (sqlite)
_lock = threading.Lock()
_db = None

def state_db():
    global _db
    if _db is None:
        os.makedirs(STATE_DIR, exist_ok=True)
        _db = sqlite3.connect(os.path.join(STATE_DIR, "state.sqlite3"), check_same_thread=False)
        _db.execute("""CREATE TABLE IF NOT EXISTS tokens
            (id INTEGER PRIMARY KEY, name TEXT, token_hash TEXT UNIQUE,
             created_at TEXT, expires_at TEXT, last_used_at TEXT, revoked INTEGER DEFAULT 0)""")
        _db.execute("""CREATE TABLE IF NOT EXISTS oauth_clients
            (client_id TEXT PRIMARY KEY, redirect_uris TEXT, created_at TEXT)""")
        _db.execute("""CREATE TABLE IF NOT EXISTS oauth_codes
            (code_hash TEXT PRIMARY KEY, client_id TEXT, redirect_uri TEXT,
             challenge TEXT, challenge_method TEXT, expires_at TEXT)""")
        _db.execute("""CREATE TABLE IF NOT EXISTS oauth_tokens
            (token_hash TEXT PRIMARY KEY, kind TEXT, client_id TEXT,
             expires_at TEXT, revoked INTEGER DEFAULT 0)""")
        _db.execute("""CREATE TABLE IF NOT EXISTS admin
            (key TEXT PRIMARY KEY, value TEXT)""")
        _db.execute("""CREATE TABLE IF NOT EXISTS sessions
            (session_hash TEXT PRIMARY KEY, expires_at TEXT)""")
        _db.execute("""CREATE TABLE IF NOT EXISTS failed_logins
            (ip TEXT PRIMARY KEY, count INTEGER, last_at REAL, locked_until REAL)""")
        _db.execute("""CREATE TABLE IF NOT EXISTS call_log
            (id INTEGER PRIMARY KEY, ts TEXT, token_name TEXT, tool TEXT,
             params TEXT, row_count INTEGER, ip TEXT, ok INTEGER, error TEXT)""")
        _db.commit()
    return _db

def log_call(token_name, tool, params, row_count, ip, ok, error=""):
    try:
        with _lock:
            db = state_db()
            db.execute("INSERT INTO call_log (ts, token_name, tool, params, row_count, ip, ok, error) VALUES (?,?,?,?,?,?,?,?)",
                       (datetime.now(timezone.utc).isoformat(), token_name, tool,
                        json.dumps(mask_params(params)), int(row_count), ip, 1 if ok else 0, (error or "")[:200]))
            db.commit()
    except Exception:
        pass

def verify_bearer(token):
    """Return (kind, name) or None. kind: 'token' | 'oauth'."""
    if not token:
        return None
    h = sha256_hex(token)
    with _lock:
        db = state_db()
        row = db.execute("SELECT name, expires_at, revoked FROM tokens WHERE token_hash=?", (h,)).fetchone()
        if row:
            if row[2]:
                return None
            if row[1] and datetime.now(timezone.utc).isoformat() > row[1]:
                return None
            db.execute("UPDATE tokens SET last_used_at=? WHERE token_hash=?",
                       (datetime.now(timezone.utc).isoformat(), h))
            db.commit()
            return ("token", row[0])
        row = db.execute("SELECT kind, client_id, expires_at, revoked FROM oauth_tokens WHERE token_hash=?", (h,)).fetchone()
        if row:
            if row[3]:
                return None
            if row[2] and datetime.now(timezone.utc).isoformat() > row[2]:
                return None
            return ("oauth", "oauth:" + row[1])
    return None

# rate limiting (in-memory, per token/IP)
_rate = {}
def rate_ok(key, limit=100, window=60):
    now = time.time()
    lst = [t for t in _rate.get(key, []) if now - t < window]
    if len(lst) >= limit:
        _rate[key] = lst
        return False
    lst.append(now)
    _rate[key] = lst
    return True

# ---------------------------------------------------------------- DB layer
def db_query(sql):
    """Run one fixed SELECT via the mysql CLI. Returns list of dicts.
    Raises RuntimeError on any DB error. Never called with user SQL."""
    if MOCK:
        raise RuntimeError("mock mode: db_query must not be used")
    if not MYSQL_CNF or not DB_NAME:
        raise RuntimeError("database not configured on this server")
    p = subprocess.run(["mysql", "--defaults-file=" + MYSQL_CNF, "--batch", "--skip-column-names", "-e", sql],
                       capture_output=True, text=True, timeout=20)
    if p.returncode != 0:
        raise RuntimeError("database query failed")
    rows = []
    lines = p.stdout.splitlines()
    # mysql --batch without headers gives no column names; callers use positional
    # parsing via a header query wrapper instead — see db_query_named below.
    return lines

def db_named(sql, columns):
    """Run SELECT and return list of dicts keyed by `columns` (same order as sql)."""
    if MOCK:
        return []
    lines = db_query(sql)
    out = []
    for line in lines:
        parts = line.split("\t")
        row = {}
        for i, col in enumerate(columns):
            v = parts[i] if i < len(parts) else None
            # mysql --batch prints SQL NULL as the literal string "NULL", not \N.
            if v in (None, "\\N", "NULL", ""):
                v = None
            row[col] = v
        out.append(row)
    return out

def num(v):
    try:
        f = float(v)
        return int(f) if f == int(f) else f
    except Exception:
        return v

# ---------------------------------------------------------------- mock data (tests + docs only)
MOCK_CUSTOMER = {"customer_id": 101, "first_name": "Ayesha", "last_name": "Rahman",
                 "username": "ayesha_r", "email": "ayesha@example.test", "city": "Dhaka",
                 "country": "BD", "date_registered": "2025-01-10 00:00:00"}
MOCK_ORDER = {"order_id": 5001, "status": "wc-completed", "currency": "BDT",
              "total_amount": 1250, "tax_amount": 0, "customer_id": 101,
              "billing_email": "ayesha@example.test", "payment_method": "cod",
              "date_created_dhaka": "2026-10-28 19:30:00"}
MOCK_PRODUCT = {"product_id": 201, "name": "Chicken Momo (Frozen, 20 pc)",
                "sku": "CM-CH-20", "price_min": 450, "price_max": 450,
                "stock_quantity": 42, "stock_status": "instock", "total_sales": 310,
                "categories": ["Frozen Packs"]}

# ---------------------------------------------------------------- tools
ORDER_STATUSES = ["wc-pending", "wc-processing", "wc-on-hold", "wc-completed",
                  "wc-cancelled", "wc-refunded", "wc-failed", "wc-checkout-draft", "trash"]

def tool_sales_summary(a):
    period = a.get("period", "today")
    if period not in ("today", "yesterday", "this_month", "last_month", "date_range"):
        raise ValueError("period must be today|yesterday|this_month|last_month|date_range")
    s, e, gs, ge = period_range(period, a.get("start_date"), a.get("end_date"))
    if MOCK:
        return {"period": period, "start_date": str(s), "end_date": str(e), "currency": "BDT",
                "timezone": "Asia/Dhaka", "by_status": [{"status": "wc-completed", "order_count": 12, "total_amount": 14800, "average_amount": 1233.33}],
                "total_orders": 12, "total_amount": 14800, "note": "MOCK DATA ONLY — not real sales."}
    o = f"{DB_PREFIX}wc_orders"
    rows = db_named(
        f"SELECT status, COUNT(*), COALESCE(SUM(total_amount),0), COALESCE(AVG(total_amount),0) FROM {DB_NAME}.{o} "
        f"WHERE date_created_gmt >= '{gs}' AND date_created_gmt < '{ge}' GROUP BY status ORDER BY status;",
        ["status", "order_count", "total_amount", "average_amount"])
    by = [{"status": r["status"], "order_count": int(r["order_count"]),
           "total_amount": num(r["total_amount"]), "average_amount": round(float(r["average_amount"] or 0), 2)} for r in rows]
    days = db_named(
        f"SELECT DATE(DATE_ADD(date_created_gmt, INTERVAL 6 HOUR)), COUNT(*), COALESCE(SUM(total_amount),0) FROM {DB_NAME}.{o} "
        f"WHERE date_created_gmt >= '{gs}' AND date_created_gmt < '{ge}' GROUP BY 1 ORDER BY 1;",
        ["date", "order_count", "total_amount"])
    return {"period": period, "start_date": str(s), "end_date": str(e), "currency": "BDT",
            "timezone": "Asia/Dhaka",
            "by_status": by,
            "by_day": [{"date": d["date"], "order_count": int(d["order_count"]), "total_amount": num(d["total_amount"])} for d in days],
            "total_orders": sum(b["order_count"] for b in by),
            "total_amount": round(sum(float(b["total_amount"]) for b in by), 2)}

def _order_items(order_id):
    if MOCK:
        return [{"order_item_id": 9001, "product_id": 201, "product_name": MOCK_PRODUCT["name"],
                 "quantity": 2, "net_revenue": 900, "gross_revenue": 900}]
    o, p, pm = f"{DB_PREFIX}wc_order_product_lookup", f"{DB_PREFIX}posts", f"{DB_PREFIX}wc_product_meta_lookup"
    rows = db_named(
        f"SELECT l.order_item_id, l.product_id, l.variation_id, l.product_qty, l.product_net_revenue, l.product_gross_revenue, "
        f"p.post_title, m.sku FROM {DB_NAME}.{o} l LEFT JOIN {DB_NAME}.{p} p ON p.ID=l.product_id "
        f"LEFT JOIN {DB_NAME}.{pm} m ON m.product_id=l.product_id WHERE l.order_id={order_id} ORDER BY l.order_item_id;",
        ["order_item_id", "product_id", "variation_id", "product_qty", "product_net_revenue", "product_gross_revenue", "product_name", "sku"])
    return [{"order_item_id": int(r["order_item_id"]), "product_id": int(r["product_id"]),
             "variation_id": int(r["variation_id"] or 0), "quantity": int(r["product_qty"]),
             "net_revenue": num(r["product_net_revenue"]), "gross_revenue": num(r["product_gross_revenue"]),
             "product_name": r["product_name"], "sku": r["sku"]} for r in rows]

def _billing(order_id):
    if MOCK:
        return {"first_name": "Ayesha", "last_name": "Rahman", "city": "Dhaka", "country": "BD", "email": MOCK_CUSTOMER["email"], "phone": "01XXXXXXXX1"}
    a = f"{DB_PREFIX}wc_order_addresses"
    rows = db_named(
        f"SELECT first_name, last_name, company, address_1, address_2, city, state, postcode, country, email, phone "
        f"FROM {DB_NAME}.{a} WHERE order_id={order_id} AND address_type='billing' LIMIT 1;",
        ["first_name", "last_name", "company", "address_1", "address_2", "city", "state", "postcode", "country", "email", "phone"])
    return rows[0] if rows else {}

def tool_orders_search(a):
    limit = clamp_int(a.get("limit", 20), 20, 1, MAX_ROWS)
    offset = clamp_int(a.get("offset", 0), 0, 0, 100000)
    status = a.get("status")
    q = a.get("query")
    if MOCK:
        return {"orders": [dict(MOCK_ORDER, billing=_billing(5001), items=[])], "limit": limit, "offset": offset, "note": "MOCK DATA ONLY."}
    o = f"{DB_PREFIX}wc_orders"
    where = ["1=1"]
    if status:
        if status not in ORDER_STATUSES:
            raise ValueError("unknown order status")
        where.append(f"status='{status}'")
    if q:
        qs = like_esc(q)
        if re.fullmatch(r"\d+", str(q)):
            where.append(f"(id={int(q)} OR customer_id={int(q)})")
        else:
            where.append(f"(billing_email LIKE '%{qs}%' ESCAPE '\\\\')")
    rows = db_named(
        f"SELECT id, status, currency, total_amount, tax_amount, customer_id, billing_email, payment_method, "
        f"DATE_ADD(date_created_gmt, INTERVAL 6 HOUR) FROM {DB_NAME}.{o} WHERE {' AND '.join(where)} "
        f"ORDER BY id DESC LIMIT {limit} OFFSET {offset};",
        ["order_id", "status", "currency", "total_amount", "tax_amount", "customer_id", "billing_email", "payment_method", "date_created_dhaka"])
    return {"orders": [{**r, "order_id": int(r["order_id"]), "customer_id": int(r["customer_id"] or 0),
                        "total_amount": num(r["total_amount"]), "tax_amount": num(r["tax_amount"]),
                        "billing_email": mask_email(r["billing_email"])} for r in rows],
            "limit": limit, "offset": offset}

def tool_order_detail(a):
    oid = clamp_int(a.get("order_id"), 0, 1, 10**12)
    if not oid:
        raise ValueError("order_id (integer) is required")
    if MOCK:
        return {**MOCK_ORDER, "billing": _billing(oid), "items": _order_items(oid), "note": "MOCK DATA ONLY."}
    o = f"{DB_PREFIX}wc_orders"
    rows = db_named(
        f"SELECT id, status, currency, total_amount, tax_amount, customer_id, billing_email, payment_method, payment_method_title, "
        f"DATE_ADD(date_created_gmt, INTERVAL 6 HOUR), DATE_ADD(date_updated_gmt, INTERVAL 6 HOUR), customer_note "
        f"FROM {DB_NAME}.{o} WHERE id={oid} LIMIT 1;",
        ["order_id", "status", "currency", "total_amount", "tax_amount", "customer_id", "billing_email", "payment_method",
         "payment_method_title", "date_created_dhaka", "date_updated_dhaka", "customer_note"])
    if not rows:
        raise ValueError("order not found")
    r = rows[0]
    return {"order_id": int(r["order_id"]), "status": r["status"], "currency": r["currency"],
            "total_amount": num(r["total_amount"]), "tax_amount": num(r["tax_amount"]),
            "customer_id": int(r["customer_id"] or 0), "billing_email": r["billing_email"],
            "payment_method": r["payment_method"], "payment_method_title": r["payment_method_title"],
            "date_created_dhaka": r["date_created_dhaka"], "date_updated_dhaka": r["date_updated_dhaka"],
            "customer_note": r["customer_note"], "billing": _billing(oid), "items": _order_items(oid)}

def _customer_totals(cid):
    if MOCK:
        return {"order_count": 4, "total_amount": 5200}
    o = f"{DB_PREFIX}wc_orders"
    rows = db_named(
        f"SELECT COUNT(*), COALESCE(SUM(total_amount),0) FROM {DB_NAME}.{o} "
        f"WHERE customer_id={cid} AND status IN ('wc-completed','wc-processing');",
        ["order_count", "total_amount"])
    return {"order_count": int(rows[0]["order_count"]), "total_amount": num(rows[0]["total_amount"])}

def tool_customers_search(a):
    limit = clamp_int(a.get("limit", 20), 20, 1, MAX_ROWS)
    q = a.get("query", "")
    if MOCK:
        return {"customers": [{**{k: v for k, v in MOCK_CUSTOMER.items() if k != "email"}, "email": mask_email(MOCK_CUSTOMER["email"]), "phone": mask_phone("01700000001"), **_customer_totals(101)}], "limit": limit, "note": "MOCK DATA ONLY."}
    c = f"{DB_PREFIX}wc_customer_lookup"
    where = "1=1"
    if q:
        qs = like_esc(q)
        where = (f"(first_name LIKE '%{qs}%' ESCAPE '\\\\' OR last_name LIKE '%{qs}%' ESCAPE '\\\\' "
                 f"OR username LIKE '%{qs}%' ESCAPE '\\\\' OR email LIKE '%{qs}%' ESCAPE '\\\\' "
                 f"OR billing_phone LIKE '%{qs}%' ESCAPE '\\\\' OR shipping_phone LIKE '%{qs}%' ESCAPE '\\\\')")
    rows = db_named(
        f"SELECT customer_id, user_id, username, first_name, last_name, email, city, state, country, billing_phone, date_registered "
        f"FROM {DB_NAME}.{c} WHERE {where} ORDER BY customer_id DESC LIMIT {limit};",
        ["customer_id", "user_id", "username", "first_name", "last_name", "email", "city", "state", "country", "billing_phone", "date_registered"])
    out = []
    for r in rows:
        cid = int(r["customer_id"])
        out.append({"customer_id": cid, "user_id": int(r["user_id"] or 0), "username": r["username"],
                    "first_name": r["first_name"], "last_name": r["last_name"],
                    "email": mask_email(r["email"]), "phone": mask_phone(r["billing_phone"]),
                    "city": r["city"], "state": r["state"], "country": r["country"],
                    "date_registered": r["date_registered"], **_customer_totals(cid)})
    return {"customers": out, "limit": limit}

def tool_customer_detail(a):
    cid = clamp_int(a.get("customer_id"), 0, 1, 10**12)
    if not cid:
        raise ValueError("customer_id (integer) is required")
    if MOCK:
        return {**MOCK_CUSTOMER, "phone": "01XXXXXXXX1", **_customer_totals(cid), "recent_orders": [MOCK_ORDER], "note": "MOCK DATA ONLY."}
    c = f"{DB_PREFIX}wc_customer_lookup"
    rows = db_named(
        f"SELECT customer_id, user_id, username, first_name, last_name, email, city, state, country, postcode, billing_phone, shipping_phone, date_registered, date_last_active "
        f"FROM {DB_NAME}.{c} WHERE customer_id={cid} LIMIT 1;",
        ["customer_id", "user_id", "username", "first_name", "last_name", "email", "city", "state", "country", "postcode", "billing_phone", "shipping_phone", "date_registered", "date_last_active"])
    if not rows:
        raise ValueError("customer not found")
    r = rows[0]
    # recent orders for this customer (direct; full email kept only in detail view)
    o = f"{DB_PREFIX}wc_orders"
    orows = db_named(
        f"SELECT id, status, currency, total_amount, payment_method, DATE_ADD(date_created_gmt, INTERVAL 6 HOUR) "
        f"FROM {DB_NAME}.{o} WHERE customer_id={cid} ORDER BY id DESC LIMIT 10;",
        ["order_id", "status", "currency", "total_amount", "payment_method", "date_created_dhaka"])
    return {"customer_id": int(r["customer_id"]), "user_id": int(r["user_id"] or 0), "username": r["username"],
            "first_name": r["first_name"], "last_name": r["last_name"], "email": r["email"],
            "phone": r["billing_phone"] or r["shipping_phone"], "city": r["city"], "state": r["state"],
            "country": r["country"], "postcode": r["postcode"], "date_registered": r["date_registered"],
            "date_last_active": r["date_last_active"], **_customer_totals(cid),
            "recent_orders": [{"order_id": int(x["order_id"]), "status": x["status"], "currency": x["currency"],
                               "total_amount": num(x["total_amount"]), "payment_method": x["payment_method"],
                               "date_created_dhaka": x["date_created_dhaka"]} for x in orows]}

def tool_customer_orders(a):
    cid = clamp_int(a.get("customer_id"), 0, 1, 10**12)
    limit = clamp_int(a.get("limit", 20), 20, 1, MAX_ROWS)
    if not cid:
        raise ValueError("customer_id (integer) is required")
    if MOCK:
        return {"customer_id": cid, "orders": [MOCK_ORDER], "limit": limit, "note": "MOCK DATA ONLY."}
    o = f"{DB_PREFIX}wc_orders"
    rows = db_named(
        f"SELECT id, status, currency, total_amount, tax_amount, payment_method, DATE_ADD(date_created_gmt, INTERVAL 6 HOUR) "
        f"FROM {DB_NAME}.{o} WHERE customer_id={cid} ORDER BY id DESC LIMIT {limit};",
        ["order_id", "status", "currency", "total_amount", "tax_amount", "payment_method", "date_created_dhaka"])
    return {"customer_id": cid, "orders": [{"order_id": int(r["order_id"]), "status": r["status"], "currency": r["currency"],
            "total_amount": num(r["total_amount"]), "tax_amount": num(r["tax_amount"]),
            "payment_method": r["payment_method"], "date_created_dhaka": r["date_created_dhaka"]} for r in rows], "limit": limit}

def tool_repeat_customers(a):
    min_orders = clamp_int(a.get("min_orders", 2), 2, 2, 100)
    limit = clamp_int(a.get("limit", 20), 20, 1, MAX_ROWS)
    if MOCK:
        return {"customers": [{**MOCK_CUSTOMER, "email": mask_email(MOCK_CUSTOMER["email"]), "order_count": 4, "total_amount": 5200}], "min_orders": min_orders, "note": "MOCK DATA ONLY."}
    c, o = f"{DB_PREFIX}wc_customer_lookup", f"{DB_PREFIX}wc_orders"
    rows = db_named(
        f"SELECT c.customer_id, c.first_name, c.last_name, c.email, c.city, COUNT(*) AS cnt, COALESCE(SUM(o.total_amount),0) AS tot "
        f"FROM {DB_NAME}.{o} o JOIN {DB_NAME}.{c} c ON c.customer_id=o.customer_id "
        f"WHERE o.status IN ('wc-completed','wc-processing') GROUP BY c.customer_id HAVING cnt >= {min_orders} "
        f"ORDER BY cnt DESC, tot DESC LIMIT {limit};",
        ["customer_id", "first_name", "last_name", "email", "city", "order_count", "total_amount"])
    return {"min_orders": min_orders, "customers": [{"customer_id": int(r["customer_id"]), "first_name": r["first_name"],
            "last_name": r["last_name"], "email": mask_email(r["email"]), "city": r["city"],
            "order_count": int(r["order_count"]), "total_amount": num(r["total_amount"])} for r in rows]}

def _product_categories(pid):
    if MOCK:
        return MOCK_PRODUCT["categories"]
    t, tt, tr = f"{DB_PREFIX}terms", f"{DB_PREFIX}term_taxonomy", f"{DB_PREFIX}term_relationships"
    rows = db_named(
        f"SELECT t.name FROM {DB_NAME}.{t} t JOIN {DB_NAME}.{tt} tt ON tt.term_id=t.term_id "
        f"JOIN {DB_NAME}.{tr} tr ON tr.term_taxonomy_id=tt.term_taxonomy_id "
        f"WHERE tt.taxonomy='product_cat' AND tr.object_id={pid} ORDER BY t.name;",
        ["name"])
    return [r["name"] for r in rows]

def tool_products_list(a):
    limit = clamp_int(a.get("limit", 20), 20, 1, MAX_ROWS)
    q = a.get("search", "") or ""
    in_stock = bool(a.get("in_stock_only", False))
    if MOCK:
        return {"products": [MOCK_PRODUCT], "limit": limit, "note": "MOCK DATA ONLY."}
    p, m = f"{DB_PREFIX}posts", f"{DB_PREFIX}wc_product_meta_lookup"
    where = ["p.post_type='product'", "p.post_status='publish'"]
    if q:
        where.append(f"p.post_title LIKE '%{like_esc(q)}%' ESCAPE '\\\\'")
    if in_stock:
        where.append("m.stock_status='instock'")
    rows = db_named(
        f"SELECT p.ID, REPLACE(REPLACE(REPLACE(p.post_title,CHAR(9),' '),CHAR(10),' '),CHAR(13),' '), LEFT(REPLACE(REPLACE(REPLACE(p.post_excerpt,CHAR(9),' '),CHAR(10),' '),CHAR(13),' '),300), m.sku, m.min_price, m.max_price, m.stock_quantity, m.stock_status, m.total_sales "
        f"FROM {DB_NAME}.{p} p LEFT JOIN {DB_NAME}.{m} m ON m.product_id=p.ID WHERE {' AND '.join(where)} ORDER BY p.post_title LIMIT {limit};",
        ["product_id", "name", "excerpt", "sku", "price_min", "price_max", "stock_quantity", "stock_status", "total_sales"])
    out = []
    for r in rows:
        pid = int(r["product_id"])
        out.append({"product_id": pid, "name": r["name"], "short_description": (r["excerpt"] or "")[:300],
                    "sku": r["sku"], "price_min": num(r["price_min"]), "price_max": num(r["price_max"]),
                    "stock_quantity": num(r["stock_quantity"]) if r["stock_quantity"] is not None else None,
                    "stock_status": r["stock_status"], "total_sales": int(r["total_sales"] or 0),
                    "categories": _product_categories(pid)})
    return {"products": out, "limit": limit, "currency": "BDT"}

def tool_product_detail(a):
    pid = clamp_int(a.get("product_id"), 0, 1, 10**12)
    if not pid:
        raise ValueError("product_id (integer) is required")
    if MOCK:
        return {**MOCK_PRODUCT, "short_description": "Mock product for testing and docs only.", "note": "MOCK DATA ONLY."}
    p, m = f"{DB_PREFIX}posts", f"{DB_PREFIX}wc_product_meta_lookup"
    rows = db_named(
        f"SELECT p.ID, REPLACE(REPLACE(REPLACE(p.post_title,CHAR(9),' '),CHAR(10),' '),CHAR(13),' '), LEFT(REPLACE(REPLACE(REPLACE(p.post_excerpt,CHAR(9),' '),CHAR(10),' '),CHAR(13),' '),1000), m.sku, m.min_price, m.max_price, m.stock_quantity, m.stock_status, m.total_sales, m.onsale "
        f"FROM {DB_NAME}.{p} p LEFT JOIN {DB_NAME}.{m} m ON m.product_id=p.ID WHERE p.ID={pid} AND p.post_type='product' LIMIT 1;",
        ["product_id", "name", "excerpt", "sku", "price_min", "price_max", "stock_quantity", "stock_status", "total_sales", "onsale"])
    if not rows:
        raise ValueError("product not found")
    r = rows[0]
    return {"product_id": int(r["product_id"]), "name": r["name"], "short_description": (r["excerpt"] or "")[:1000],
            "sku": r["sku"], "price_min": num(r["price_min"]), "price_max": num(r["price_max"]),
            "stock_quantity": num(r["stock_quantity"]) if r["stock_quantity"] is not None else None,
            "stock_status": r["stock_status"], "total_sales": int(r["total_sales"] or 0),
            "on_sale": bool(int(r["onsale"] or 0)), "categories": _product_categories(pid), "currency": "BDT"}

def tool_categories_list(a):
    if MOCK:
        return {"categories": [{"term_id": 10, "name": "Frozen Packs", "slug": "frozen-packs", "product_count": 20}], "note": "MOCK DATA ONLY."}
    t, tt = f"{DB_PREFIX}terms", f"{DB_PREFIX}term_taxonomy"
    rows = db_named(
        f"SELECT t.term_id, t.name, t.slug, tt.count FROM {DB_NAME}.{t} t JOIN {DB_NAME}.{tt} tt ON tt.term_id=t.term_id "
        f"WHERE tt.taxonomy='product_cat' ORDER BY t.name;",
        ["term_id", "name", "slug", "product_count"])
    return {"categories": [{"term_id": int(r["term_id"]), "name": r["name"], "slug": r["slug"], "product_count": int(r["product_count"])} for r in rows]}

def tool_stock_list(a):
    threshold = clamp_int(a.get("threshold", 10), 10, 0, 1000)
    low_only = bool(a.get("low_stock_only", False))
    limit = clamp_int(a.get("limit", 20), 20, 1, MAX_ROWS)
    if MOCK:
        return {"products": [MOCK_PRODUCT], "threshold": threshold, "note": "MOCK DATA ONLY."}
    p, m = f"{DB_PREFIX}posts", f"{DB_PREFIX}wc_product_meta_lookup"
    where = ["p.post_type='product'", "p.post_status='publish'"]
    if low_only:
        where.append(f"(m.stock_status!='instock' OR (m.stock_quantity IS NOT NULL AND m.stock_quantity <= {threshold}))")
    rows = db_named(
        f"SELECT p.ID, p.post_title, m.sku, m.stock_quantity, m.stock_status FROM {DB_NAME}.{p} p "
        f"JOIN {DB_NAME}.{m} m ON m.product_id=p.ID WHERE {' AND '.join(where)} ORDER BY m.stock_quantity ASC LIMIT {limit};",
        ["product_id", "name", "sku", "stock_quantity", "stock_status"])
    return {"threshold": threshold, "products": [{"product_id": int(r["product_id"]), "name": r["name"], "sku": r["sku"],
            "stock_quantity": num(r["stock_quantity"]) if r["stock_quantity"] is not None else None,
            "stock_status": r["stock_status"]} for r in rows]}

def tool_coupons_list(a):
    limit = clamp_int(a.get("limit", 20), 20, 1, MAX_ROWS)
    active_only = bool(a.get("active_only", True))
    if MOCK:
        return {"coupons": [{"coupon_id": 301, "code": "MOCK10", "discount_type": "percent", "amount": 10, "usage_count": 5}], "note": "MOCK DATA ONLY — never a real coupon code."}
    p, pm = f"{DB_PREFIX}posts", f"{DB_PREFIX}postmeta"
    where = ["p.post_type='shop_coupon'"]
    if active_only:
        where.append("p.post_status='publish'")
    rows = db_named(
        f"SELECT p.ID, p.post_title, p.post_status, "
        f"MAX(CASE WHEN pm.meta_key='coupon_amount' THEN pm.meta_value END), "
        f"MAX(CASE WHEN pm.meta_key='discount_type' THEN pm.meta_value END), "
        f"MAX(CASE WHEN pm.meta_key='usage_count' THEN pm.meta_value END), "
        f"MAX(CASE WHEN pm.meta_key='date_expires' THEN pm.meta_value END) "
        f"FROM {DB_NAME}.{p} p LEFT JOIN {DB_NAME}.{pm} pm ON pm.post_id=p.ID WHERE {' AND '.join(where)} "
        f"GROUP BY p.ID ORDER BY p.post_title LIMIT {limit};",
        ["coupon_id", "code", "status", "amount", "discount_type", "usage_count", "expiry"])
    return {"coupons": [{"coupon_id": int(r["coupon_id"]), "code": r["code"], "status": r["status"],
            "amount": num(r["amount"]), "discount_type": r["discount_type"],
            "usage_count": int(r["usage_count"] or 0), "expiry": r["expiry"]} for r in rows]}

def tool_site_health(a):
    if MOCK:
        return {"status": "ok", "uptime_seconds": 123456, "disk": {"total_gb": 100, "free_gb": 40},
                "orders_total": 2296, "products_published": 51, "customers_total": 1932,
                "note": "MOCK DATA ONLY. No plugin, theme, version or system info is ever returned."}
    try:
        total, used, free = shutil.disk_usage("/")
        disk = {"total_gb": round(total / 1e9, 2), "free_gb": round(free / 1e9, 2)}
    except Exception:
        disk = {}
    uptime = None
    try:
        uptime = int(float(open("/proc/uptime").read().split()[0]))
    except Exception:
        pass
    o, p, c = f"{DB_PREFIX}wc_orders", f"{DB_PREFIX}posts", f"{DB_PREFIX}wc_customer_lookup"
    counts = {}
    try:
        r = db_named(f"SELECT COUNT(*) FROM {DB_NAME}.{o};", ["n"]); counts["orders_total"] = int(r[0]["n"])
        r = db_named(f"SELECT COUNT(*) FROM {DB_NAME}.{p} WHERE post_type='product' AND post_status='publish';", ["n"]); counts["products_published"] = int(r[0]["n"])
        r = db_named(f"SELECT COUNT(*) FROM {DB_NAME}.{c};", ["n"]); counts["customers_total"] = int(r[0]["n"])
        r = db_named(f"SELECT ROUND(SUM(data_length+index_length)/1024/1024,2) FROM information_schema.TABLES WHERE table_schema='{DB_NAME}';", ["mb"]); counts["database_size_mb"] = num(r[0]["mb"])
    except Exception as e:
        counts["error"] = "database counts unavailable"
    return {"status": "ok", "uptime_seconds": uptime, "disk": disk, **counts,
            "timezone": "Asia/Dhaka", "currency": "BDT"}

TOOLS = [
    ("ping", "Check that the MCP connection works. Returns ok and server time in Asia/Dhaka. No business data.",
     {"type": "object", "properties": {}}),
    ("sales_summary", "Sales summary for a period. Amounts are BDT, dates are Asia/Dhaka days (converted from GMT in the database). by_status uses WooCommerce statuses: wc-completed = paid/delivered, wc-processing = in progress, wc-cancelled = cancelled, wc-failed = failed, wc-on-hold = on hold. Never use for plugin/theme/version data — this tool has none.",
     {"type": "object", "properties": {"period": {"type": "string", "enum": ["today", "yesterday", "this_month", "last_month", "date_range"], "default": "today"},
      "start_date": {"type": "string", "description": "YYYY-MM-DD, required only for date_range"},
      "end_date": {"type": "string", "description": "YYYY-MM-DD, required only for date_range"}}}),
    ("orders_search", "Search orders. query = order id, customer id, or billing-email text. status must be a WooCommerce status (see sales_summary). List results mask email; use order_detail for one order.",
     {"type": "object", "properties": {"query": {"type": "string"}, "status": {"type": "string"},
      "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 50}, "offset": {"type": "integer", "default": 0}}}),
    ("order_detail", "One order: totals (BDT), status, payment method, Dhaka dates, billing address, and line items with product names, quantities and revenue.",
     {"type": "object", "properties": {"order_id": {"type": "integer"}}, "required": ["order_id"]}),
    ("customers_search", "Search customers by name, username, email or phone text. List results MASK email and phone — never quote the masked value as a full contact. Use customer_detail for one customer.",
     {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 50}}}),
    ("customer_detail", "One customer: profile, full contact (owner token only), order totals over wc-completed + wc-processing, and the 10 most recent orders.",
     {"type": "object", "properties": {"customer_id": {"type": "integer"}}, "required": ["customer_id"]}),
    ("customer_orders", "Orders of one customer, newest first. Amounts BDT, dates Asia/Dhaka.",
     {"type": "object", "properties": {"customer_id": {"type": "integer"}, "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 50}}, "required": ["customer_id"]}),
    ("repeat_customers", "Customers with at least min_orders completed/processing orders, ranked by order count then total. Emails are masked in this list.",
     {"type": "object", "properties": {"min_orders": {"type": "integer", "default": 2, "minimum": 2}, "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 50}}}),
    ("products_list", "Published products: name, SKU, price range (BDT), stock, total sales, categories. Search matches product name only.",
     {"type": "object", "properties": {"search": {"type": "string"}, "in_stock_only": {"type": "boolean", "default": False}, "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 50}}}),
    ("product_detail", "One published product: price range (BDT), SKU, stock quantity/status, total sales, on-sale flag, categories.",
     {"type": "object", "properties": {"product_id": {"type": "integer"}}, "required": ["product_id"]}),
    ("categories_list", "Product categories with product counts.",
     {"type": "object", "properties": {}}),
    ("stock_list", "Stock view. low_stock_only=true returns out-of-stock or stock_quantity <= threshold. stock_status: instock / outofstock / onbackorder. stock_quantity may be null when stock is not managed per item.",
     {"type": "object", "properties": {"threshold": {"type": "integer", "default": 10}, "low_stock_only": {"type": "boolean", "default": False}, "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 50}}}),
    ("coupons_list", "Published shop coupons: code, discount type (percent/fixed_cart), amount, usage count, expiry. This is business data; do not invent codes.",
     {"type": "object", "properties": {"active_only": {"type": "boolean", "default": True}, "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 50}}}),
    ("site_health", "Site health ONLY: uptime, disk, order/product/customer counts, database size. It deliberately returns NO plugin, theme, WordPress/WooCommerce version, user, or system/secret information.",
     {"type": "object", "properties": {}}),
]
TOOL_FUNCS = {"ping": lambda a: {"status": "ok", "server": SERVER_NAME, "version": VERSION,
                                  "time_dhaka": (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat(), "timezone": "Asia/Dhaka"},
              "sales_summary": tool_sales_summary, "orders_search": tool_orders_search, "order_detail": tool_order_detail,
              "customers_search": tool_customers_search, "customer_detail": tool_customer_detail,
              "customer_orders": tool_customer_orders, "repeat_customers": tool_repeat_customers,
              "products_list": tool_products_list, "product_detail": tool_product_detail,
              "categories_list": tool_categories_list, "stock_list": tool_stock_list,
              "coupons_list": tool_coupons_list, "site_health": tool_site_health}

# ---------------------------------------------------------------- HTTP
def json_body(handler):
    try:
        n = int(handler.headers.get("Content-Length") or 0)
    except Exception:
        n = 0
    if n <= 0 or n > MAX_BODY:
        return None
    try:
        return json.loads(handler.rfile.read(n) or b"{}")
    except Exception:
        return None

def send_json(handler, code, obj, extra=None):
    data = json.dumps(obj).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    if extra:
        for k, v in extra.items():
            handler.send_header(k, v)
    handler.end_headers()
    handler.wfile.write(data)

def send_html(handler, code, body, cookie=None):
    data = body.encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    if cookie:
        handler.send_header("Set-Cookie", cookie)
    handler.end_headers()
    handler.wfile.write(data)

def bearer_of(handler):
    auth = handler.headers.get("Authorization") or ""
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return None

def session_ok(handler):
    cookie = handler.headers.get("Cookie") or ""
    m = re.search(r"cmcp_session=([A-Za-z0-9_\-]+)", cookie)
    if not m:
        return False
    h = sha256_hex(m.group(1))
    with _lock:
        db = state_db()
        row = db.execute("SELECT expires_at FROM sessions WHERE session_hash=?", (h,)).fetchone()
    return bool(row and datetime.now(timezone.utc).isoformat() < row[0])

def admin_pin_set():
    with _lock:
        db = state_db()
        return db.execute("SELECT value FROM admin WHERE key='pin_hash'").fetchone() is not None

def login_locked(ip):
    with _lock:
        db = state_db()
        row = db.execute("SELECT count, locked_until FROM failed_logins WHERE ip=?", (ip,)).fetchone()
    return bool(row and row[1] and time.time() < row[1])

def record_failed_login(ip):
    with _lock:
        db = state_db()
        row = db.execute("SELECT count FROM failed_logins WHERE ip=?", (ip,)).fetchone()
        cnt = (row[0] + 1) if row else 1
        locked = time.time() + 900 if cnt >= 5 else 0
        db.execute("INSERT OR REPLACE INTO failed_logins (ip, count, last_at, locked_until) VALUES (?,?,?,?)",
                   (ip, cnt, time.time(), locked))
        db.commit()

def clear_failed_login(ip):
    with _lock:
        db = state_db()
        db.execute("DELETE FROM failed_logins WHERE ip=?", (ip,))
        db.commit()

ADMIN_HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Crush Momo MCP — Admin</title><style>body{font-family:system-ui,sans-serif;max-width:900px;margin:2em auto;padding:0 1em}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:6px;text-align:left;font-size:14px}input,button{padding:8px;margin:4px 0}</style></head>
<body><h1>Crush Momo MCP — Admin</h1><p>This admin is separate from the WordPress admin. It manages MCP tokens and call logs only. It never shows a token value after creation, and logs never show full phone/email.</p>
<div id="login"><h2>Login</h2><input id="pin" type="password" placeholder="Admin PIN"><button onclick="login()">Login</button><p id="msg"></p></div>
<div id="app" style="display:none"><button onclick="logout()">Logout</button>
<h2>New token</h2><input id="tname" placeholder="Client name, e.g. Claude"><input id="texp" type="number" value="365" style="width:80px"> days <button onclick="newToken()">Generate</button><p id="newtok" style="word-break:break-all"></p>
<h2>Tokens</h2><div id="tokens"></div>
<h2>Call log (latest 100)</h2><div id="logs"></div></div>
<script>
async function api(p,m,b){const r=await fetch(p,{method:m,headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});return r.json();}
async function login(){const r=await api('/admin/api/login','POST',{pin:document.getElementById('pin').value});document.getElementById('msg').textContent=r.ok?'Logged in':'Login failed';if(r.ok){show();}}
async function logout(){await api('/admin/api/logout','POST',{});location.reload();}
async function show(){document.getElementById('login').style.display='none';document.getElementById('app').style.display='block';const t=await api('/admin/api/tokens','GET');document.getElementById('tokens').innerHTML='<table><tr><th>Name</th><th>Created</th><th>Expires</th><th>Last used</th><th>Action</th></tr>'+t.tokens.map(x=>'<tr><td>'+x.name+'</td><td>'+x.created_at+'</td><td>'+x.expires_at+'</td><td>'+(x.last_used_at||'')+'</td><td>'+(x.revoked?'revoked':'<button onclick="revoke('+x.id+')">Revoke</button>')+'</td></tr>').join('')+'</table>';const l=await api('/admin/api/logs','GET');document.getElementById('logs').innerHTML='<table><tr><th>Time (UTC)</th><th>Token</th><th>Tool</th><th>Rows</th><th>IP</th><th>OK</th></tr>'+l.logs.map(x=>'<tr><td>'+x.ts+'</td><td>'+x.token_name+'</td><td>'+x.tool+'</td><td>'+x.row_count+'</td><td>'+x.ip+'</td><td>'+x.ok+'</td></tr>').join('')+'</table>';}
async function newToken(){const r=await api('/admin/api/tokens','POST',{name:document.getElementById('tname').value,expires_days:parseInt(document.getElementById('texp').value||'365')});document.getElementById('newtok').textContent=r.token?('COPY NOW — shown once: '+r.token):(r.error||'Failed');if(r.token)show();}
async function revoke(id){await api('/admin/api/tokens/'+id+'/revoke','POST',{});show();}
fetch('/admin/api/status').then(r=>r.json()).then(s=>{if(s.authenticated)show();if(!s.pin_set)document.getElementById('msg').textContent='Admin PIN is not set yet. The owner must set it with the setup command on the VPS (see private deploy runbook).';});
</script></body></html>"""

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a):
        pass
    def _ip(self):
        return self.headers.get("X-Forwarded-For", "").split(",")[0].strip() or self.client_address[0]

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/health"):
            return send_json(self, 200, {"service": SERVER_NAME, "version": VERSION, "status": "ok"})
        if path == "/.well-known/oauth-protected-resource/mcp":
            return send_json(self, 200, {"resource": BASE_URL + "/mcp", "authorization_servers": [BASE_URL],
                                         "scopes_supported": ["read"]})
        if path == "/.well-known/oauth-authorization-server":
            return send_json(self, 200, {"issuer": BASE_URL, "authorization_endpoint": BASE_URL + "/oauth/authorize",
                                         "token_endpoint": BASE_URL + "/oauth/token", "registration_endpoint": BASE_URL + "/oauth/register",
                                         "response_types_supported": ["code"], "grant_types_supported": ["authorization_code", "refresh_token"],
                                         "code_challenge_methods_supported": ["S256", "plain"]})
        if path == "/admin":
            return send_html(self, 200, ADMIN_HTML)
        if path == "/admin/api/status":
            return send_json(self, 200, {"pin_set": admin_pin_set(), "authenticated": session_ok(self)})
        if path == "/admin/api/tokens":
            if not session_ok(self):
                return send_json(self, 401, {"error": "unauthorized"})
            with _lock:
                db = state_db()
                rows = db.execute("SELECT id, name, created_at, expires_at, last_used_at, revoked FROM tokens ORDER BY id DESC").fetchall()
            return send_json(self, 200, {"tokens": [{"id": r[0], "name": r[1], "created_at": r[2], "expires_at": r[3], "last_used_at": r[4], "revoked": bool(r[5])} for r in rows]})
        if path == "/admin/api/logs":
            if not session_ok(self):
                return send_json(self, 401, {"error": "unauthorized"})
            qs = parse_qs(parsed.query)
            limit = clamp_int(qs.get("limit", ["100"])[0], 100, 1, 500)
            with _lock:
                db = state_db()
                rows = db.execute("SELECT ts, token_name, tool, row_count, ip, ok FROM call_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return send_json(self, 200, {"logs": [{"ts": r[0], "token_name": r[1], "tool": r[2], "row_count": r[3], "ip": r[4], "ok": r[5]} for r in rows]})
        if path == "/oauth/authorize":
            qs = parse_qs(parsed.query)
            cid = qs.get("client_id", [""])[0]
            redir = qs.get("redirect_uri", [""])[0]
            state = qs.get("state", [""])[0]
            chall = qs.get("code_challenge", [""])[0]
            method = qs.get("code_challenge_method", ["plain"])[0]
            form = f"""<!doctype html><html><body><h1>Crush Momo MCP — PIN login</h1>
            <p>This grants a short-lived read-only MCP token to the requesting app. It never grants WordPress admin access.</p>
            <form method="post" action="/oauth/authorize">
            <input type="hidden" name="client_id" value="{html.escape(cid)}">
            <input type="hidden" name="redirect_uri" value="{html.escape(redir)}">
            <input type="hidden" name="state" value="{html.escape(state)}">
            <input type="hidden" name="code_challenge" value="{html.escape(chall)}">
            <input type="hidden" name="code_challenge_method" value="{html.escape(method)}">
            <input type="password" name="pin" placeholder="Admin PIN" required>
            <button type="submit">Approve (read-only)</button></form></body></html>"""
            return send_html(self, 200, form)
        return send_json(self, 404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if 0 < length <= MAX_BODY else b""
        ip = self._ip()
        # ---- admin API
        if path == "/admin/api/login":
            try:
                body = json.loads(raw or b"{}")
            except Exception:
                return send_json(self, 400, {"error": "bad json"})
            if login_locked(ip):
                return send_json(self, 429, {"error": "too many failed logins, try later"})
            with _lock:
                db = state_db()
                row = db.execute("SELECT value FROM admin WHERE key='pin_hash'").fetchone()
            if not row or not check_pin(str(body.get("pin", "")), row[0]):
                record_failed_login(ip)
                return send_json(self, 401, {"error": "unauthorized"})
            clear_failed_login(ip)
            sess = secrets.token_urlsafe(32)
            with _lock:
                db = state_db()
                db.execute("INSERT INTO sessions VALUES (?,?)", (sha256_hex(sess), (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()))
                db.commit()
            return send_json(self, 200, {"ok": True}, {"Set-Cookie": f"cmcp_session={sess}; HttpOnly; SameSite=Lax; Secure; Path=/; Max-Age=7200"})
        if path == "/admin/api/logout":
            return send_json(self, 200, {"ok": True}, {"Set-Cookie": "cmcp_session=; HttpOnly; SameSite=Lax; Secure; Path=/; Max-Age=0"})
        if path == "/admin/api/tokens":
            if not session_ok(self):
                return send_json(self, 401, {"error": "unauthorized"})
            try:
                body = json.loads(raw or b"{}")
            except Exception:
                return send_json(self, 400, {"error": "bad json"})
            name = str(body.get("name", "")).strip()[:80] or "unnamed"
            days = clamp_int(body.get("expires_days", 365), 365, 1, 3650)
            tok = secrets.token_urlsafe(32)
            now = datetime.now(timezone.utc)
            with _lock:
                db = state_db()
                db.execute("INSERT INTO tokens (name, token_hash, created_at, expires_at, revoked) VALUES (?,?,?,?,0)",
                           (name, sha256_hex(tok), now.isoformat(), (now + timedelta(days=days)).isoformat()))
                db.commit()
            return send_json(self, 200, {"token": tok, "name": name, "expires_days": days})
        m = re.fullmatch(r"/admin/api/tokens/(\d+)/revoke", path)
        if m:
            if not session_ok(self):
                return send_json(self, 401, {"error": "unauthorized"})
            with _lock:
                db = state_db()
                db.execute("UPDATE tokens SET revoked=1 WHERE id=?", (int(m.group(1)),))
                db.commit()
            return send_json(self, 200, {"ok": True})
        # ---- OAuth
        if path == "/oauth/register":
            try:
                body = json.loads(raw or b"{}")
            except Exception:
                body = {}
            cid = "cmcp_" + secrets.token_hex(12)
            redirs = body.get("redirect_uris") or []
            with _lock:
                db = state_db()
                db.execute("INSERT INTO oauth_clients VALUES (?,?,?)", (cid, json.dumps(redirs), datetime.now(timezone.utc).isoformat()))
                db.commit()
            return send_json(self, 201, {"client_id": cid, "client_id_issued_at": int(time.time())})
        if path == "/oauth/authorize":
            form = parse_qs(raw.decode(errors="ignore"))
            pin = form.get("pin", [""])[0]
            cid = form.get("client_id", [""])[0]
            redir = form.get("redirect_uri", [""])[0]
            state = form.get("state", [""])[0]
            chall = form.get("code_challenge", [""])[0]
            method = form.get("code_challenge_method", ["plain"])[0]
            if login_locked(ip):
                return send_json(self, 429, {"error": "too many failed logins"})
            with _lock:
                db = state_db()
                row = db.execute("SELECT value FROM admin WHERE key='pin_hash'").fetchone()
            if not row or not check_pin(pin, row[0]) or not redir:
                record_failed_login(ip)
                return send_html(self, 401, "<h1>Login failed</h1><p>Wrong PIN or missing redirect.</p>")
            clear_failed_login(ip)
            code = secrets.token_urlsafe(32)
            with _lock:
                db = state_db()
                db.execute("INSERT INTO oauth_codes VALUES (?,?,?,?,?,?)",
                           (sha256_hex(code), cid, redir, chall, method, (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()))
                db.commit()
            sep = "&" if "?" in redir else "?"
            loc = f"{redir}{sep}code={code}" + (f"&state={state}" if state else "")
            self.send_response(302)
            self.send_header("Location", loc)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/oauth/token":
            form = parse_qs(raw.decode(errors="ignore"))
            grant = form.get("grant_type", [""])[0]
            if grant == "authorization_code":
                code = form.get("code", [""])[0]
                redir = form.get("redirect_uri", [""])[0]
                verifier = form.get("code_verifier", [""])[0]
                with _lock:
                    db = state_db()
                    row = db.execute("SELECT client_id, redirect_uri, challenge, challenge_method, expires_at FROM oauth_codes WHERE code_hash=?", (sha256_hex(code),)).fetchone()
                    if row:
                        db.execute("DELETE FROM oauth_codes WHERE code_hash=?", (sha256_hex(code),))
                        db.commit()
                if not row or row[1] != redir or datetime.now(timezone.utc).isoformat() > row[4]:
                    return send_json(self, 400, {"error": "invalid_grant"})
                if row[2]:
                    if row[3] == "S256":
                        chal = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
                        if chal != row[2]:
                            return send_json(self, 400, {"error": "invalid_grant"})
                    elif verifier != row[2]:
                        return send_json(self, 400, {"error": "invalid_grant"})
                access = secrets.token_urlsafe(32)
                refresh = secrets.token_urlsafe(32)
                now = datetime.now(timezone.utc)
                with _lock:
                    db = state_db()
                    db.execute("INSERT INTO oauth_tokens VALUES (?,?,?,?)", (sha256_hex(access), "access", row[0], (now + timedelta(hours=1)).isoformat(), 0))
                    db.execute("INSERT INTO oauth_tokens VALUES (?,?,?,?)", (sha256_hex(refresh), "refresh", row[0], (now + timedelta(days=30)).isoformat(), 0))
                    db.commit()
                return send_json(self, 200, {"access_token": access, "token_type": "Bearer", "expires_in": 3600, "refresh_token": refresh, "scope": "read"})
            if grant == "refresh_token":
                ref = form.get("refresh_token", [""])[0]
                with _lock:
                    db = state_db()
                    row = db.execute("SELECT client_id, expires_at, revoked FROM oauth_tokens WHERE token_hash=? AND kind='refresh'", (sha256_hex(ref),)).fetchone()
                if not row or row[2] or datetime.now(timezone.utc).isoformat() > row[1]:
                    return send_json(self, 400, {"error": "invalid_grant"})
                access = secrets.token_urlsafe(32)
                with _lock:
                    db = state_db()
                    db.execute("INSERT INTO oauth_tokens VALUES (?,?,?,?)", (sha256_hex(access), "access", row[0], (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(), 0))
                    db.commit()
                return send_json(self, 200, {"access_token": access, "token_type": "Bearer", "expires_in": 3600, "scope": "read"})
            return send_json(self, 400, {"error": "unsupported_grant_type"})
        # ---- MCP
        if path == "/mcp":
            try:
                body = json.loads(raw or b"{}")
            except Exception:
                return send_json(self, 400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            method = body.get("method", "")
            req_id = body.get("id")
            if method.startswith("notifications/"):
                return send_json(self, 202, {})
            if method == "initialize":
                pv = (body.get("params") or {}).get("protocolVersion")
                chosen = pv if pv in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
                return send_json(self, 200, {"jsonrpc": "2.0", "id": req_id, "result": {
                    "protocolVersion": chosen, "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": VERSION}}})
            # all other MCP methods require auth
            auth = verify_bearer(bearer_of(self))
            if not auth:
                return send_json(self, 401, {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": "unauthorized: a valid Bearer token is required"}})
            if not rate_ok("mcp:" + auth[1] + ":" + ip):
                return send_json(self, 429, {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": "rate limited"}})
            if method == "ping":
                log_call(auth[1], "ping", {}, 0, ip, True)
                return send_json(self, 200, {"jsonrpc": "2.0", "id": req_id, "result": {}})
            if method == "tools/list":
                log_call(auth[1], "tools/list", {}, len(TOOLS), ip, True)
                return send_json(self, 200, {"jsonrpc": "2.0", "id": req_id, "result": {"tools": [
                    {"name": n, "description": d, "inputSchema": s} for n, d, s in TOOLS]}})
            if method in ("resources/list", "prompts/list"):
                log_call(auth[1], method, {}, 0, ip, True)
                return send_json(self, 200, {"jsonrpc": "2.0", "id": req_id, "result": {"resources": []} if method == "resources/list" else {"prompts": []}})
            if method == "tools/call":
                params = body.get("params") or {}
                name = params.get("name", "")
                args = params.get("arguments") or {}
                if name not in TOOL_FUNCS:
                    log_call(auth[1], "tools/call:" + str(name)[:60], args, 0, ip, False, "unknown tool")
                    return send_json(self, 200, {"jsonrpc": "2.0", "id": req_id, "result": {
                        "content": [{"type": "text", "text": json.dumps({"error": "unknown tool: no such tool exists (allowlist only)"})}], "isError": True}})
                try:
                    result = TOOL_FUNCS[name](args)
                    nrows = len(result.get("orders", result.get("customers", result.get("products", result.get("coupons", []))))) if isinstance(result, dict) else 0
                    if isinstance(result, dict) and "total_orders" in result:
                        nrows = result["total_orders"]
                    log_call(auth[1], name, args, nrows, ip, True)
                    text = json.dumps(result, default=str)
                    return send_json(self, 200, {"jsonrpc": "2.0", "id": req_id, "result": {
                        "content": [{"type": "text", "text": text}], "structuredContent": result}})
                except Exception as e:
                    log_call(auth[1], name, args, 0, ip, False, str(e)[:200])
                    return send_json(self, 200, {"jsonrpc": "2.0", "id": req_id, "result": {
                        "content": [{"type": "text", "text": json.dumps({"error": str(e)})}], "isError": True}})
            return send_json(self, 200, {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "method not found"}})
        return send_json(self, 404, {"error": "not found"})

    def do_PUT(self):
        return send_json(self, 405, {"error": "method not allowed"})
    def do_DELETE(self):
        return send_json(self, 405, {"error": "method not allowed"})

def main():
    state_db()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"{SERVER_NAME} {VERSION} listening on {HOST}:{PORT} mock={MOCK} db={'configured' if MYSQL_CNF else 'unset'}", flush=True)
    server.serve_forever()

if __name__ == "__main__":
    main()
