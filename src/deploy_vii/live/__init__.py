"""Capped live model runner: one drawn OpenRouter model per module step, full retention.

No module here calls a model at import time. Every HTTP call goes through an injectable
transport, the key is read only at dispatch time, and spend is bounded by a persisted
reservation ledger. See docs/development/live-runner.md.
"""
