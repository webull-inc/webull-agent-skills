"""Runtime shared helpers for production scripts."""

from __future__ import annotations

import logging


def set_sdk_logging(verbose: bool) -> None:
    """Suppress noisy SDK logs unless explicitly requested."""
    if verbose:
        return
    noisy_loggers = [
        "webull.core.client",
        "webull.core.http.initializer.client_initializer",
        "webull.core.http.initializer.token.token_storage",
        "webull.core.http.initializer.token.token_operation",
    ]
    for name in noisy_loggers:
        logging.getLogger(name).setLevel(logging.CRITICAL)
