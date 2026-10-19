# 2. Price table uses published list prices, marked unverified

`pricing/prices.json` holds Anthropic first-party list prices with standard cache multipliers
(5m = 1.25x, 1h = 2x), `verified: false`. Claude Code's own `cost-state.costUSD` differs by +3.5% to
+35% and no multiplier set reconciles it, so dollar figures are labelled "API-equivalent". Token
totals reconcile exactly. Owner to confirm or correct the table.
