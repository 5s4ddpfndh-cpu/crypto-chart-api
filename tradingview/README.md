# TradingView ICT indicators (Pine Script v5)

Every ICT tool has its own indicator. `ict_toolkit_all_in_one.pine` combines all of them in one
indicator, each switchable in Settings (useful on the free plan, which limits indicators per chart).

| # | File | Tool |
|---|---|---|
| 1 | `ict_market_structure.pine` | BOS / MSS (CHoCH) and HH / HL / LH / LL swings |
| 2 | `ict_order_blocks.pine` | Order blocks |
| 3 | `ict_breaker_blocks.pine` | Breaker blocks (failed order blocks) |
| 4 | `ict_fair_value_gap.pine` | Fair value gaps with 50% (CE) line |
| 5 | `ict_inversion_fvg.pine` | Inversion FVG (IFVG) |
| 6 | `ict_balanced_price_range.pine` | Balanced price range (BPR) |
| 7 | `ict_volume_imbalance.pine` | Volume imbalance (VI) |
| 8 | `ict_liquidity.pine` | BSL / SSL, EQH / EQL, liquidity sweeps |
| 9 | `ict_premium_discount.pine` | Premium / discount / equilibrium |
| 10 | `ict_ote.pine` | OTE 62-79% (70.5%) with -0.27 / -0.62 / -1 / -2 targets |
| 11 | `ict_killzones.pine` | Asia, London, NY AM, NY Lunch, NY PM with session high / low levels |
| 12 | `ict_silver_bullet.pine` | Silver Bullet windows and the FVGs inside them |
| 13 | `ict_macros.pine` | ICT macro windows |
| 14 | `ict_key_levels.pine` | PDH / PDL, PWH / PWL, PMH / PML, IPDA 20 / 40 / 60 |
| 15 | `ict_opens.pine` | Midnight open, 08:30 open, daily / weekly / monthly opens |
| 16 | `ict_opening_gaps.pine` | NWOG / NDOG |
| 17 | `ict_displacement.pine` | Displacement candles |
| 18 | `ict_smt_divergence.pine` | SMT divergence against a correlated market |
| - | `ict_toolkit_all_in_one.pine` | All of the above in one indicator |

All times are New York time, as in the ICT school.

## How to add to TradingView
1. Open a chart, then **Pine Editor** at the bottom.
2. Delete the template code and paste the whole contents of one `.pine` file.
3. Click **Save**, then **Add to chart**. Repeat for each indicator you want.

These are analysis tools only, not financial advice.
