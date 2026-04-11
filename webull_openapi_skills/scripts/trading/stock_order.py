"""Stock order tools for Webull OpenAPI Skill.

Provides: place_stock_order, preview_stock_order, replace_stock_order,
          place_option_single_order, preview_option_order, replace_option_order,
          place_stock_combo_order, place_algo_order.

Note: Uses order_v3 SDK API (OrderOperationV3).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, Optional

try:
    from scripts.errors import ValidationError, handle_sdk_exception
    from scripts.formatters import prepend_disclaimer, extract_response_data, format_order_preview
    from scripts.guards import validate_stock_order, validate_client_order_id
except ImportError:
    from errors import ValidationError, handle_sdk_exception
    from formatters import prepend_disclaimer, extract_response_data, format_order_preview
    from guards import validate_stock_order, validate_client_order_id

if TYPE_CHECKING:
    try:
        from scripts.sdk_client import SDKClient
        from scripts.config import SkillConfig
    except ImportError:
        from sdk_client import SDKClient
        from config import SkillConfig


def _generate_client_order_id() -> str:
    """Generate a unique client order ID if not provided."""
    return str(uuid.uuid4()).replace("-", "")[:32]


def _format_order_result(data: dict) -> str:
    """Format order result to standard format."""
    result = {}
    if "client_order_id" in data:
        result["client_order_id"] = data["client_order_id"]
    if "client_combo_order_id" in data:
        result["client_combo_order_id"] = data["client_combo_order_id"]
    if "combo_order_id" in data:
        result["combo_order_id"] = data["combo_order_id"]
    if "order_id" in data:
        result["order_id"] = data["order_id"]
    if not result:
        return str(data)
    lines = [f"{k}: {v}" for k, v in result.items()]
    return "\n".join(lines)


def _add_optional_str(order: dict, key: str, value: Any) -> None:
    """Add a value to order dict as string if not None."""
    if value is not None:
        order[key] = str(value)


def _build_stock_order(params: dict) -> dict:
    """Build a single stock order dict for the SDK."""
    entrust_type = params["entrust_type"]
    order: dict = {
        "combo_type": "NORMAL",
        "client_order_id": params["coid"],
        "instrument_type": "EQUITY",
        "market": params["market"],
        "symbol": params["symbol"],
        "order_type": params["order_type"],
        "entrust_type": entrust_type,
        "support_trading_session": params["trading_session"],
        "time_in_force": params["time_in_force"],
        "side": params["side"],
    }
    if entrust_type == "AMOUNT" and params.get("total_cash_amount") is not None:
        order["total_cash_amount"] = str(params["total_cash_amount"])
    else:
        order["quantity"] = str(params["quantity"])
    _add_optional_str(order, "limit_price", params.get("limit_price"))
    _add_optional_str(order, "stop_price", params.get("stop_price"))
    if params.get("extended_hours"):
        order["extended_hours"] = params["extended_hours"]
    _add_optional_str(order, "trailing_type", params.get("trailing_type"))
    _add_optional_str(order, "trailing_stop_step", params.get("trailing_stop_step"))
    # HK region fields (broker/institutional)
    if params.get("sender_sub_id"):
        order["sender_sub_id"] = params["sender_sub_id"]
    if params.get("no_party_ids"):
        order["no_party_ids"] = params["no_party_ids"]
    return order


def _build_option_order(
    coid: str, symbol: str, side: str, quantity: int,
    option_type: str, strike_price: float, expiration_date: str,
    order_type: str, time_in_force: str, market: str,
    limit_price: float | None, stop_price: float | None,
) -> dict:
    """Build a single-leg option order dict for the SDK."""
    order: dict = {
        "client_order_id": coid,
        "combo_type": "NORMAL",
        "order_type": order_type,
        "quantity": str(quantity),
        "option_strategy": "SINGLE",
        "side": side,
        "time_in_force": time_in_force,
        "entrust_type": "QTY",
        "legs": [
            {
                "side": side,
                "quantity": str(quantity),
                "symbol": symbol,
                "strike_price": str(strike_price),
                "option_expire_date": expiration_date,
                "instrument_type": "OPTION",
                "option_type": option_type,
                "market": market,
            }
        ],
    }
    _add_optional_str(order, "limit_price", limit_price)
    _add_optional_str(order, "stop_price", stop_price)
    return order


_MODIFY_FIELDS: dict[str, tuple[str, bool]] = {
    "quantity": ("quantity", True),
    "limit_price": ("limit_price", True),
    "stop_price": ("stop_price", True),
    "time_in_force": ("time_in_force", False),
    "expire_date": ("expire_date", False),
    "order_type": ("order_type", False),
    "trailing_type": ("trailing_type", False),
    "trailing_stop_step": ("trailing_stop_step", True),
    "target_vol_percent": ("target_vol_percent", True),
    "max_target_percent": ("max_target_percent", True),
    "algo_start_time": ("algo_start_time", False),
    "algo_end_time": ("algo_end_time", False),
}


def _build_modify_order(order_args: dict) -> dict:
    """Build a modify-order dict from the provided arguments."""
    modify_order: dict = {"client_order_id": order_args["client_order_id"]}
    for key, (out_key, to_str) in _MODIFY_FIELDS.items():
        if key in order_args:
            modify_order[out_key] = str(order_args[key]) if to_str else order_args[key]
    return modify_order


def _collect_replace_args(**kwargs: Any) -> dict:
    """Collect non-None keyword arguments into a dict."""
    return {k: v for k, v in kwargs.items() if v is not None}


# ---------------------------------------------------------------------------
# Stock order tools
# ---------------------------------------------------------------------------

def place_stock_order(
    sdk: "SDKClient",
    config: "SkillConfig",
    symbol: str,
    side: str,
    order_type: str,
    time_in_force: str,
    quantity: Optional[float] = None,
    market: str = "US",
    account_id: Optional[str] = None,
    client_order_id: Optional[str] = None,
    limit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    entrust_type: str = "QTY",
    total_cash_amount: Optional[float] = None,
    trading_session: str = "CORE",
    extended_hours: bool = False,
    trailing_type: Optional[str] = None,
    trailing_stop_step: Optional[float] = None,
    sender_sub_id: Optional[str] = None,
    no_party_ids: Optional[list[dict]] = None,
) -> str:
    """Place a stock order (single, non-combo). For combo orders use place_stock_combo_order.

    Account: stock/option account (Individual Cash, Individual Margin, IRA).
    Call get_account_list first.
    Returns: {client_order_id, order_id}
    """
    # Auto-resolve account_id
    try:
        from scripts.trading.account import resolve_account_id
    except ImportError:
        from trading.account import resolve_account_id

    try:
        account_id = resolve_account_id(sdk, "stock", account_id)
    except ValueError as e:
        return f"Account error: {e}"

    # Validate quantity vs total_cash_amount based on entrust_type
    if entrust_type == "AMOUNT":
        if total_cash_amount is None:
            return "Validation error: total_cash_amount is required when entrust_type=AMOUNT"
    else:
        if quantity is None:
            return "Validation error: quantity is required when entrust_type=QTY"

    params: dict = {
        "symbol": symbol, "side": side, "order_type": order_type,
        "time_in_force": time_in_force, "quantity": quantity,
        "entrust_type": entrust_type, "trading_session": trading_session,
        "market": market,
    }
    if limit_price is not None:
        params["limit_price"] = limit_price
    if stop_price is not None:
        params["stop_price"] = stop_price

    try:
        validate_stock_order(params, config)
    except ValidationError as e:
        return f"Validation error: {e.message}"

    try:
        validate_client_order_id(client_order_id)
    except ValidationError as e:
        return f"Validation error: {e.message}"

    coid = client_order_id or _generate_client_order_id()

    order = _build_stock_order({
        "coid": coid, "market": market, "symbol": symbol, "side": side,
        "order_type": order_type, "time_in_force": time_in_force,
        "entrust_type": entrust_type, "trading_session": trading_session,
        "quantity": quantity, "total_cash_amount": total_cash_amount,
        "limit_price": limit_price, "stop_price": stop_price,
        "extended_hours": extended_hours, "trailing_type": trailing_type,
        "trailing_stop_step": trailing_stop_step,
        "sender_sub_id": sender_sub_id, "no_party_ids": no_party_ids,
    })

    try:
        response = sdk.trade.order_v3.place_order(
            account_id=account_id, new_orders=[order],
        )
        data = extract_response_data(response)
        return prepend_disclaimer(_format_order_result(data if isinstance(data, dict) else {}))
    except Exception as e:
        return handle_sdk_exception(e, "place_stock_order")


def preview_stock_order(
    sdk: "SDKClient",
    account_id: str,
    symbol: str,
    side: str,
    order_type: str,
    time_in_force: str,
    quantity: float,
    market: str = "US",
    limit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    trading_session: str = "CORE",
) -> str:
    """Preview a stock order without submitting. Returns: estimated cost and fees.

    Account: stock/option account (Individual Cash, Individual Margin, IRA).
    """
    order: dict = {
        "client_order_id": _generate_client_order_id(),
        "combo_type": "NORMAL",
        "instrument_type": "EQUITY",
        "market": market,
        "symbol": symbol,
        "order_type": order_type,
        "entrust_type": "QTY",
        "support_trading_session": trading_session,
        "time_in_force": time_in_force,
        "side": side,
        "quantity": str(quantity),
    }
    _add_optional_str(order, "limit_price", limit_price)
    _add_optional_str(order, "stop_price", stop_price)

    try:
        response = sdk.trade.order_v3.preview_order(
            account_id=account_id, preview_orders=[order],
        )
        data = extract_response_data(response)
        return prepend_disclaimer(format_order_preview(data if isinstance(data, dict) else {}))
    except Exception as e:
        return handle_sdk_exception(e, "preview_stock_order")


def replace_stock_order(
    sdk: "SDKClient",
    account_id: str,
    client_order_id: Optional[str] = None,
    quantity: Optional[float] = None,
    limit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    time_in_force: Optional[str] = None,
    order_type: Optional[str] = None,
    expire_date: Optional[str] = None,
    trailing_type: Optional[str] = None,
    trailing_stop_step: Optional[float] = None,
    target_vol_percent: Optional[int] = None,
    max_target_percent: Optional[int] = None,
    algo_start_time: Optional[str] = None,
    algo_end_time: Optional[str] = None,
    orders: Optional[list[dict]] = None,
) -> str:
    """Modify an existing stock order. For combo orders (US): pass orders array.

    Returns: {client_order_id, order_id}
    """
    try:
        validate_client_order_id(client_order_id)
    except ValidationError as e:
        return f"Validation error: {e.message}"

    if orders:
        modify_orders = [_build_modify_order(o) for o in orders]
    else:
        args = _collect_replace_args(
            client_order_id=client_order_id, quantity=quantity,
            limit_price=limit_price, stop_price=stop_price,
            time_in_force=time_in_force, order_type=order_type,
            expire_date=expire_date, trailing_type=trailing_type,
            trailing_stop_step=trailing_stop_step,
            target_vol_percent=target_vol_percent,
            max_target_percent=max_target_percent,
            algo_start_time=algo_start_time, algo_end_time=algo_end_time,
        )
        modify_orders = [_build_modify_order(args)]

    try:
        response = sdk.trade.order_v3.replace_order(
            account_id=account_id, modify_orders=modify_orders,
        )
        data = extract_response_data(response)
        return prepend_disclaimer(_format_order_result(data if isinstance(data, dict) else {}))
    except Exception as e:
        return handle_sdk_exception(e, "replace_stock_order")


# ---------------------------------------------------------------------------
# Single-leg option order tools
# ---------------------------------------------------------------------------

def place_option_single_order(
    sdk: "SDKClient",
    config: "SkillConfig",
    symbol: str,
    side: str,
    quantity: int,
    option_type: str,
    strike_price: float,
    expiration_date: str,
    order_type: str,
    time_in_force: str,
    market: str = "US",
    account_id: Optional[str] = None,
    client_order_id: Optional[str] = None,
    limit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
) -> str:
    """Place a single-leg option order. For multi-leg use place_option_strategy_order.

    Account: stock/option account (Individual Cash, Individual Margin, IRA).
    Call get_account_list first.
    Returns: {client_order_id, order_id}
    """
    try:
        from scripts.trading.account import resolve_account_id
    except ImportError:
        from trading.account import resolve_account_id

    try:
        account_id = resolve_account_id(sdk, "option", account_id)
    except ValueError as e:
        return f"Account error: {e}"

    try:
        validate_client_order_id(client_order_id)
    except ValidationError as e:
        return f"Validation error: {e.message}"

    coid = client_order_id or _generate_client_order_id()

    order = _build_option_order(
        coid=coid, symbol=symbol, side=side, quantity=quantity,
        option_type=option_type, strike_price=strike_price,
        expiration_date=expiration_date, order_type=order_type,
        time_in_force=time_in_force, market=market,
        limit_price=limit_price, stop_price=stop_price,
    )

    try:
        response = sdk.trade.order_v3.place_order(
            account_id=account_id, new_orders=[order],
        )
        data = extract_response_data(response)
        return prepend_disclaimer(_format_order_result(data if isinstance(data, dict) else {}))
    except Exception as e:
        return handle_sdk_exception(e, "place_option_single_order")


def preview_option_order(
    sdk: "SDKClient",
    account_id: str,
    symbol: str,
    side: str,
    quantity: int,
    option_type: str,
    strike_price: float,
    expiration_date: str,
    order_type: str,
    time_in_force: str,
    market: str = "US",
    limit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
) -> str:
    """Preview an option order without submitting. Returns: estimated cost and fees."""
    preview_order: dict = {
        "client_order_id": _generate_client_order_id(),
        "combo_type": "NORMAL",
        "instrument_type": "OPTION",
        "market": market,
        "symbol": symbol,
        "side": side,
        "quantity": str(quantity),
        "option_type": option_type,
        "strike_price": str(strike_price),
        "option_expire_date": expiration_date,
        "order_type": order_type,
        "time_in_force": time_in_force,
        "entrust_type": "QTY",
        "option_strategy": "SINGLE",
    }
    _add_optional_str(preview_order, "limit_price", limit_price)
    _add_optional_str(preview_order, "stop_price", stop_price)

    try:
        response = sdk.trade.order_v3.preview_order(
            account_id=account_id, preview_orders=[preview_order],
        )
        data = extract_response_data(response)
        return prepend_disclaimer(format_order_preview(data if isinstance(data, dict) else {}))
    except Exception as e:
        return handle_sdk_exception(e, "preview_option_order")


def replace_option_order(
    sdk: "SDKClient",
    account_id: str,
    client_order_id: str,
    limit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    quantity: Optional[float] = None,
    time_in_force: Optional[str] = None,
) -> str:
    """Modify an existing option order.

    Returns: {client_order_id, order_id} or
    {client_order_id, client_combo_order_id, combo_order_id, order_id} for strategy orders
    """
    try:
        validate_client_order_id(client_order_id)
    except ValidationError as e:
        return f"Validation error: {e.message}"

    modify_order: dict = {"client_order_id": client_order_id}
    _add_optional_str(modify_order, "limit_price", limit_price)
    _add_optional_str(modify_order, "stop_price", stop_price)
    if quantity is not None:
        modify_order["qty"] = str(quantity)

    try:
        data = sdk.trade.order_v3.replace_order(
            account_id=account_id, modify_orders=[modify_order],
        )
        return prepend_disclaimer(_format_order_result(data))
    except Exception as e:
        return handle_sdk_exception(e, "replace_option_order")


# ---------------------------------------------------------------------------
# Combo order tools
# ---------------------------------------------------------------------------

def _build_combo_leg(order: dict) -> dict:
    """Build a single combo order leg dict."""
    leg: dict = {
        "combo_type": order.get("combo_type", "NORMAL"),
        "instrument_type": order.get("instrument_type", "EQUITY"),
        "market": order.get("market", "US"),
        "symbol": order["symbol"],
        "side": order["side"],
        "order_type": order["order_type"],
        "quantity": str(order["quantity"]),
        "entrust_type": "QTY",
        "time_in_force": order.get("time_in_force", "DAY"),
        "support_trading_session": order.get("support_trading_session", "CORE"),
    }
    if order.get("option_strategy") or order.get("instrument_type") == "OPTION":
        leg["option_strategy"] = order.get("option_strategy", "SINGLE")
    leg["client_order_id"] = order.get("client_order_id") or _generate_client_order_id()
    _add_optional_str(leg, "limit_price", order.get("limit_price"))
    _add_optional_str(leg, "stop_price", order.get("stop_price"))
    return leg


def place_stock_combo_order(
    sdk: "SDKClient",
    account_id: str,
    orders: list[dict],
    client_combo_order_id: Optional[str] = None,
) -> str:
    """[US Only] Place a combo stock order.

    combo_type per leg: NORMAL, MASTER (triggers TP/SL), STOP_PROFIT, STOP_LOSS, OTO, OCO, OTOCO.
    Account: stock/option account. Call get_account_list first.
    Returns: {client_order_id, combo_order_id, order_id}
    """
    combo_id = client_combo_order_id or _generate_client_order_id()
    new_orders = [_build_combo_leg(order) for order in orders]

    try:
        response = sdk.trade.order_v3.place_order(
            account_id=account_id,
            new_orders=new_orders,
            client_combo_order_id=combo_id,
        )
        data = extract_response_data(response)
        return prepend_disclaimer(_format_order_result(data if isinstance(data, dict) else {}))
    except Exception as e:
        return handle_sdk_exception(e, "place_stock_combo_order")


# ---------------------------------------------------------------------------
# Algo order tools
# ---------------------------------------------------------------------------

def place_algo_order(
    sdk: "SDKClient",
    account_id: str,
    symbol: str,
    side: str,
    quantity: float,
    algo_type: str,
    client_order_id: Optional[str] = None,
    order_type: Optional[str] = None,
    limit_price: Optional[float] = None,
    algo_start_time: Optional[str] = None,
    algo_end_time: Optional[str] = None,
    target_vol_percent: Optional[int] = None,
    max_target_percent: Optional[int] = None,
) -> str:
    """[US Only] Place an algorithmic order (TWAP, VWAP, POV).

    Only MARKET and LIMIT order types supported.
    TWAP/VWAP require max_target_percent (1-20). POV requires target_vol_percent (1-20).
    algo_start_time/algo_end_time: US Eastern Time, HH:mm:ss format (e.g. 09:30:00, 16:00:00).
    Returns: {client_order_id, order_id}
    """
    effective_order_type = order_type or "LIMIT"
    if effective_order_type not in ("MARKET", "LIMIT"):
        return f"Validation error: algo orders only support MARKET or LIMIT order_type, got '{effective_order_type}'"

    try:
        validate_client_order_id(client_order_id)
    except ValidationError as e:
        return f"Validation error: {e.message}"

    if algo_type in ("TWAP", "VWAP") and max_target_percent is None:
        return "Validation error: max_target_percent is required for TWAP/VWAP (integer 1-20)"
    if algo_type == "POV" and target_vol_percent is None:
        return "Validation error: target_vol_percent is required for POV (integer 1-20)"

    coid = client_order_id or _generate_client_order_id()

    order: dict = {
        "combo_type": "NORMAL",
        "order_type": effective_order_type,
        "time_in_force": "DAY",
        "support_trading_session": "CORE",
        "instrument_type": "EQUITY",
        "market": "US",
        "symbol": symbol,
        "side": side,
        "quantity": str(quantity),
        "algo_type": algo_type,
        "entrust_type": "QTY",
        "client_order_id": coid,
    }
    _add_optional_str(order, "algo_start_time", algo_start_time)
    _add_optional_str(order, "algo_end_time", algo_end_time)
    _add_optional_str(order, "max_target_percent", max_target_percent)
    _add_optional_str(order, "target_vol_percent", target_vol_percent)
    _add_optional_str(order, "limit_price", limit_price)

    try:
        response = sdk.trade.order_v3.place_order(
            account_id=account_id, new_orders=[order],
        )
        data = extract_response_data(response)
        return prepend_disclaimer(_format_order_result(data if isinstance(data, dict) else {"client_order_id": coid}))
    except Exception as e:
        return handle_sdk_exception(e, "place_algo_order")
