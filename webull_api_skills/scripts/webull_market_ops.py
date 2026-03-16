#!/usr/bin/env python3
"""Unified market/instrument/account query ops for OpenClaw/OpenWork skill usage."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from webull.core.client import ApiClient
from webull.data.common.category import Category
from webull.data.common.contract_type import ContractType
from webull.data.common.timespan import Timespan
from webull.data.data_client import DataClient
from webull.trade.trade_client import TradeClient

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
    "instrument-stock",
    "instrument-crypto",
    "instrument-futures-products",
    "instrument-futures-list",
    "instrument-futures-by-code",
    "instrument-event-series",
    "instrument-event-list",
    "stock-snapshot",
    "stock-bars",
    "stock-batch-bars",
    "stock-tick",
    "stock-quotes",
    "stock-footprint",
    "futures-snapshot",
    "futures-bars",
    "futures-tick",
    "futures-depth",
    "futures-footprint",
    "crypto-snapshot",
    "crypto-bars",
    "event-snapshot",
    "event-depth",
    "account-list",
    "balance",
    "position",
    "trade-calendar",
    "trade-instrument-detail",
    "trade-security-detail",
    "tradeable-instruments",
]


def _safe_json(resp: Any) -> Any:
    try:
        return resp.json()
    except Exception:
        return None


def _call_api(name: str, fn) -> Dict[str, Any]:
    try:
        resp = fn()
        code = getattr(resp, "status_code", None)
        payload = _safe_json(resp)
        if code == 200:
            return {"ok": True, "status_code": code, "detail": "ok", "payload": payload}
        detail = None
        if isinstance(payload, dict):
            detail = payload.get("message") or payload.get("msg") or payload.get("error_code")
        return {"ok": False, "status_code": code, "detail": detail or f"{name} failed", "payload": payload}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "status_code": None, "detail": str(exc), "payload": None}


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


def _split_csv(value: str) -> List[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _load_json_input(raw: str, file_path: str, default: Any) -> Any:
    if raw and file_path:
        raise SystemExit("Use only one of --query-json/--query-file or --body-json/--body-file.")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid JSON input: line {exc.lineno}, column {exc.colno}: {exc.msg}.")
    if file_path:
        try:
            text = Path(file_path).read_text(encoding="utf-8")
        except Exception as exc:
            raise SystemExit(f"Failed to read JSON file '{file_path}': {exc}")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid JSON file '{file_path}': line {exc.lineno}, column {exc.colno}: {exc.msg}.")
    return default


def _default_category_for_action(action: str) -> str:
    if action.startswith("stock-") or action == "instrument-stock":
        return Category.US_STOCK.name
    if action.startswith("futures-") or action in {"instrument-futures-products", "instrument-futures-list", "instrument-futures-by-code"}:
        return Category.US_FUTURES.name
    if action.startswith("crypto-") or action == "instrument-crypto":
        return Category.US_CRYPTO.name
    if action.startswith("event-"):
        return Category.US_EVENT.name
    return Category.US_STOCK.name


def _require(value: Any, message: str) -> None:
    if value is None:
        raise SystemExit(message)
    if isinstance(value, str) and not value.strip():
        raise SystemExit(message)


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
        raise SystemExit("webull_market_ops.py expects one concrete profile.")
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


def _resolve_account_id(
    trade_client: TradeClient, explicit_account_id: str, hint: str
) -> Tuple[str, str, Dict[str, Any], List[Dict[str, str]]]:
    if explicit_account_id:
        return explicit_account_id, "input", {"ok": True, "status_code": 200, "detail": "input", "payload": None}, []
    if hint:
        return hint, "profile_hint", {"ok": True, "status_code": 200, "detail": "profile_hint", "payload": None}, []

    account_list = _call_api("trade.get_account_list", lambda: trade_client.account_v2.get_account_list())
    if not account_list["ok"]:
        return "", "none", account_list, []
    candidates = _collect_account_candidates(account_list["payload"])
    if not candidates:
        return "", "none", {
            "ok": False,
            "status_code": account_list["status_code"],
            "detail": "Could not resolve account_id from account list payload.",
            "payload": account_list["payload"],
        }, []
    try:
        account_id, source = _prompt_select_account_id(candidates)
    except ValueError as exc:
        return "", "none", {
            "ok": False,
            "status_code": account_list["status_code"],
            "detail": str(exc),
            "payload": account_list["payload"],
        }, candidates
    return account_id, source, account_list, candidates


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Webull market/instrument/account query operations")
    parser.add_argument(
        "--profile",
        default="auto",
        help="Profile selector (single profile expected). Use 'auto' to choose from local credentials.",
    )
    parser.add_argument("--action", required=True, choices=ACTION_CHOICES, help="Action to execute")
    parser.add_argument("--env", choices=["uat", "prod"], default="", help="Environment router override")
    parser.add_argument("--endpoint", default="", help="Override endpoint host")
    parser.add_argument("--region-id", default="", help="Override region id (us/hk)")
    parser.add_argument("--account-id", default="", help="Explicit account id for balance/position")

    parser.add_argument("--symbol", default="AAPL", help="Single symbol")
    parser.add_argument("--symbols", default="AAPL", help="CSV symbols for batch actions")
    parser.add_argument("--category", default="", help="Category enum, e.g. US_STOCK/US_FUTURES/US_CRYPTO/US_EVENT")
    parser.add_argument("--timespan", default=Timespan.M1.name, help="Timespan enum, e.g. M1/M5/D")
    parser.add_argument("--count", default="200", help="Count for bars/tick APIs")
    parser.add_argument("--depth", type=int, default=1, help="Depth for quotes/depth APIs")
    parser.add_argument("--trading-sessions", default="", help="CSV trading sessions: PRE,RTH,ATH,OVN")
    parser.add_argument("--real-time-required", action="store_true", help="Include realtime unfinished bars")
    parser.add_argument("--extend-hour-required", action="store_true", help="Stock snapshot with extended hour")
    parser.add_argument("--overnight-required", action="store_true", help="Stock snapshot/quotes with overnight")

    parser.add_argument("--status", default="", help="Instrument status filter")
    parser.add_argument("--page-size", type=int, default=10, help="Page size for paged APIs")
    parser.add_argument("--last-instrument-id", default="", help="Pagination cursor for instrument APIs")
    parser.add_argument("--code", default="", help="Futures code for instrument-futures-by-code")
    parser.add_argument("--contract-type", default="", choices=["", *ContractType.__members__.keys()], help="MONTHLY or MAIN")
    parser.add_argument("--event-category", default="ECONOMICS", help="Event series category")
    parser.add_argument("--series-symbol", default="", help="Series symbol for instrument-event-list")
    parser.add_argument("--expiration-date-after", default="", help="Event expiration lower bound (YYYY-MM-DD)")

    parser.add_argument("--market", default="US", help="Market for trade-calendar")
    parser.add_argument("--start-date", default="", help="Start date for trade-calendar")
    parser.add_argument("--end-date", default="", help="End date for trade-calendar")
    parser.add_argument("--instrument-id", default="", help="Instrument id for trade-instrument-detail")
    parser.add_argument("--instrument-super-type", default="EQUITY", help="Trade security asset class")
    parser.add_argument("--instrument-type", default="", help="Trade security type")
    parser.add_argument("--strike-price", default="", help="Strike price for trade-security-detail")
    parser.add_argument("--init-exp-date", default="", help="Init exp date (YYYY-MM-DD) for trade-security-detail")

    parser.add_argument("--query-json", default="", help="Reserved json input")
    parser.add_argument("--query-file", default="", help="Reserved json file input")
    parser.add_argument("--body-json", default="", help="Reserved json input")
    parser.add_argument("--body-file", default="", help="Reserved json file input")
    parser.add_argument("--json", action="store_true", help="No-op flag kept for contract compatibility")
    parser.add_argument("--verbose-sdk-log", action="store_true", help="Do not suppress SDK logs")

    parser.add_argument("--app-key", default="", help="Custom app key")
    parser.add_argument("--app-secret", default="", help="Custom app secret")
    parser.add_argument("--alias", default="custom", help="Alias for custom profile")
    parser.add_argument("--account-id-hint", default="", help="Optional account id hint for custom mode")
    return parser.parse_args()


def execute(args: argparse.Namespace) -> Dict[str, Any]:
    set_sdk_logging(args.verbose_sdk_log)
    _ = _load_json_input(args.query_json, args.query_file, default={})
    _ = _load_json_input(args.body_json, args.body_file, default={})

    profile = build_profile(args)
    endpoint = args.endpoint or profile.endpoint
    region_id = args.region_id or profile.region_id
    category = (args.category or _default_category_for_action(args.action)).upper()
    timespan = args.timespan.upper()
    if timespan not in Timespan.__members__:
        raise SystemExit(f"Invalid --timespan '{args.timespan}', choices: {', '.join(Timespan.__members__.keys())}")
    if category not in Category.__members__:
        raise SystemExit(f"Invalid --category '{category}', choices: {', '.join(Category.__members__.keys())}")

    result: Dict[str, Any] = {
        "profile": profile.name,
        "action": args.action,
        "endpoint": endpoint,
        "region_id": region_id,
        "category": category,
        "account_id": "",
        "account_id_source": "none",
        "account_candidates": [],
        "accounts": [],
        "account_count": 0,
        "ok": False,
        "status_code": None,
        "detail": "",
        "payload": None,
    }

    try:
        api_client = ApiClient(profile.app_key, profile.app_secret, region_id)
        api_client.add_endpoint(region_id, endpoint)
        data_client = DataClient(api_client)
        trade_client = TradeClient(api_client)
    except Exception as exc:  # pragma: no cover
        result.update(
            {
                "ok": False,
                "status_code": None,
                "detail": str(exc),
                "payload": None,
            }
        )
        return result

    account_id = ""
    if args.action in {"balance", "position"}:
        account_id, source, account_result, account_candidates = _resolve_account_id(
            trade_client=trade_client,
            explicit_account_id=args.account_id,
            hint=profile.account_id_hint,
        )
        result["account_id"] = account_id
        result["account_id_source"] = source
        result["account_candidates"] = account_candidates
        result["accounts"] = list(account_candidates)
        result["account_count"] = len(account_candidates)
        if not account_result["ok"]:
            result.update(account_result)
            return result

    sessions: Optional[Iterable[str]] = _split_csv(args.trading_sessions) or None
    symbols = args.symbols or args.symbol

    if args.action == "instrument-stock":
        api_result = _call_api(
            "instrument.get_instrument",
            lambda: data_client.instrument.get_instrument(
                symbols=symbols,
                category=category,
                status=(args.status or None),
                last_instrument_id=(args.last_instrument_id or None),
                page_size=args.page_size,
            ),
        )
    elif args.action == "instrument-crypto":
        api_result = _call_api(
            "instrument.get_crypto_instrument",
            lambda: data_client.instrument.get_crypto_instrument(
                symbols=symbols,
                status=(args.status or None),
                last_instrument_id=(args.last_instrument_id or None),
                category=category,
                page_size=args.page_size,
            ),
        )
    elif args.action == "instrument-futures-products":
        api_result = _call_api("instrument.get_futures_products", lambda: data_client.instrument.get_futures_products(category))
    elif args.action == "instrument-futures-list":
        api_result = _call_api(
            "instrument.get_futures_instrument",
            lambda: data_client.instrument.get_futures_instrument(symbols=symbols, category=category),
        )
    elif args.action == "instrument-futures-by-code":
        _require(args.code, "--code is required for instrument-futures-by-code")
        api_result = _call_api(
            "instrument.get_futures_instrument_by_code",
            lambda: data_client.instrument.get_futures_instrument_by_code(
                code=args.code,
                category=category,
                contract_type=(args.contract_type or None),
            ),
        )
    elif args.action == "instrument-event-series":
        api_result = _call_api(
            "instrument.get_event_series",
            lambda: data_client.instrument.get_event_series(
                category=args.event_category,
                last_instrument_id=(args.last_instrument_id or None),
                page_size=args.page_size,
            ),
        )
    elif args.action == "instrument-event-list":
        _require(args.series_symbol, "--series-symbol is required for instrument-event-list")
        api_result = _call_api(
            "instrument.get_event_instrument",
            lambda: data_client.instrument.get_event_instrument(
                series_symbol=args.series_symbol,
                expiration_date_after=(args.expiration_date_after or None),
                last_instrument_id=(args.last_instrument_id or None),
                page_size=args.page_size,
            ),
        )
    elif args.action == "stock-snapshot":
        api_result = _call_api(
            "market.get_snapshot",
            lambda: data_client.market_data.get_snapshot(
                symbols=symbols,
                category=category,
                extend_hour_required=(True if args.extend_hour_required else None),
                overnight_required=(True if args.overnight_required else None),
            ),
        )
    elif args.action == "stock-bars":
        api_result = _call_api(
            "market.get_history_bar",
            lambda: data_client.market_data.get_history_bar(
                symbol=args.symbol,
                category=category,
                timespan=timespan,
                count=args.count,
                real_time_required=(True if args.real_time_required else None),
                trading_sessions=sessions,
            ),
        )
    elif args.action == "stock-batch-bars":
        api_result = _call_api(
            "market.get_batch_history_bar",
            lambda: data_client.market_data.get_batch_history_bar(
                symbols=_split_csv(symbols),
                category=category,
                timespan=timespan,
                count=args.count,
                real_time_required=(True if args.real_time_required else None),
                trading_sessions=sessions,
            ),
        )
    elif args.action == "stock-tick":
        api_result = _call_api(
            "market.get_tick",
            lambda: data_client.market_data.get_tick(
                symbol=args.symbol,
                category=category,
                count=args.count,
                trading_sessions=sessions,
            ),
        )
    elif args.action == "stock-quotes":
        api_result = _call_api(
            "market.get_quotes",
            lambda: data_client.market_data.get_quotes(
                symbol=args.symbol,
                category=category,
                depth=args.depth,
                overnight_required=(True if args.overnight_required else None),
            ),
        )
    elif args.action == "stock-footprint":
        api_result = _call_api(
            "market.get_footprint",
            lambda: data_client.market_data.get_footprint(
                symbols=symbols,
                category=category,
                timespan=timespan,
                count=args.count,
                real_time_required=(True if args.real_time_required else None),
                trading_sessions=sessions,
            ),
        )
    elif args.action == "futures-snapshot":
        api_result = _call_api(
            "futures.get_snapshot",
            lambda: data_client.futures_market_data.get_futures_snapshot(symbols=symbols, category=category),
        )
    elif args.action == "futures-bars":
        api_result = _call_api(
            "futures.get_history_bars",
            lambda: data_client.futures_market_data.get_futures_history_bars(
                symbols=symbols,
                category=category,
                timespan=timespan,
                count=args.count,
                real_time_required=(True if args.real_time_required else None),
            ),
        )
    elif args.action == "futures-tick":
        api_result = _call_api(
            "futures.get_tick",
            lambda: data_client.futures_market_data.get_futures_tick(
                symbol=args.symbol,
                category=category,
                count=args.count,
            ),
        )
    elif args.action == "futures-depth":
        api_result = _call_api(
            "futures.get_depth",
            lambda: data_client.futures_market_data.get_futures_depth(
                symbol=args.symbol,
                category=category,
                depth=args.depth,
            ),
        )
    elif args.action == "futures-footprint":
        api_result = _call_api(
            "futures.get_footprint",
            lambda: data_client.futures_market_data.get_futures_footprint(
                symbols=symbols,
                category=category,
                timespan=timespan,
                count=args.count,
                real_time_required=(True if args.real_time_required else None),
                trading_sessions=sessions,
            ),
        )
    elif args.action == "crypto-snapshot":
        api_result = _call_api(
            "crypto.get_snapshot",
            lambda: data_client.crypto_market_data.get_crypto_snapshot(symbols=symbols, category=category),
        )
    elif args.action == "crypto-bars":
        api_result = _call_api(
            "crypto.get_history_bar",
            lambda: data_client.crypto_market_data.get_crypto_history_bar(
                symbols=symbols,
                category=category,
                timespan=timespan,
                count=args.count,
                real_time_required=(True if args.real_time_required else None),
            ),
        )
    elif args.action == "event-snapshot":
        api_result = _call_api(
            "event.get_snapshot",
            lambda: data_client.event_market_data.get_event_snapshot(symbols=symbols, category=category),
        )
    elif args.action == "event-depth":
        api_result = _call_api(
            "event.get_depth",
            lambda: data_client.event_market_data.get_event_depth(
                symbol=args.symbol,
                category=category,
                depth=args.depth,
            ),
        )
    elif args.action == "account-list":
        api_result = _call_api("trade.get_account_list", lambda: trade_client.account_v2.get_account_list())
    elif args.action == "balance":
        api_result = _call_api("trade.get_account_balance", lambda: trade_client.account_v2.get_account_balance(account_id))
    elif args.action == "position":
        api_result = _call_api("trade.get_account_position", lambda: trade_client.account_v2.get_account_position(account_id))
    elif args.action == "trade-calendar":
        _require(args.start_date, "--start-date is required for trade-calendar")
        _require(args.end_date, "--end-date is required for trade-calendar")
        api_result = _call_api(
            "trade.get_trade_calendar",
            lambda: trade_client.trade_calendar.get_trade_calendar(
                market=args.market,
                start=args.start_date,
                end=args.end_date,
            ),
        )
    elif args.action == "trade-instrument-detail":
        _require(args.instrument_id, "--instrument-id is required for trade-instrument-detail")
        api_result = _call_api(
            "trade.get_trade_instrument_detail",
            lambda: trade_client.trade_instrument.get_trade_instrument_detail(args.instrument_id),
        )
    elif args.action == "trade-security-detail":
        _require(args.symbol, "--symbol is required for trade-security-detail")
        _require(args.instrument_type, "--instrument-type is required for trade-security-detail")
        _require(args.strike_price, "--strike-price is required for trade-security-detail")
        _require(args.init_exp_date, "--init-exp-date is required for trade-security-detail")
        api_result = _call_api(
            "trade.get_trade_security_detail",
            lambda: trade_client.trade_instrument.get_trade_security_detail(
                symbol=args.symbol,
                market=args.market,
                instrument_super_type=args.instrument_super_type,
                instrument_type=args.instrument_type,
                strike_price=args.strike_price,
                init_exp_date=args.init_exp_date,
            ),
        )
    elif args.action == "tradeable-instruments":
        api_result = _call_api(
            "trade.get_tradeable_instruments",
            lambda: trade_client.trade_instrument.get_tradeable_instruments(
                last_instrument_id=(args.last_instrument_id or None),
                page_size=args.page_size,
            ),
        )
    else:  # pragma: no cover
        raise SystemExit(f"Unsupported action: {args.action}")

    result.update(api_result)
    if args.action == "account-list":
        accounts = _collect_account_candidates(api_result.get("payload"))
        result["account_candidates"] = accounts
        result["accounts"] = accounts
        result["account_count"] = len(accounts)
    return result


def main() -> int:
    args = parse_args()
    try:
        result = execute(args)
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover
        result = {
            "profile": args.profile,
            "action": args.action,
            "ok": False,
            "status_code": None,
            "detail": str(exc),
            "payload": None,
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
