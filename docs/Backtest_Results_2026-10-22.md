# Backtest Results — 2026-10-22 (RESEARCH PROXY)

- Source: **public Binance USDT candles** via `config.research.binance.json`.
- Strategy: `ResearchFamily` (binds `app/indicators/families.py` — the SAME causal signal math the live dispatcher routes to, WITHOUT the order-safety veto).
- Timeframe: `1d`   Range: `20240101-20261020`   Fee: **0.0025/side** taker; `entry_pricing.price_side=other` approximates the touch-to-touch spread.

> **NOT Alpaca execution parity.** This ranks *signal quality / after-cost expectancy* on a price proxy. It does not prove profit, and it does not authorize live trading. The live veto (stake caps, exposure, kill-switch) is exercised only in PAPER, never here.

## Best-by-expectancy family per pair (min 5 trades)

| Pair | Family | Trades | Win% | Profit% | Exp expectancy | Profit factor | Max DD% |
|---|---|---|---|---|---|---|---|
| AVAX/USD | momentum_ema_vol | 6 | 50.0 | 31.897 | 531.6155 | 2.6171 | 16.9 |
| BTC/USD | link_trend | 7 | 42.857 | 0.718 | 10.2535 | 1.0229 | 25.166 |
| DOGE/USD | bb_squeeze | 6 | 33.333 | 14.377 | 239.6091 | 1.6143 | 18.954 |
| DOT/USD | momentum_ema_vol | 7 | 14.286 | -34.247 | -489.2475 | 0.228 | 44.361 |
| ETH/USD | momentum_ema_vol | 7 | 42.857 | 57.4 | 820.0038 | 2.0701 | 32.409 |
| LINK/USD | momentum_ema_vol | 5 | 60.0 | 55.917 | 1118.3428 | 4.6255 | 9.323 |
| LTC/USD | momentum_ema_vol | 6 | 33.333 | -2.393 | -39.8894 | 0.9472 | 37.184 |
| SOL/USD | bb_squeeze | 7 | 42.857 | -11.988 | -171.2627 | 0.5354 | 25.466 |
| UNI/USD | link_trend | 6 | 66.667 | 162.616 | 2710.2634 | 4.2651 | 21.041 |
| XRP/USD | momentum_ema_vol | 9 | 22.222 | -18.456 | -205.0687 | 0.6103 | 36.794 |

## All rows

| Pair | TF | Family | Trades | Win% | Profit% | Expectancy | PF | MaxDD% | rc |
|---|---|---|---|---|---|---|---|---|---|
| BTC/USD | 1d | momentum_ema_vol | 8 | 37.5 | -10.105 | -126.3106 | 0.638 | 27.889 | 0 |
| BTC/USD | 1d | rsi_divergence | 1 | 100.0 | 14.832 | 1483.1888 | 0.0 | 0.0 | 0 |
| BTC/USD | 1d | bb_squeeze | 11 | 27.273 | -5.381 | -48.9137 | 0.8672 | 23.936 | 0 |
| BTC/USD | 1d | link_trend | 7 | 42.857 | 0.718 | 10.2535 | 1.0229 | 25.166 | 0 |
| ETH/USD | 1d | momentum_ema_vol | 7 | 42.857 | 57.4 | 820.0038 | 2.0701 | 32.409 | 0 |
| ETH/USD | 1d | rsi_divergence | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |
| ETH/USD | 1d | bb_squeeze | 6 | 50.0 | -5.902 | -98.3659 | 0.7332 | 14.632 | 0 |
| ETH/USD | 1d | link_trend | 5 | 60.0 | 32.421 | 648.4162 | 1.9954 | 22.633 | 0 |
| XRP/USD | 1d | momentum_ema_vol | 9 | 22.222 | -18.456 | -205.0687 | 0.6103 | 36.794 | 0 |
| XRP/USD | 1d | rsi_divergence | 1 | 100.0 | 20.334 | 2033.4154 | 0.0 | 0.0 | 0 |
| XRP/USD | 1d | bb_squeeze | 4 | 50.0 | -11.213 | -280.3316 | 0.177 | 13.212 | 0 |
| XRP/USD | 1d | link_trend | 2 | 0.0 | -16.244 | -812.2186 | 0.0 | 16.244 | 0 |
| DOT/USD | 1d | momentum_ema_vol | 7 | 14.286 | -34.247 | -489.2475 | 0.228 | 44.361 | 0 |
| DOT/USD | 1d | rsi_divergence | 1 | 0.0 | -15.351 | -1535.1394 | 0.0 | 15.351 | 0 |
| DOT/USD | 1d | bb_squeeze | 4 | 25.0 | -17.031 | -425.7789 | 0.3459 | 23.886 | 0 |
| DOT/USD | 1d | link_trend | 1 | 100.0 | 12.507 | 1250.6616 | 0.0 | 0.0 | 0 |
| LINK/USD | 1d | momentum_ema_vol | 5 | 60.0 | 55.917 | 1118.3428 | 4.6255 | 9.323 | 0 |
| LINK/USD | 1d | rsi_divergence | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |
| LINK/USD | 1d | bb_squeeze | 7 | 28.571 | 15.24 | 217.7149 | 1.698 | 19.749 | 0 |
| LINK/USD | 1d | link_trend | 7 | 28.571 | -8.885 | -126.9356 | 0.8503 | 34.217 | 0 |
| SOL/USD | 1d | momentum_ema_vol | 4 | 0.0 | -26.299 | -657.4654 | 0.0 | 26.299 | 0 |
| SOL/USD | 1d | rsi_divergence | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |
| SOL/USD | 1d | bb_squeeze | 7 | 42.857 | -11.988 | -171.2627 | 0.5354 | 25.466 | 0 |
| SOL/USD | 1d | link_trend | 4 | 50.0 | 16.346 | 408.6514 | 1.6375 | 15.46 | 0 |
| UNI/USD | 1d | momentum_ema_vol | 7 | 42.857 | 91.607 | 1308.6678 | 2.9482 | 34.869 | 0 |
| UNI/USD | 1d | rsi_divergence | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |
| UNI/USD | 1d | bb_squeeze | 5 | 0.0 | -34.333 | -686.6566 | 0.0 | 34.333 | 0 |
| UNI/USD | 1d | link_trend | 6 | 66.667 | 162.616 | 2710.2634 | 4.2651 | 21.041 | 0 |
| LTC/USD | 1d | momentum_ema_vol | 6 | 33.333 | -2.393 | -39.8894 | 0.9472 | 37.184 | 0 |
| LTC/USD | 1d | rsi_divergence | 1 | 100.0 | 26.27 | 2626.9672 | 0.0 | 0.0 | 0 |
| LTC/USD | 1d | bb_squeeze | 7 | 28.571 | -6.248 | -89.2624 | 0.7531 | 22.732 | 0 |
| LTC/USD | 1d | link_trend | 2 | 50.0 | 3.882 | 194.0969 | 1.4228 | 8.121 | 0 |
| AVAX/USD | 1d | momentum_ema_vol | 6 | 50.0 | 31.897 | 531.6155 | 2.6171 | 16.9 | 0 |
| AVAX/USD | 1d | rsi_divergence | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |
| AVAX/USD | 1d | bb_squeeze | 6 | 33.333 | 2.975 | 49.5825 | 1.1215 | 20.586 | 0 |
| AVAX/USD | 1d | link_trend | 5 | 40.0 | 13.797 | 275.937 | 1.3315 | 15.457 | 0 |
| DOGE/USD | 1d | momentum_ema_vol | 8 | 25.0 | -39.565 | -494.5625 | 0.185 | 43.295 | 0 |
| DOGE/USD | 1d | rsi_divergence | 1 | 100.0 | 5.632 | 563.2383 | 0.0 | 0.0 | 0 |
| DOGE/USD | 1d | bb_squeeze | 6 | 33.333 | 14.377 | 239.6091 | 1.6143 | 18.954 | 0 |
| DOGE/USD | 1d | link_trend | 2 | 100.0 | 45.48 | 2274.0023 | 0.0 | 0.0 | 0 |
