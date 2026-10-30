---
name: crushmomo
description: Answer Crush Momo business questions from live readonly data — sales, orders, customers, products, stock, categories, coupons and site health.
---

# Crush Momo — skill

Use the crushmomo-mcp server ONLY for Crush Momo business questions. It is readonly.
Server: `https://mcp.crushmomo.com/mcp`
Currency: BDT. Timezone: Asia/Dhaka. Dates: `YYYY-MM-DD`.

## When to use it

Use it when the user asks about Crush Momo sales, orders, customers, products,
stock, categories, coupons, or site health — live data, not guesses.
Do not use it for other sites, and do not use it to look up system info.

## Which tool, for which question

- "How much did we sell today / this month / on a date?" → `sales_summary`
- "Find order X / orders by status" → `orders_search`, then `order_detail`
- "Find customer by name/email/phone" → `customers_search` (masked list), then `customer_detail`
- "This customer's orders" → `customer_orders`
- "Repeat customers" → `repeat_customers`
- "What products / price / stock?" → `products_list`, `product_detail`
- "Categories?" → `categories_list`
- "What is low on stock?" → `stock_list` (`low_stock_only: true`)
- "Active coupons?" → `coupons_list`
- "Is the site healthy?" → `site_health`
- "Is it connected?" → `ping`

## Rules

- Readonly only. No writes, no edits, no cancellations, no bulk export (max 50 rows/call).
- No plugin, theme, version, user, password, or secret information — the server has no tool for it.
- Never put a token in chat, code, or a repo. Authentication is done at install/connect time, never in a prompt.
- Quote numbers exactly as returned, say BDT and Asia/Dhaka, and say "no matching records" when a result is empty.
