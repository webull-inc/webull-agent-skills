#!/usr/bin/env python3
"""Webull trade operations with optional dry-run and configurable risk guard."""

from __future__ import annotations

import argparse
import copy
import json
import sys
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from webull.core.client import ApiClient
from webull.trade.trade_client import TradeClient

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

try:
    from scripts.webull_env_router import resolve_openapi_host
    from scripts.webull_profiles import (
        CredentialConfigError,
        choose_default_profile,
        expand_selector,
        get_profile,
        make_custom_profile,
    )
    from scripts.webull_runtime import set_sdk_logging
except ModuleNotFoundError:  # running as plain script from scripts/
    from webull_env_router import resolve_openapi_host
    from webull_profiles import CredentialConfigError, choose_default_profile, expand_selector, get_profile, make_custom_profile
    from webull_runtime import set_sdk_logging


ACTION_CHOICES = [
    "local-check",
    "preview",
    "place",
    "batch-place",
    "replace",
    "cancel",
    "option-preview",
    "option-place",
    "option-replace",
    "option-cancel",
    "detail",
    "open",
    "history",
    "account-list",
    "balance",
    "position",
]


DEFAULT_POLICY: Dict[str, Any] = {
    "global": {
        "max_orders_per_request": 10,
        "allowed_instrument_types": ["EQUITY", "OPTION", "FUTURES", "CRYPTO", "EVENT"],
        "allowed_sides": ["BUY", "SELL"],
        "require_client_order_id": True,
        "auto_generate_client_order_id": True,
        "enforce_unique_client_order_id": True,
    },
    "live": {
        # Fail-closed defaults.
        "enabled": True,
        "require_confirm_live": True,
        "require_preview_before_live": True,
        "allowed_endpoints": [],
    },
    "instruments": {
        "EQUITY": {
            "allowed_order_types": ["MARKET", "LIMIT", "STOP_LOSS", "STOP_LOSS_LIMIT"],
            "allowed_tif": ["DAY", "GTC", "IOC"],
        },
        "OPTION": {
            "allowed_order_types": ["MARKET", "LIMIT", "STOP_LOSS", "STOP_LOSS_LIMIT"],
            "allowed_tif": ["DAY", "GTC"],
            "allowed_option_strategies": ["SINGLE", "COVERED_STOCK"],
        },
        "FUTURES": {
            "allowed_order_types": ["MARKET", "LIMIT", "STOP_LOSS", "STOP_LOSS_LIMIT", "TRAILING_STOP_LOSS"],
            "allowed_tif": ["DAY", "GTC"],
            "disallow_combo": True,
        },
        "CRYPTO": {
            "allowed_order_types": ["MARKET", "LIMIT", "STOP_LOSS_LIMIT"],
            "allowed_tif": ["DAY", "GTC", "IOC"],
            "min_order_notional": "1",
            "max_order_notional": "100000",
            "max_pending_buy_notional": "200000",
            "enforce_pending_buy_notional": False,
            "min_quantity": "0.00000001",
        },
        "EVENT": {
            "allowed_order_types": ["LIMIT"],
            "allowed_tif": ["DAY"],
            "max_quantity": "50000",
            "prohibit_sell_to_open": True,
        },
    },
}


@dataclass
class ApiResult:
    ok: bool
    status_code: Optional[int]
    detail: str
    payload: Any


class PolicyLoadError(ValueError):
    """Raised when risk policy loading/parsing/validation fails."""


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_local_or_project_path(raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    if candidate.exists():
        return candidate.resolve()
    return (_project_root() / candidate).resolve()


def _decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _safe_json(response: Any) -> Any:
    try:
        return response.json()
    except Exception:
        return None


def _merge_dict(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _format_yaml_parse_error(exc: Exception) -> str:
    problem = getattr(exc, "problem", "")
    context = getattr(exc, "context", "")
    mark = getattr(exc, "problem_mark", None)
    detail_parts = [part for part in [context, problem] if part]
    detail = "; ".join(detail_parts) if detail_parts else str(exc)
    if mark is not None:
        detail = f"{detail} (line {mark.line + 1}, column {mark.column + 1})"
    return detail


def _policy_error(policy_file: str, message: str) -> PolicyLoadError:
    return PolicyLoadError(f"Risk policy error ({policy_file}): {message}")


def _expect_dict(value: Any, policy_file: str, path: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise _policy_error(policy_file, f"'{path}' must be an object/map, got {type(value).__name__}.")
    return value


def _expect_bool(value: Any, policy_file: str, path: str) -> bool:
    if not isinstance(value, bool):
        raise _policy_error(policy_file, f"'{path}' must be a boolean, got {type(value).__name__}.")
    return value


def _expect_positive_int(value: Any, policy_file: str, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise _policy_error(policy_file, f"'{path}' must be a positive integer, got {value!r}.")
    return value


def _expect_str_list(value: Any, policy_file: str, path: str) -> List[str]:
    if not isinstance(value, list):
        raise _policy_error(policy_file, f"'{path}' must be a string array, got {type(value).__name__}.")
    bad_items = [item for item in value if not isinstance(item, str) or not item.strip()]
    if bad_items:
        raise _policy_error(policy_file, f"'{path}' contains invalid item(s): {bad_items!r}.")
    return value


def _expect_positive_decimal(value: Any, policy_file: str, path: str) -> Decimal:
    dec = _decimal(value)
    if dec is None or dec <= 0:
        raise _policy_error(policy_file, f"'{path}' must be a positive decimal, got {value!r}.")
    return dec


def _validate_policy(policy: Dict[str, Any], policy_file: str) -> None:
    top = _expect_dict(policy, policy_file, "root")

    global_cfg = _expect_dict(top.get("global"), policy_file, "global")
    _expect_positive_int(global_cfg.get("max_orders_per_request"), policy_file, "global.max_orders_per_request")
    _expect_str_list(global_cfg.get("allowed_instrument_types"), policy_file, "global.allowed_instrument_types")
    _expect_str_list(global_cfg.get("allowed_sides"), policy_file, "global.allowed_sides")
    _expect_bool(global_cfg.get("require_client_order_id"), policy_file, "global.require_client_order_id")
    _expect_bool(global_cfg.get("auto_generate_client_order_id"), policy_file, "global.auto_generate_client_order_id")
    _expect_bool(global_cfg.get("enforce_unique_client_order_id"), policy_file, "global.enforce_unique_client_order_id")

    live_cfg = _expect_dict(top.get("live"), policy_file, "live")
    _expect_bool(live_cfg.get("enabled"), policy_file, "live.enabled")
    _expect_bool(live_cfg.get("require_confirm_live"), policy_file, "live.require_confirm_live")
    _expect_bool(live_cfg.get("require_preview_before_live"), policy_file, "live.require_preview_before_live")
    _expect_str_list(live_cfg.get("allowed_endpoints"), policy_file, "live.allowed_endpoints")

    instruments = _expect_dict(top.get("instruments"), policy_file, "instruments")
    required_instruments = ["EQUITY", "OPTION", "FUTURES", "CRYPTO", "EVENT"]
    for inst_name in required_instruments:
        if inst_name not in instruments:
            raise _policy_error(policy_file, f"'instruments.{inst_name}' is required.")
        inst_cfg = _expect_dict(instruments.get(inst_name), policy_file, f"instruments.{inst_name}")
        _expect_str_list(inst_cfg.get("allowed_order_types"), policy_file, f"instruments.{inst_name}.allowed_order_types")
        _expect_str_list(inst_cfg.get("allowed_tif"), policy_file, f"instruments.{inst_name}.allowed_tif")

    option_cfg = _expect_dict(instruments.get("OPTION"), policy_file, "instruments.OPTION")
    _expect_str_list(option_cfg.get("allowed_option_strategies"), policy_file, "instruments.OPTION.allowed_option_strategies")

    futures_cfg = _expect_dict(instruments.get("FUTURES"), policy_file, "instruments.FUTURES")
    _expect_bool(futures_cfg.get("disallow_combo"), policy_file, "instruments.FUTURES.disallow_combo")

    crypto_cfg = _expect_dict(instruments.get("CRYPTO"), policy_file, "instruments.CRYPTO")
    min_notional = _expect_positive_decimal(
        crypto_cfg.get("min_order_notional"), policy_file, "instruments.CRYPTO.min_order_notional"
    )
    max_notional = _expect_positive_decimal(
        crypto_cfg.get("max_order_notional"), policy_file, "instruments.CRYPTO.max_order_notional"
    )
    if min_notional > max_notional:
        raise _policy_error(
            policy_file,
            "'instruments.CRYPTO.min_order_notional' must be <= 'instruments.CRYPTO.max_order_notional'.",
        )
    _expect_positive_decimal(
        crypto_cfg.get("max_pending_buy_notional"), policy_file, "instruments.CRYPTO.max_pending_buy_notional"
    )
    _expect_bool(
        crypto_cfg.get("enforce_pending_buy_notional"), policy_file, "instruments.CRYPTO.enforce_pending_buy_notional"
    )
    _expect_positive_decimal(crypto_cfg.get("min_quantity"), policy_file, "instruments.CRYPTO.min_quantity")

    event_cfg = _expect_dict(instruments.get("EVENT"), policy_file, "instruments.EVENT")
    _expect_positive_decimal(event_cfg.get("max_quantity"), policy_file, "instruments.EVENT.max_quantity")
    _expect_bool(event_cfg.get("prohibit_sell_to_open"), policy_file, "instruments.EVENT.prohibit_sell_to_open")


def load_policy(policy_file: Optional[str]) -> Dict[str, Any]:
    if not policy_file:
        raise PolicyLoadError("Risk policy error: --policy-file is required.")

    path = _resolve_local_or_project_path(policy_file)
    path_str = str(path)
    if not path.exists():
        raise _policy_error(path_str, "file does not exist.")
    if not path.is_file():
        raise _policy_error(path_str, "path is not a file.")

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        raise _policy_error(path_str, f"cannot read file: {exc}") from exc

    try:
        if yaml is not None:
            loaded = yaml.safe_load(text)
        else:
            loaded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _policy_error(
            path_str,
            (
                f"parse failed at line {exc.lineno}, column {exc.colno}: {exc.msg}. "
                "PyYAML is unavailable, so only JSON syntax is accepted."
            ),
        ) from exc
    except Exception as exc:
        if yaml is not None:
            detail = _format_yaml_parse_error(exc)
            raise _policy_error(path_str, f"YAML parse failed: {detail}") from exc
        raise _policy_error(path_str, f"parse failed: {exc}") from exc

    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise _policy_error(path_str, f"top-level must be an object/map, got {type(loaded).__name__}.")

    policy = _merge_dict(DEFAULT_POLICY, loaded)
    _validate_policy(policy, path_str)
    return policy


def action_requires_orders(action: str) -> bool:
    return action in {
        "local-check",
        "preview",
        "place",
        "batch-place",
        "replace",
        "option-preview",
        "option-place",
        "option-replace",
    }


def action_mutates_with_orders(action: str) -> bool:
    return action in {"place", "batch-place", "replace", "option-place", "option-replace"}


def action_is_mutating(action: str) -> bool:
    return action in {"place", "batch-place", "replace", "cancel", "option-place", "option-replace", "option-cancel"}


def action_requires_account(action: str) -> bool:
    return action in {
        "preview",
        "place",
        "batch-place",
        "replace",
        "cancel",
        "option-preview",
        "option-place",
        "option-replace",
        "option-cancel",
        "detail",
        "open",
        "history",
        "balance",
        "position",
    }


def action_requires_client_order_id(action: str) -> bool:
    return action in {"cancel", "detail", "option-cancel"}


def load_orders_if_needed(action: str, order_json: str, order_file: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    if not action_requires_orders(action):
        return [], None
    if not order_json and not order_file:
        raise ValueError(f"Action '{action}' requires --order-json or --order-file.")
    if order_json and order_file:
        raise ValueError("Use only one of --order-json or --order-file.")

    source_label = "--order-json"
    raw = order_json
    if order_file:
        source_label = f"--order-file ({order_file})"
        try:
            raw = Path(order_file).read_text(encoding="utf-8")
        except Exception as exc:
            raise ValueError(f"Failed to read order file '{order_file}': {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid order JSON from {source_label}: line {exc.lineno}, column {exc.colno}: {exc.msg}."
        ) from exc

    client_combo_order_id: Optional[str] = None
    if isinstance(payload, list):
        orders = payload
    elif isinstance(payload, dict):
        if "new_orders" in payload:
            orders = payload["new_orders"]
            client_combo_order_id = payload.get("client_combo_order_id")
        elif "batch_orders" in payload:
            orders = payload["batch_orders"]
        elif "modify_orders" in payload:
            orders = payload["modify_orders"]
            client_combo_order_id = payload.get("client_combo_order_id")
        else:
            orders = [payload]
    else:
        raise ValueError("Order payload must be a JSON object or array.")

    if not isinstance(orders, list) or not orders:
        raise ValueError("Order payload must contain at least one order.")
    for item in orders:
        if not isinstance(item, dict):
            raise ValueError("Each order must be a JSON object.")
    return orders, client_combo_order_id


def normalize_orders(
    orders: List[Dict[str, Any]],
    policy: Dict[str, Any],
    default_instrument_type: str = "EQUITY",
    require_explicit_client_order_id: bool = False,
    allow_default_instrument_type: bool = True,
    allow_default_market: bool = True,
) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
    violations: List[str] = []
    warnings: List[str] = []
    normalized = copy.deepcopy(orders)
    seen_ids = set()

    global_cfg = policy.get("global", {})
    require_client_order_id = bool(global_cfg.get("require_client_order_id", True)) or require_explicit_client_order_id
    auto_generate = bool(global_cfg.get("auto_generate_client_order_id", True)) and not require_explicit_client_order_id
    enforce_unique = bool(global_cfg.get("enforce_unique_client_order_id", True))
    max_orders = int(global_cfg.get("max_orders_per_request", 10))

    if len(normalized) > max_orders:
        violations.append(f"Too many orders in one request: {len(normalized)} > {max_orders}")

    for idx, order in enumerate(normalized):
        order.setdefault("combo_type", "NORMAL")
        if allow_default_market:
            order.setdefault("market", "US")

        client_order_id = str(order.get("client_order_id", "")).strip()
        if not client_order_id:
            if require_client_order_id and not auto_generate:
                if require_explicit_client_order_id:
                    violations.append(f"Order[{idx}] missing client_order_id (explicit value required for live mutating action).")
                else:
                    violations.append(f"Order[{idx}] missing client_order_id")
            elif auto_generate:
                new_id = uuid.uuid4().hex
                order["client_order_id"] = new_id
                client_order_id = new_id
                warnings.append(f"Order[{idx}] missing client_order_id, auto-generated.")
        if client_order_id and enforce_unique:
            if client_order_id in seen_ids:
                violations.append(f"Duplicate client_order_id detected: {client_order_id}")
            seen_ids.add(client_order_id)

        inst_raw = order.get("instrument_type")
        if (inst_raw is None or (isinstance(inst_raw, str) and not inst_raw.strip())) and allow_default_instrument_type:
            order["instrument_type"] = default_instrument_type
        if "instrument_type" in order and order["instrument_type"] is not None:
            order["instrument_type"] = str(order["instrument_type"]).upper()
        if "market" in order and order["market"] is not None:
            order["market"] = str(order["market"]).upper()
        if "side" in order and order["side"] is not None:
            order["side"] = str(order["side"]).upper()
        if "order_type" in order and order["order_type"] is not None:
            order["order_type"] = str(order["order_type"]).upper()
        if "time_in_force" in order and order["time_in_force"] is not None:
            order["time_in_force"] = str(order["time_in_force"]).upper()
        if "option_strategy" in order and order["option_strategy"] is not None:
            order["option_strategy"] = str(order["option_strategy"]).upper()
        if "combo_type" in order and order["combo_type"] is not None:
            order["combo_type"] = str(order["combo_type"]).upper()

        if order["instrument_type"] == "EQUITY" and "support_trading_session" not in order:
            order["support_trading_session"] = "N"
            warnings.append(f"Order[{idx}] missing support_trading_session, defaulted to 'N'.")

    return normalized, violations, warnings


def _has_non_empty_field(order: Dict[str, Any], field: str) -> bool:
    value = order.get(field)
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def validate_order_payload(orders: List[Dict[str, Any]], action: str) -> List[str]:
    violations: List[str] = []

    required_common = ("instrument_type", "market", "symbol", "side", "order_type")
    quantity_required_actions = {"preview", "place", "batch-place", "option-preview", "option-place"}
    replace_actions = {"replace", "option-replace"}
    price_checked_actions = quantity_required_actions | replace_actions

    for idx, order in enumerate(orders):
        for field in required_common:
            if not _has_non_empty_field(order, field):
                violations.append(f"Order[{idx}] missing required field '{field}'.")

        if action in quantity_required_actions and not _has_non_empty_field(order, "quantity"):
            violations.append(f"Order[{idx}] missing required field 'quantity' for action '{action}'.")

        if action in price_checked_actions:
            order_type = str(order.get("order_type", "")).upper()
            limit_price = _decimal(order.get("limit_price"))
            stop_price = _decimal(order.get("stop_price"))
            trailing_amount = _decimal(order.get("trailing_amount"))
            trailing_percent = _decimal(order.get("trailing_percent"))

            if order_type == "LIMIT":
                if limit_price is None or limit_price <= 0:
                    violations.append(f"Order[{idx}] LIMIT order requires 'limit_price' > 0.")
            elif order_type == "STOP_LOSS":
                if stop_price is None or stop_price <= 0:
                    violations.append(f"Order[{idx}] STOP_LOSS order requires 'stop_price' > 0.")
            elif order_type == "STOP_LOSS_LIMIT":
                if stop_price is None or stop_price <= 0:
                    violations.append(f"Order[{idx}] STOP_LOSS_LIMIT order requires 'stop_price' > 0.")
                if limit_price is None or limit_price <= 0:
                    violations.append(f"Order[{idx}] STOP_LOSS_LIMIT order requires 'limit_price' > 0.")
            elif order_type == "TRAILING_STOP_LOSS":
                has_positive_trailing = (
                    (trailing_amount is not None and trailing_amount > 0)
                    or (trailing_percent is not None and trailing_percent > 0)
                )
                if not has_positive_trailing and (stop_price is None or stop_price <= 0):
                    violations.append(
                        f"Order[{idx}] TRAILING_STOP_LOSS requires trailing_amount>0 or trailing_percent>0 or stop_price>0."
                    )

    return violations


def _compute_order_notional(order: Dict[str, Any]) -> Optional[Decimal]:
    qty = _decimal(order.get("quantity"))
    if qty is None:
        return None
    price = _decimal(order.get("limit_price"))
    if price is None:
        price = _decimal(order.get("stop_price"))
    if price is None:
        return None
    return qty * price


def evaluate_risk(
    orders: List[Dict[str, Any]],
    policy: Dict[str, Any],
    action: str,
    endpoint: str,
    pending_crypto_buy_notional: Optional[Decimal] = None,
) -> Tuple[List[str], List[str], Dict[str, Any]]:
    violations: List[str] = []
    warnings: List[str] = []
    metrics: Dict[str, Any] = {"order_count": len(orders), "action": action}

    global_cfg = policy.get("global", {})
    allowed_instrument_types = set(global_cfg.get("allowed_instrument_types", []))
    allowed_sides = set(global_cfg.get("allowed_sides", []))

    live_cfg = policy.get("live", {})
    if action in {"place", "batch-place", "replace", "cancel", "option-place", "option-replace", "option-cancel"}:
        if not bool(live_cfg.get("enabled", True)):
            violations.append("Live mutating actions are disabled by risk policy.")
        allowed_endpoints = set(live_cfg.get("allowed_endpoints", []))
        if allowed_endpoints and endpoint not in allowed_endpoints:
            violations.append(f"Endpoint '{endpoint}' is not allowed for mutating actions.")

    for idx, order in enumerate(orders):
        inst = str(order.get("instrument_type", "")).upper()
        side = str(order.get("side", "")).upper()
        order_type = str(order.get("order_type", "")).upper()
        tif = str(order.get("time_in_force", "")).upper()
        combo = str(order.get("combo_type", "NORMAL")).upper()
        qty = _decimal(order.get("quantity"))

        if inst not in allowed_instrument_types:
            violations.append(f"Order[{idx}] instrument_type '{inst}' is not allowed.")
            continue
        if side and side not in allowed_sides:
            violations.append(f"Order[{idx}] side '{side}' is not allowed.")

        if action in {"preview", "place"} and (qty is None or qty <= 0):
            violations.append(f"Order[{idx}] quantity must be > 0 for action '{action}'.")
        if action == "replace" and qty is not None and qty <= 0:
            violations.append(f"Order[{idx}] quantity must be > 0 when provided in replace.")

        inst_cfg = policy.get("instruments", {}).get(inst, {})
        if inst_cfg:
            allowed_order_types = set(inst_cfg.get("allowed_order_types", []))
            if order_type and allowed_order_types and order_type not in allowed_order_types:
                violations.append(f"Order[{idx}] order_type '{order_type}' not allowed for {inst}.")

            allowed_tif = set(inst_cfg.get("allowed_tif", []))
            if tif and allowed_tif and tif not in allowed_tif:
                violations.append(f"Order[{idx}] time_in_force '{tif}' not allowed for {inst}.")

        if inst == "FUTURES":
            if bool(inst_cfg.get("disallow_combo", False)) and combo != "NORMAL":
                violations.append(f"Order[{idx}] FUTURES does not allow combo_type '{combo}'.")

        if inst == "OPTION":
            strategy = str(order.get("option_strategy", "")).upper()
            allowed_strategies = set(inst_cfg.get("allowed_option_strategies", []))
            if strategy and allowed_strategies and strategy not in allowed_strategies:
                violations.append(f"Order[{idx}] option_strategy '{strategy}' is not allowed.")

        if inst == "CRYPTO":
            min_qty = _decimal(inst_cfg.get("min_quantity"))
            if min_qty is not None and qty is not None and qty < min_qty:
                violations.append(f"Order[{idx}] CRYPTO quantity {qty} < min_quantity {min_qty}.")

            if action in {"preview", "place"}:
                notional = _compute_order_notional(order)
                if notional is not None:
                    min_notional = _decimal(inst_cfg.get("min_order_notional"))
                    max_notional = _decimal(inst_cfg.get("max_order_notional"))
                    if min_notional is not None and notional < min_notional:
                        violations.append(f"Order[{idx}] CRYPTO notional {notional} < min_order_notional {min_notional}.")
                    if max_notional is not None and notional > max_notional:
                        violations.append(f"Order[{idx}] CRYPTO notional {notional} > max_order_notional {max_notional}.")
                elif order_type != "MARKET":
                    warnings.append(f"Order[{idx}] could not compute CRYPTO notional from price fields.")

                enforce_pending = bool(inst_cfg.get("enforce_pending_buy_notional", False))
                max_pending = _decimal(inst_cfg.get("max_pending_buy_notional"))
                if enforce_pending and side == "BUY" and max_pending is not None and pending_crypto_buy_notional is not None:
                    delta = notional or Decimal("0")
                    total = pending_crypto_buy_notional + delta
                    metrics["pending_crypto_buy_notional_before"] = str(pending_crypto_buy_notional)
                    metrics["pending_crypto_buy_notional_after"] = str(total)
                    if total > max_pending:
                        violations.append(f"CRYPTO pending buy notional {total} > max_pending_buy_notional {max_pending}.")

        if inst == "EVENT":
            max_qty = _decimal(inst_cfg.get("max_quantity"))
            if max_qty is not None and qty is not None and qty > max_qty:
                violations.append(f"Order[{idx}] EVENT quantity {qty} > max_quantity {max_qty}.")

            prohibit_sell_to_open = bool(inst_cfg.get("prohibit_sell_to_open", True))
            position_effect = str(order.get("position_effect", "")).upper()
            if prohibit_sell_to_open and side == "SELL" and position_effect in {"OPEN", "SELL_TO_OPEN"}:
                violations.append(f"Order[{idx}] EVENT sell-to-open is prohibited.")

    return violations, warnings, metrics


def _call_api(name: str, fn) -> ApiResult:
    try:
        resp = fn()
        code = getattr(resp, "status_code", None)
        payload = _safe_json(resp)
        if code == 200:
            return ApiResult(ok=True, status_code=code, detail="ok", payload=payload)
        message = None
        if isinstance(payload, dict):
            message = payload.get("message") or payload.get("msg") or payload.get("error_code")
        return ApiResult(ok=False, status_code=code, detail=message or f"{name} failed", payload=payload)
    except Exception as exc:  # pragma: no cover
        return ApiResult(ok=False, status_code=None, detail=str(exc), payload=None)


def _collect_account_candidates(payload: Any) -> List[Dict[str, str]]:
    collected: List[Dict[str, str]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            account_id_raw = node.get("account_id", node.get("accountId"))
            account_id = str(account_id_raw).strip() if account_id_raw is not None else ""
            if account_id:
                candidate: Dict[str, str] = {"account_id": account_id}
                field_aliases = {
                    "user_id": "user_id",
                    "userId": "user_id",
                    "open_id": "open_id",
                    "openId": "open_id",
                    "account_type": "account_type",
                    "accountType": "account_type",
                    "account_category": "account_category",
                    "accountCategory": "account_category",
                    "account_status": "account_status",
                    "accountStatus": "account_status",
                    "currency": "currency",
                    "base_currency": "currency",
                    "baseCurrency": "currency",
                }
                for src, dest in field_aliases.items():
                    value = node.get(src)
                    if value is None:
                        continue
                    normalized = str(value).strip()
                    if normalized:
                        candidate.setdefault(dest, normalized)
                collected.append(candidate)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)

    dedup: Dict[str, Dict[str, str]] = {}
    order: List[str] = []
    for candidate in collected:
        account_id = candidate["account_id"]
        if account_id not in dedup:
            dedup[account_id] = dict(candidate)
            order.append(account_id)
            continue
        for key, value in candidate.items():
            if key not in dedup[account_id] and value:
                dedup[account_id][key] = value
    return [dedup[account_id] for account_id in order]


def _format_account_candidate(candidate: Dict[str, str]) -> str:
    parts = [f"account_id={candidate.get('account_id', '')}"]
    for key in ("user_id", "open_id", "account_type", "account_category", "account_status", "currency"):
        value = candidate.get(key, "")
        if value:
            parts.append(f"{key}={value}")
    return ", ".join(parts)


def _prompt_select_account_id(candidates: List[Dict[str, str]]) -> Tuple[str, str]:
    if len(candidates) == 1:
        return candidates[0]["account_id"], "account_list_single"

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        candidate_ids = ", ".join(c["account_id"] for c in candidates)
        raise ValueError(
            "Multiple accounts found. Non-interactive mode cannot prompt for selection. "
            f"Please pass --account-id explicitly. Candidates: {candidate_ids}"
        )

    print("Multiple accounts found. Please select one account:", file=sys.stderr)
    for idx, candidate in enumerate(candidates, start=1):
        print(f"  [{idx}] {_format_account_candidate(candidate)}", file=sys.stderr)

    while True:
        try:
            raw = input("Select account number: ").strip()
        except EOFError as exc:
            raise ValueError("No input received while selecting account.") from exc
        if raw.isdigit():
            selected = int(raw)
            if 1 <= selected <= len(candidates):
                return candidates[selected - 1]["account_id"], "account_list_selected_interactive"
        print(f"Invalid selection '{raw}'. Enter a number between 1 and {len(candidates)}.", file=sys.stderr)


def _iter_order_like(payload: Any):
    if isinstance(payload, dict):
        keys = set(payload.keys())
        if {"instrument_type", "side"} & keys:
            yield payload
        for value in payload.values():
            yield from _iter_order_like(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _iter_order_like(item)


def _fetch_pending_crypto_buy_notional(trade_client: TradeClient, account_id: str) -> Optional[Decimal]:
    response = _call_api("trade.get_order_open", lambda: trade_client.order_v3.get_order_open(account_id, page_size=50))
    if not response.ok:
        return None
    total = Decimal("0")
    for order in _iter_order_like(response.payload):
        inst = str(order.get("instrument_type", "")).upper()
        side = str(order.get("side", "")).upper()
        if inst != "CRYPTO" or side != "BUY":
            continue
        notional = _compute_order_notional(order)
        if notional is not None:
            total += notional
    return total


def resolve_account_id(
    trade_client: TradeClient, explicit_account_id: str, account_id_hint: str
) -> Tuple[str, str, ApiResult, List[Dict[str, str]]]:
    if explicit_account_id:
        return explicit_account_id, "input", ApiResult(ok=True, status_code=200, detail="input", payload=None), []
    if account_id_hint:
        return account_id_hint, "profile_hint", ApiResult(ok=True, status_code=200, detail="profile_hint", payload=None), []

    account_list = _call_api("trade.get_account_list", lambda: trade_client.account_v2.get_account_list())
    if not account_list.ok:
        return "", "none", account_list, []
    candidates = _collect_account_candidates(account_list.payload)
    if not candidates:
        return "", "none", ApiResult(
            ok=False,
            status_code=account_list.status_code,
            detail="Could not resolve account_id from account list response.",
            payload=account_list.payload,
        ), []
    try:
        account_id, source = _prompt_select_account_id(candidates)
    except ValueError as exc:
        return "", "none", ApiResult(
            ok=False,
            status_code=account_list.status_code,
            detail=str(exc),
            payload=account_list.payload,
        ), candidates
    return account_id, source, account_list, candidates


def _action_from_mode(mode: str) -> str:
    if mode == "local":
        return "local-check"
    if mode == "preview":
        return "preview"
    if mode == "live":
        return "place"
    raise ValueError(f"Unsupported mode: {mode}")


def _dedup_str_list(values: List[str]) -> List[str]:
    deduped: List[str] = []
    seen = set()
    for item in values:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def _collect_status_strings(payload: Any) -> List[str]:
    status_keys = {
        "status",
        "order_status",
        "orderState",
        "order_state",
        "entrust_status",
        "state",
        "exec_status",
        "execution_status",
    }
    values: List[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, (dict, list)):
                    walk(value)
                    continue
                if isinstance(value, str):
                    key_l = str(key).lower()
                    if key in status_keys or "status" in key_l or key_l.endswith("_state") or key_l == "state":
                        values.append(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return _dedup_str_list(values)


def _status_category(raw: str) -> str:
    normalized = str(raw or "").strip().upper().replace("-", "_").replace(" ", "_")
    if not normalized:
        return "unknown"

    rejected_tokens = {"REJECT", "FAIL", "ERROR", "INVALID", "EXPIRE"}
    cancelled_tokens = {"CANCEL", "CANCELED", "CANCELLED"}
    filled_tokens = {"FILLED", "DONE", "COMPLETED", "EXECUTED"}
    partial_tokens = {"PARTIAL"}
    pending_tokens = {"NEW", "PENDING", "SUBMIT", "OPEN", "WORKING", "QUEUE", "ACCEPT", "ACTIVE", "TRIGGER"}

    if any(token in normalized for token in rejected_tokens):
        return "rejected"
    if any(token in normalized for token in partial_tokens):
        return "partial_fill"
    if any(token in normalized for token in filled_tokens):
        return "filled"
    if any(token in normalized for token in pending_tokens):
        return "pending"
    if any(token in normalized for token in cancelled_tokens):
        return "cancelled"
    return "unknown"


def _derive_business_status(action: str, statuses: List[str], query_ok: bool) -> str:
    if not query_ok:
        return "unknown"
    if not statuses:
        return "unknown"

    categories = {_status_category(status) for status in statuses}
    is_cancel_action = action in {"cancel", "option-cancel"}

    if "rejected" in categories:
        return "failure"
    if is_cancel_action:
        if "cancelled" in categories:
            return "success"
        if "pending" in categories:
            return "pending"
        if "filled" in categories or "partial_fill" in categories:
            return "failure"
        return "unknown"

    if "cancelled" in categories:
        return "failure"
    if "pending" in categories:
        return "pending"
    if "partial_fill" in categories:
        return "partial_fill"
    if "filled" in categories:
        return "success"
    return "unknown"


def _extract_order_ids_for_post_check(action: str, normalized_orders: List[Dict[str, Any]], client_order_id: str) -> List[str]:
    ids: List[str] = []
    if action in {"cancel", "option-cancel"} and client_order_id:
        ids.append(client_order_id)
    for order in normalized_orders:
        value = str(order.get("client_order_id", "")).strip()
        if value:
            ids.append(value)
    return _dedup_str_list(ids)


def _fetch_order_detail_for_post_check(
    trade_client: TradeClient, action: str, account_id: str, order_client_id: str
) -> ApiResult:
    if action.startswith("option-"):
        return _call_api(
            "trade.get_option_order_detail",
            lambda: trade_client.order_v2.get_order_detail(account_id, order_client_id),
        )
    return _call_api(
        "trade.get_order_detail",
        lambda: trade_client.order_v3.get_order_detail(account_id, order_client_id),
    )


def _run_post_trade_check(
    trade_client: TradeClient,
    action: str,
    account_id: str,
    order_client_ids: List[str],
) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    outcomes: List[str] = []

    for oid in order_client_ids:
        detail = _fetch_order_detail_for_post_check(trade_client, action, account_id, oid)
        statuses = _collect_status_strings(detail.payload)
        business_status = _derive_business_status(action, statuses, detail.ok)
        outcomes.append(business_status)
        checks.append(
            {
                "client_order_id": oid,
                "query_ok": detail.ok,
                "query_status_code": detail.status_code,
                "query_detail": detail.detail,
                "observed_statuses": statuses,
                "business_status": business_status,
                "payload": detail.payload,
            }
        )

    failed_checks = sum(1 for check in checks if not check["query_ok"])
    known_orders = sum(1 for outcome in outcomes if outcome != "unknown")

    if not outcomes:
        final_outcome = "unknown"
    elif "failure" in outcomes:
        final_outcome = "failure"
    elif "pending" in outcomes:
        final_outcome = "pending"
    elif "partial_fill" in outcomes:
        final_outcome = "partial_fill"
    elif all(outcome == "success" for outcome in outcomes):
        final_outcome = "success"
    else:
        final_outcome = "unknown"

    return {
        "attempted": True,
        "account_id": account_id,
        "checked_order_count": len(checks),
        "orders": checks,
        "summary": {
            "outcome": final_outcome,
            "is_success": final_outcome == "success",
            "is_failure": final_outcome == "failure",
            "is_final": final_outcome in {"success", "failure"},
            "requires_follow_up": final_outcome in {"pending", "partial_fill", "unknown"},
            "failed_checks": failed_checks,
            "known_status_orders": known_orders,
        },
    }


def _finalize_trade_result(result: Dict[str, Any]) -> Dict[str, Any]:
    result["ok"] = bool(result.get("allow"))
    return result


def _run_required_preview_before_live(
    trade_client: TradeClient,
    action: str,
    account_id: str,
    normalized_orders: List[Dict[str, Any]],
    client_combo_order_id: Optional[str],
) -> Optional[ApiResult]:
    if action in {"place", "batch-place"}:
        return _call_api(
            "trade.preview_order",
            lambda: trade_client.order_v3.preview_order(
                account_id,
                normalized_orders,
                client_combo_order_id=client_combo_order_id,
            ),
        )
    if action == "option-place":
        return _call_api(
            "trade.preview_option",
            lambda: trade_client.order_v2.preview_option(
                account_id,
                normalized_orders,
                client_combo_order_id=client_combo_order_id,
            ),
        )
    return None


def execute_trade_action(
    profile,
    action: str,
    policy: Dict[str, Any],
    orders: Optional[List[Dict[str, Any]]] = None,
    account_id: str = "",
    endpoint_override: str = "",
    region_override: str = "",
    client_combo_order_id: Optional[str] = None,
    client_order_id: str = "",
    confirm_live: bool = False,
    skip_preview: bool = False,
    risk_mode: str = "enforce",
    page_size: int = 20,
    start_date: str = "",
    end_date: str = "",
    last_client_order_id: str = "",
) -> Dict[str, Any]:
    endpoint = endpoint_override or profile.endpoint
    region_id = region_override or profile.region_id
    decision_trace: List[str] = []

    orders = orders or []
    normalized_orders: List[Dict[str, Any]] = []
    normalize_violations: List[str] = []
    normalize_warnings: List[str] = []
    order_payload_violations: List[str] = []
    order_field = "new_orders"
    if action in {"replace", "option-replace"}:
        order_field = "modify_orders"
    elif action == "batch-place":
        order_field = "batch_orders"
    if action_requires_orders(action):
        default_inst = "OPTION" if action in {"option-preview", "option-place", "option-replace"} else "EQUITY"
        strict_live_order_guard = action_mutates_with_orders(action)
        normalized_orders, normalize_violations, normalize_warnings = normalize_orders(
            orders,
            policy,
            default_instrument_type=default_inst,
            require_explicit_client_order_id=strict_live_order_guard,
            allow_default_instrument_type=(not strict_live_order_guard),
            allow_default_market=(not strict_live_order_guard),
        )
        order_payload_violations = validate_order_payload(normalized_orders, action)

    result: Dict[str, Any] = {
        "profile": profile.name,
        "action": action,
        "endpoint": endpoint,
        "region_id": region_id,
        "account_id": "",
        "account_id_source": "none",
        "account_candidates": [],
        "accounts": [],
        "account_count": 0,
        "allow": False,
        "risk_mode": risk_mode,
        "normalized_order": {
            "order_field": order_field,
            "orders": normalized_orders,
            "client_combo_order_id": client_combo_order_id,
        },
        "risk": {
            "violations": list(normalize_violations) + list(order_payload_violations),
            "warnings": list(normalize_warnings),
            "metrics": {},
            "blocked_by_risk": False,
        },
        "preview_result": None,
        "live_result": None,
        "post_trade_check": None,
        "trade_outcome": {
            "status": "not_applicable",
            "is_success": False,
            "checked": False,
            "detail": "Action does not mutate orders.",
        },
        "action_result": None,
        "decision_trace": decision_trace,
    }

    pending_crypto_buy_notional: Optional[Decimal] = None

    # local-check path.
    if action == "local-check":
        risk_violations, risk_warnings, metrics = evaluate_risk(
            orders=normalized_orders,
            policy=policy,
            action="preview",
            endpoint=endpoint,
            pending_crypto_buy_notional=None,
        )
        result["risk"]["violations"].extend(risk_violations)
        result["risk"]["warnings"].extend(risk_warnings)
        result["risk"]["metrics"] = metrics

        if result["risk"]["violations"] and risk_mode == "enforce":
            result["risk"]["blocked_by_risk"] = True
            decision_trace.append("Blocked in local-check because risk_mode=enforce and violations exist.")
            return _finalize_trade_result(result)
        if result["risk"]["violations"] and risk_mode in {"warn", "off"}:
            decision_trace.append("Risk violations captured but not blocking local-check.")

        result["allow"] = True
        decision_trace.append("Local-check completed. No API call executed.")
        return _finalize_trade_result(result)

    if result["risk"]["violations"] and risk_mode == "enforce":
        result["risk"]["blocked_by_risk"] = True
        decision_trace.append("Blocked by preflight validation before API call.")
        return _finalize_trade_result(result)
    if result["risk"]["violations"] and risk_mode in {"warn", "off"}:
        decision_trace.append(f"Preflight violations exist but continue because risk_mode={risk_mode}.")

    decision_trace.append("Initializing API client.")
    try:
        api_client = ApiClient(profile.app_key, profile.app_secret, region_id)
        api_client.add_endpoint(region_id, endpoint)
        trade_client = TradeClient(api_client)
    except Exception as exc:
        result["risk"]["violations"].append(f"Client initialization failed: {exc}")
        result["risk"]["blocked_by_risk"] = True
        decision_trace.append("Blocked because API client initialization failed.")
        return _finalize_trade_result(result)

    if action_requires_account(action):
        resolved_account_id, account_source, account_api_result, account_candidates = resolve_account_id(
            trade_client=trade_client,
            explicit_account_id=account_id,
            account_id_hint=profile.account_id_hint,
        )
        result["account_candidates"] = account_candidates
        result["accounts"] = list(account_candidates)
        result["account_count"] = len(account_candidates)
        if not account_api_result.ok:
            result["risk"]["violations"].append(f"Account resolution failed: {account_api_result.detail}")
            result["risk"]["blocked_by_risk"] = True
            decision_trace.append("Blocked because account resolution failed.")
            return _finalize_trade_result(result)
        result["account_id"] = resolved_account_id
        result["account_id_source"] = account_source
        if account_source == "account_list_selected_interactive":
            decision_trace.append("Account selected interactively from account list.")

    if action_requires_client_order_id(action) and not client_order_id:
        result["risk"]["violations"].append(f"Action '{action}' requires --client-order-id.")
        result["risk"]["blocked_by_risk"] = True
        decision_trace.append("Blocked because required client_order_id is missing.")
        return _finalize_trade_result(result)

    if action_requires_orders(action):
        crypto_cfg = policy.get("instruments", {}).get("CRYPTO", {})
        if bool(crypto_cfg.get("enforce_pending_buy_notional", False)) and result["account_id"]:
            pending_crypto_buy_notional = _fetch_pending_crypto_buy_notional(trade_client, result["account_id"])
            if pending_crypto_buy_notional is None:
                result["risk"]["warnings"].append("Could not fetch pending crypto buy notional; skipping this guard.")

        risk_action = action
        if action in {"batch-place", "option-place"}:
            risk_action = "place"
        elif action in {"option-preview"}:
            risk_action = "preview"
        elif action in {"option-replace"}:
            risk_action = "replace"

        risk_violations, risk_warnings, metrics = evaluate_risk(
            orders=normalized_orders,
            policy=policy,
            action=risk_action,
            endpoint=endpoint,
            pending_crypto_buy_notional=pending_crypto_buy_notional,
        )
        result["risk"]["violations"].extend(risk_violations)
        result["risk"]["warnings"].extend(risk_warnings)
        result["risk"]["metrics"] = metrics

        if risk_violations and risk_mode == "enforce":
            result["risk"]["blocked_by_risk"] = True
            decision_trace.append("Blocked by risk guard (risk_mode=enforce).")
            return _finalize_trade_result(result)
        if risk_violations:
            decision_trace.append(f"Risk violations exist but continue because risk_mode={risk_mode}.")

    live_cfg = policy.get("live", {})
    if action in {"place", "batch-place", "replace", "cancel", "option-place", "option-replace", "option-cancel"}:
        if bool(live_cfg.get("require_confirm_live", False)) and not confirm_live:
            result["risk"]["violations"].append("Mutating action requires --confirm-live by policy.")
            result["risk"]["blocked_by_risk"] = True
            decision_trace.append("Blocked because confirm-live flag is missing.")
            return _finalize_trade_result(result)

        require_preview_before_live = bool(live_cfg.get("require_preview_before_live", False))
        if require_preview_before_live:
            if skip_preview:
                decision_trace.append("Policy requires preview-before-live; ignoring --skip-preview.")
            decision_trace.append("Policy requires preview before mutating action; executing preview first.")
            preview_call = _run_required_preview_before_live(
                trade_client=trade_client,
                action=action,
                account_id=result["account_id"],
                normalized_orders=normalized_orders,
                client_combo_order_id=client_combo_order_id,
            )
            if preview_call is None:
                result["risk"]["warnings"].append(
                    f"Policy requires preview-before-live, but action '{action}' has no preview API; continuing without preview."
                )
                decision_trace.append(f"No preview API for action '{action}', continue by policy exception.")
            else:
                result["preview_result"] = {
                    "ok": preview_call.ok,
                    "status_code": preview_call.status_code,
                    "detail": preview_call.detail,
                    "payload": preview_call.payload,
                }
                if not preview_call.ok:
                    result["risk"]["violations"].append(f"Preview-before-live failed: {preview_call.detail}")
                    result["risk"]["blocked_by_risk"] = True
                    decision_trace.append("Blocked because preview-before-live failed.")
                    return _finalize_trade_result(result)

    action_result: ApiResult
    account_for_call = result["account_id"]

    if action == "preview":
        decision_trace.append("Executing preview_order.")
        action_result = _call_api(
            "trade.preview_order",
            lambda: trade_client.order_v3.preview_order(
                account_for_call,
                normalized_orders,
                client_combo_order_id=client_combo_order_id,
            ),
        )
    elif action == "place":
        decision_trace.append("Executing place_order.")
        action_result = _call_api(
            "trade.place_order",
            lambda: trade_client.order_v3.place_order(
                account_for_call,
                normalized_orders,
                client_combo_order_id=client_combo_order_id,
            ),
        )
    elif action == "batch-place":
        decision_trace.append("Executing batch_place_order.")
        action_result = _call_api(
            "trade.batch_place_order",
            lambda: trade_client.order_v3.batch_place_order(
                account_for_call,
                normalized_orders,
            ),
        )
    elif action == "replace":
        decision_trace.append("Executing replace_order.")
        action_result = _call_api(
            "trade.replace_order",
            lambda: trade_client.order_v3.replace_order(
                account_for_call,
                normalized_orders,
                client_combo_order_id=client_combo_order_id,
            ),
        )
    elif action == "cancel":
        decision_trace.append("Executing cancel_order.")
        action_result = _call_api(
            "trade.cancel_order",
            lambda: trade_client.order_v3.cancel_order(account_for_call, client_order_id),
        )
    elif action == "option-preview":
        decision_trace.append("Executing preview_option.")
        action_result = _call_api(
            "trade.preview_option",
            lambda: trade_client.order_v2.preview_option(
                account_for_call,
                normalized_orders,
                client_combo_order_id=client_combo_order_id,
            ),
        )
    elif action == "option-place":
        decision_trace.append("Executing place_option.")
        action_result = _call_api(
            "trade.place_option",
            lambda: trade_client.order_v2.place_option(
                account_for_call,
                normalized_orders,
                client_combo_order_id=client_combo_order_id,
            ),
        )
    elif action == "option-replace":
        decision_trace.append("Executing replace_option.")
        action_result = _call_api(
            "trade.replace_option",
            lambda: trade_client.order_v2.replace_option(
                account_for_call,
                normalized_orders,
                client_combo_order_id=client_combo_order_id,
            ),
        )
    elif action == "option-cancel":
        decision_trace.append("Executing cancel_option.")
        action_result = _call_api(
            "trade.cancel_option",
            lambda: trade_client.order_v2.cancel_option(account_for_call, client_order_id),
        )
    elif action == "detail":
        decision_trace.append("Executing get_order_detail.")
        action_result = _call_api(
            "trade.get_order_detail",
            lambda: trade_client.order_v3.get_order_detail(account_for_call, client_order_id),
        )
    elif action == "open":
        decision_trace.append("Executing get_order_open.")
        action_result = _call_api(
            "trade.get_order_open",
            lambda: trade_client.order_v3.get_order_open(
                account_for_call,
                page_size=page_size,
                last_client_order_id=(last_client_order_id or None),
            ),
        )
    elif action == "history":
        decision_trace.append("Executing get_order_history.")
        action_result = _call_api(
            "trade.get_order_history",
            lambda: trade_client.order_v3.get_order_history(
                account_for_call,
                page_size=page_size,
                start_date=(start_date or None),
                end_date=(end_date or None),
                last_client_order_id=(last_client_order_id or None),
            ),
        )
    elif action == "account-list":
        decision_trace.append("Executing get_account_list.")
        action_result = _call_api("trade.get_account_list", lambda: trade_client.account_v2.get_account_list())
    elif action == "balance":
        decision_trace.append("Executing get_account_balance.")
        action_result = _call_api("trade.get_account_balance", lambda: trade_client.account_v2.get_account_balance(account_for_call))
    elif action == "position":
        decision_trace.append("Executing get_account_position.")
        action_result = _call_api("trade.get_account_position", lambda: trade_client.account_v2.get_account_position(account_for_call))
    else:
        result["risk"]["violations"].append(f"Unsupported action: {action}")
        result["risk"]["blocked_by_risk"] = True
        decision_trace.append("Blocked because action is unsupported.")
        return _finalize_trade_result(result)

    action_payload = {
        "ok": action_result.ok,
        "status_code": action_result.status_code,
        "detail": action_result.detail,
        "payload": action_result.payload,
    }
    if action == "account-list":
        accounts = _collect_account_candidates(action_result.payload)
        result["account_candidates"] = accounts
        result["accounts"] = accounts
        result["account_count"] = len(accounts)
    result["action_result"] = action_payload
    if action in {"preview", "option-preview"}:
        result["preview_result"] = action_payload
    if action_is_mutating(action):
        result["live_result"] = action_payload

    if not action_result.ok:
        if action_is_mutating(action):
            result["trade_outcome"] = {
                "status": "failure",
                "is_success": False,
                "checked": False,
                "detail": "Mutating API call failed before post-trade check.",
            }
        decision_trace.append(f"Action '{action}' failed.")
        return _finalize_trade_result(result)

    if action_is_mutating(action):
        order_client_ids = _extract_order_ids_for_post_check(action, normalized_orders, client_order_id)
        if not order_client_ids:
            result["post_trade_check"] = {
                "attempted": False,
                "account_id": account_for_call,
                "checked_order_count": 0,
                "orders": [],
                "summary": {
                    "outcome": "unknown",
                    "is_success": False,
                    "is_failure": False,
                    "failed_checks": 0,
                    "known_status_orders": 0,
                },
                "detail": "No client_order_id available for post-trade check.",
            }
            result["trade_outcome"] = {
                "status": "unknown",
                "is_success": False,
                "checked": False,
                "detail": "Order submitted, but post-trade verification was skipped because client_order_id is unavailable.",
            }
            decision_trace.append("Post-trade check skipped because no client_order_id is available.")
            return _finalize_trade_result(result)

        post_check = _run_post_trade_check(trade_client, action, account_for_call, order_client_ids)
        result["post_trade_check"] = post_check
        outcome = post_check["summary"]["outcome"]
        result["trade_outcome"] = {
            "status": outcome,
            "is_success": bool(post_check["summary"]["is_success"]),
            "checked": True,
            "detail": (
                "Post-trade check completed."
                if outcome != "unknown"
                else "Post-trade check completed, but order status remains unknown."
            ),
        }
        if outcome == "failure":
            decision_trace.append("Post-trade check indicates business failure.")
            return _finalize_trade_result(result)
        if outcome == "unknown":
            decision_trace.append("Post-trade check result is unknown.")
            return _finalize_trade_result(result)

    result["allow"] = True
    decision_trace.append(
        f"Action '{action}' succeeded."
        if not action_is_mutating(action)
        else f"Action '{action}' succeeded and post-trade outcome is {result['trade_outcome']['status']}."
    )
    return _finalize_trade_result(result)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Webull trade ops with dry-run and risk guard")
    parser.add_argument(
        "--profile",
        default="auto",
        help="Profile selector (e.g. prod-us-ref). Use 'auto' to choose from local credentials.",
    )
    parser.add_argument("--mode", choices=["local", "preview", "live"], default="local")
    parser.add_argument(
        "--dry-run",
        choices=["local", "preview"],
        default="",
        help="Alias for dry-run modes; overrides --mode when set.",
    )
    parser.add_argument("--action", choices=ACTION_CHOICES, default="", help="Explicit action (overrides mode/dry-run mapping)")
    parser.add_argument("--risk-mode", choices=["enforce", "warn", "off"], default="enforce")
    parser.add_argument("--order-json", default="", help="Order JSON string")
    parser.add_argument("--order-file", default="", help="Path to order JSON file")
    parser.add_argument("--policy-file", default="scripts/risk_policy.yaml", help="Risk policy file path")
    parser.add_argument("--env", choices=["uat", "prod"], default="", help="Environment router override")
    parser.add_argument("--endpoint", default="", help="Override endpoint host")
    parser.add_argument("--region-id", default="", help="Override region id")
    parser.add_argument("--account-id", default="", help="Explicit account id")
    parser.add_argument("--client-combo-order-id", default="", help="Optional combo order id")
    parser.add_argument("--client-order-id", default="", help="Required for cancel/detail/option-cancel actions")
    parser.add_argument("--confirm-live", action="store_true", help="Used only when policy requires confirm for mutating actions")
    parser.add_argument(
        "--skip-preview",
        action="store_true",
        help="Request skipping preview-before-live. Ignored when policy requires preview.",
    )
    parser.add_argument("--page-size", type=int, default=10, help="Used by open/history actions (10-100)")
    parser.add_argument("--start-date", default="", help="Used by history action (YYYY-MM-DD)")
    parser.add_argument("--end-date", default="", help="Used by history action (YYYY-MM-DD)")
    parser.add_argument("--last-client-order-id", default="", help="Used by open/history pagination")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    parser.add_argument("--verbose-sdk-log", action="store_true", help="Do not suppress SDK logs")

    # Optional custom credentials.
    parser.add_argument("--app-key", default="", help="Custom app key")
    parser.add_argument("--app-secret", default="", help="Custom app secret")
    parser.add_argument("--alias", default="custom", help="Alias for custom profile")
    parser.add_argument("--account-id-hint", default="", help="Optional account id hint for custom profile")
    return parser.parse_args()


def build_profile(args: argparse.Namespace):
    endpoint_override = args.endpoint
    region_override = args.region_id

    if args.app_key or args.app_secret:
        if not args.app_key or not args.app_secret:
            raise SystemExit("Both --app-key and --app-secret are required when custom credentials are used.")
        region_final = (region_override or "us").lower()
        env_final = (args.env or "prod").lower()
        if not endpoint_override:
            endpoint_override = resolve_openapi_host(env_final, region_final)
        return make_custom_profile(
            name=args.alias,
            app_key=args.app_key,
            app_secret=args.app_secret,
            account_id_hint=args.account_id_hint,
            region_id=region_final,
            endpoint=endpoint_override,
        )

    selector = (args.profile or "").strip()
    if selector.lower() == "auto" or not selector:
        selector = choose_default_profile()

    names = list(expand_selector(selector))
    if not names:
        raise SystemExit("No profile selected.")
    if len(names) > 1:
        raise SystemExit("webull_trade_ops.py expects one profile. Use one concrete profile name.")
    try:
        base_profile = get_profile(names[0])
    except (KeyError, CredentialConfigError) as exc:
        raise SystemExit(str(exc))
    region_final = (region_override or base_profile.region_id).lower()
    if args.env and not endpoint_override:
        endpoint_override = resolve_openapi_host(args.env, region_final)

    if not endpoint_override and region_final == base_profile.region_id.lower():
        return base_profile
    return make_custom_profile(
        name=base_profile.name,
        app_key=base_profile.app_key,
        app_secret=base_profile.app_secret,
        account_id_hint=base_profile.account_id_hint,
        region_id=region_final,
        endpoint=endpoint_override or base_profile.endpoint,
    )


def resolve_action(args: argparse.Namespace) -> str:
    if args.action:
        return args.action
    if args.dry_run:
        return _action_from_mode(args.dry_run)
    return _action_from_mode(args.mode)


def main() -> int:
    args = parse_args()
    set_sdk_logging(args.verbose_sdk_log)

    action = resolve_action(args)
    if action in {"open", "history"} and not (10 <= args.page_size <= 100):
        raise SystemExit("--page-size must be between 10 and 100 for open/history actions.")
    profile = build_profile(args)
    try:
        policy = load_policy(args.policy_file)
    except PolicyLoadError as exc:
        raise SystemExit(str(exc))

    try:
        orders, combo_id_from_payload = load_orders_if_needed(action, args.order_json, args.order_file)
    except ValueError as exc:
        raise SystemExit(str(exc))

    try:
        result = execute_trade_action(
            profile=profile,
            action=action,
            policy=policy,
            orders=orders,
            account_id=args.account_id,
            endpoint_override=args.endpoint,
            region_override=args.region_id,
            client_combo_order_id=(args.client_combo_order_id or combo_id_from_payload or None),
            client_order_id=args.client_order_id,
            confirm_live=args.confirm_live,
            skip_preview=args.skip_preview,
            risk_mode=args.risk_mode,
            page_size=args.page_size,
            start_date=args.start_date,
            end_date=args.end_date,
            last_client_order_id=args.last_client_order_id,
        )
    except ValueError as exc:
        raise SystemExit(str(exc))

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("allow") else 1


if __name__ == "__main__":
    raise SystemExit(main())
