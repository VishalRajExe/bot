"""UnboundBot thin-layer exchange extensions.

These modules run ON TOP of the vendored Freqtrade engine without modifying its
source (no fork, no drift, git-tracked here). They register small, strictly gated
runtime patches to close verified gaps in Freqtrade's handling of our Alpaca PAPER
account. See alpaca_fees for the concrete example.
"""
