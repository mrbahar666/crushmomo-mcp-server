# Crush Momo MCP — skill

Use this MCP server ONLY for Crush Momo business questions. It is readonly.
Server: `https://mcp.crushmomo.com/mcp` · Connector name: `crushmomo-mcp`
Currency: BDT. Timezone: Asia/Dhaka. Dates: `YYYY-MM-DD`.

## When to use it

Use it when the user asks about Crush Momo sales, orders, customers, products,
stock, categories, coupons, or site health — live data, not guesses.
Do not use it for other sites, and do not use it to look up system info.

## Which tool, for which question

- "How much did we sell today / this month / on a date?" → `sales_summary`
  (`period`: today | yesterday | this_month | last_month | date_range + start/end dates)
- "Find order X / orders by status / by email" → `orders_search`, then `order_detail` for one order
- "Find customer by name/email/phone" → `customers_search` (masked list), then `customer_detail` (one customer, full contact)
- "This customer's orders" → `customer_orders`
- "Repeat customers" → `repeat_customers` (`min_orders`, default 2)
- "What products / price / stock?" → `products_list`, `product_detail`
- "Categories?" → `categories_list`
- "What is low on stock?" → `stock_list` (`low_stock_only: true`)
- "Active coupons?" → `coupons_list`
- "Is the site healthy?" → `site_health`
- "Is it connected?" → `ping`

## Field meanings you must know

- Amounts are BDT. `total_amount` is the order total; `tax_amount` is tax included in it.
- Dates are Dhaka local time, converted from GMT in WooCommerce.
- Statuses: `wc-completed` = paid/delivered, `wc-processing` = in progress,
  `wc-on-hold` = on hold, `wc-cancelled` = cancelled, `wc-failed` = failed,
  `wc-pending` = pending payment, `wc-refunded` = refunded.
- `stock_status`: `instock` / `outofstock` / `onbackorder`. `stock_quantity` may be
  `null` when stock is not managed per item — say so, never invent a number.
- Customer totals count `wc-completed` + `wc-processing` only.
- Lists mask email/phone. Never present a masked value as a full contact.
  Use `customer_detail` for one customer when full contact is genuinely needed.

## Rules (see docs/DO-NOT-DO.md for the full list)

- Readonly only. No writes, no edits, no cancellations, no bulk export (max 50 rows/call).
- No plugin, theme, version, user, password, or secret information — the server
  has no tool for it. If asked, say so plainly.
- Never put a token in chat, code, or a repo. Never share a token.
- Quote numbers exactly as returned, say BDT and Asia/Dhaka, and say "no matching
  records" when a result is empty. You may summarise, rank, and reformat the
  returned data in your answer — that never changes the site.
- Full tool reference with parameters, returns, and mock examples: `docs/USAGE.md`.
- Install/connect per client: `docs/INSTALL.md`.
