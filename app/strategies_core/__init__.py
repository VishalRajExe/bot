"""Deterministic, testable trading-strategy math for UnboundBot (research layer).

Pure Python/pandas — no exchange, no Freqtrade, no network, no orders. Kept
separate from the live execution path so an untested strategy can never become
actionable implicitly.
"""
