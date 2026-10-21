# Strategy source — authoritative path

The single authoritative strategy file is **`app/user_data/strategies/BtcZScore.py`**.
That is what Freqtrade actually loads: `run_paper.py` and the research launcher start
`freqtrade trade/backtesting` with `--userdir app/user_data` and **no** `--strategy-path`,
so Freqtrade resolves strategies from `<userdir>/strategies`.

This `app/strategies/` directory previously held a byte-identical duplicate that no
config referenced (drift risk). It was removed (audit 2026-10-21, TASK 4). Do **not**
re-add a copy here — edit the authoritative file under `app/user_data/strategies/`.
