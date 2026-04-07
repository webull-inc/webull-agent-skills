"""Assets tools for Webull OpenAPI Skill.

Provides: get_account_balance, get_account_positions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

try:
    from scripts.errors import handle_sdk_exception
    from scripts.formatters import (
        extract_response_data,
        format_account_balance,
        format_positions,
        prepend_disclaimer,
    )
except ImportError:
    from errors import handle_sdk_exception
    from formatters import (
        extract_response_data,
        format_account_balance,
        format_positions,
        prepend_disclaimer,
    )

if TYPE_CHECKING:
    try:
        from scripts.sdk_client import SDKClient
    except ImportError:
        from sdk_client import SDKClient


def get_account_balance(sdk: "SDKClient", account_id: str) -> str:
    """Get account balance.

    Returns: net_liquidation, buying_power, cash_balance,
    market_value, unrealized_pnl, realized_pnl.
    """
    try:
        response = sdk.trade.account_v2.get_account_balance(account_id)
        data = extract_response_data(response)
        return prepend_disclaimer(format_account_balance(data))
    except Exception as e:
        return handle_sdk_exception(e, "get_account_balance")


def get_account_positions(sdk: "SDKClient", account_id: str) -> str:
    """Get account positions.

    Returns: symbol, quantity, side, avg_cost, last_price,
    market_value, unrealized_pnl, realized_pnl.
    """
    try:
        response = sdk.trade.account_v2.get_account_position(account_id)
        data = extract_response_data(response)
        return prepend_disclaimer(format_positions(data))
    except Exception as e:
        return handle_sdk_exception(e, "get_account_positions")
