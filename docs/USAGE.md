# Crush Momo MCP — How to use

Server: `https://mcp.crushmomo.com/mcp` · Admin: `https://mcp.crushmomo.com/admin`
Connector name in clients: `crushmomo-mcp`
Currency: **BDT** everywhere an amount appears. Timezone: **Asia/Dhaka** (+06:00).
Dates are `YYYY-MM-DD`. Datetimes returned by tools are Dhaka local time
(converted from GMT stored in WooCommerce). No tool ever writes anything.

## Limits that apply to every tool

- Max **50 rows per call**. Ask for a smaller limit when you only need a few.
- There is **no bulk-export tool**. Do not try to page through the whole
  customer or order table to build a full copy.
- Rate limit: 100 MCP calls per minute per token. Back off on 429.
- Unauthenticated calls get **401** and no tool list. That is by design.

## Order statuses (WooCommerce)

| Status | Meaning |
|---|---|
| `wc-completed` | Paid and delivered/completed |
| `wc-processing` | In progress |
| `wc-on-hold` | On hold, awaiting something |
| `wc-pending` | Pending payment |
| `wc-cancelled` | Cancelled |
| `wc-refunded` | Refunded |
| `wc-failed` | Payment failed |
| `wc-checkout-draft` | Abandoned checkout draft |
| `trash` | Trashed |

Totals in `customer_detail` / `repeat_customers` count only
`wc-completed` + `wc-processing`, unless a tool says otherwise.

## Every tool

### 1. `ping`
Params: none.
Returns: `{"status":"ok","server":"crushmomo-mcp","version":"1.0.0","time_dhaka":"...","timezone":"Asia/Dhaka"}`
Example question: "Is the Crush Momo MCP connected?"
Example call: `{"name":"ping","arguments":{}}`

### 2. `sales_summary`
Params: `period` = `today` (default) | `yesterday` | `this_month` | `last_month` | `date_range`.
For `date_range` also `start_date` and `end_date` (`YYYY-MM-DD`, max 366 days).
Returns: `period`, `start_date`, `end_date`, `currency` (BDT), `timezone`,
`by_status` (order_count, total_amount, average_amount per status),
`by_day` (date, order_count, total_amount), `total_orders`, `total_amount`.
Example question: "How much did we sell today?" / "Last month's sales by status?"
Example call: `{"name":"sales_summary","arguments":{"period":"today"}}`
Example response (MOCK DATA ONLY, never real sales):
```json
{"period":"today","start_date":"2026-10-30","end_date":"2026-10-30","currency":"BDT","timezone":"Asia/Dhaka","by_status":[{"status":"wc-completed","order_count":12,"total_amount":14800,"average_amount":1233.33}],"total_orders":12,"total_amount":14800}
```

### 3. `orders_search`
Params: `query` (order id, customer id, or billing-email text), `status` (optional, see table above),
`limit` (1–50, default 20), `offset` (default 0).
Returns: `orders[]` with `order_id`, `status`, `currency`, `total_amount`, `tax_amount`,
`customer_id`, `billing_email` (**masked** in lists), `payment_method`, `date_created_dhaka`.
Example question: "Find order 5001" / "Show today's processing orders"
Example call: `{"name":"orders_search","arguments":{"query":"5001"}}`

### 4. `order_detail`
Params: `order_id` (integer, required).
Returns: one order — totals (BDT), status, payment method/title, Dhaka created/updated dates,
customer note, `billing` address, and `items[]` (product name, SKU, quantity, net/gross revenue).
Example question: "What was in order 5001 and who ordered it?"
Example call: `{"name":"order_detail","arguments":{"order_id":5001}}`
Example response (MOCK DATA ONLY):
```json
{"order_id":5001,"status":"wc-completed","currency":"BDT","total_amount":1250,"customer_id":101,"billing_email":"ayesha@example.test","payment_method":"cod","date_created_dhaka":"2026-10-28 19:30:00","billing":{"first_name":"Ayesha","last_name":"Rahman","city":"Dhaka","country":"BD"},"items":[{"product_id":201,"product_name":"Chicken Momo (Frozen, 20 pc)","quantity":2,"net_revenue":900,"gross_revenue":900}]}
```

### 5. `customers_search`
Params: `query` (name, username, email or phone text), `limit` (1–50, default 20).
Returns: `customers[]` with `customer_id`, `username`, names, `email` (**masked**),
`phone` (**masked**), city/state/country, `date_registered`, plus `order_count` and
`total_amount` (completed + processing). Never present a masked value as a full contact.
Example question: "Find the customer named Ayesha"
Example call: `{"name":"customers_search","arguments":{"query":"Ayesha","limit":10}}`

### 6. `customer_detail`
Params: `customer_id` (integer, required).
Returns: profile, **full** email/phone (this single-record view is for the owner token only),
city/state/country/postcode, `date_registered`, `date_last_active`, order totals
(completed + processing), and the 10 most recent orders.
Example question: "Show me everything about customer 101 and their last orders"
Example call: `{"name":"customer_detail","arguments":{"customer_id":101}}`

### 7. `customer_orders`
Params: `customer_id` (integer, required), `limit` (1–50, default 20).
Returns: that customer's orders, newest first, with status, BDT totals, payment method, Dhaka date.
Example question: "All orders by customer 101"
Example call: `{"name":"customer_orders","arguments":{"customer_id":101,"limit":20}}`

### 8. `repeat_customers`
Params: `min_orders` (integer, default 2, minimum 2), `limit` (1–50, default 20).
Returns: customers with at least `min_orders` completed/processing orders, ranked by
order count then total. Emails are **masked** in this list.
Example question: "Who are our repeat customers?"
Example call: `{"name":"repeat_customers","arguments":{"min_orders":3,"limit":20}}`

### 9. `products_list`
Params: `search` (product-name text, optional), `in_stock_only` (boolean, default false),
`limit` (1–50, default 20).
Returns: `products[]` with `product_id`, `name`, `short_description`, `sku`,
`price_min`/`price_max` (BDT), `stock_quantity`, `stock_status`, `total_sales`, `categories[]`.
Example question: "List our frozen packs" / "What products do we sell?"
Example call: `{"name":"products_list","arguments":{"search":"Momo","limit":20}}`
Example response (MOCK DATA ONLY):
```json
{"products":[{"product_id":201,"name":"Chicken Momo (Frozen, 20 pc)","sku":"CM-CH-20","price_min":450,"price_max":450,"stock_quantity":42,"stock_status":"instock","total_sales":310,"categories":["Frozen Packs"]}],"currency":"BDT"}
```

### 10. `product_detail`
Params: `product_id` (integer, required).
Returns: one published product — name, short description, SKU, BDT price range,
stock quantity/status, total sales, `on_sale`, categories.
Example question: "Price and stock for product 201?"
Example call: `{"name":"product_detail","arguments":{"product_id":201}}`

### 11. `categories_list`
Params: none.
Returns: `categories[]` with `term_id`, `name`, `slug`, `product_count`.
Example question: "What product categories do we have?"
Example call: `{"name":"categories_list","arguments":{}}`

### 12. `stock_list`
Params: `threshold` (integer, default 10), `low_stock_only` (boolean, default false),
`limit` (1–50, default 20).
Returns: products with `stock_quantity` and `stock_status` (`instock` / `outofstock` / `onbackorder`).
With `low_stock_only=true` it returns out-of-stock items or items at/below `threshold`.
`stock_quantity` may be `null` when stock is not managed per item — say so, do not invent a number.
Example question: "What is running low?"
Example call: `{"name":"stock_list","arguments":{"low_stock_only":true,"threshold":10}}`

### 13. `coupons_list`
Params: `active_only` (boolean, default true), `limit` (1–50, default 20).
Returns: `coupons[]` with `coupon_id`, `code`, `status`, `amount`, `discount_type`
(`percent` / `fixed_cart` / etc.), `usage_count`, `expiry`. Do not invent coupon codes;
only report codes this tool returns.
Example question: "What coupons are active?"
Example call: `{"name":"coupons_list","arguments":{"active_only":true}}`

### 14. `site_health`
Params: none.
Returns: `status`, `uptime_seconds`, `disk` (total/free GB), `orders_total`,
`products_published`, `customers_total`, `database_size_mb`, timezone, currency.
It deliberately returns **no** plugin, theme, WordPress/WooCommerce version, user,
password, or secret information. If someone asks for those, say the MCP does not provide them.
Example question: "Is the site healthy? How big is the database?"
Example call: `{"name":"site_health","arguments":{}}`

## How to answer from a tool result

- Quote numbers exactly as returned; do not round totals unless you say you rounded.
- Say the currency (BDT) and that dates are Asia/Dhaka.
- If a list is masked, say the contact is masked and use `customer_detail` for one customer.
- If a result is empty, say "no matching records" — do not invent a record.
- You may summarise, rank, compare and reformat the returned data in your own answer.
  That is presentation only. It never changes anything on the site.
