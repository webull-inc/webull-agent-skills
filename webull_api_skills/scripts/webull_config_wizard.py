#!/usr/bin/env python3
"""Interactive setup wizard for profile JSON and risk policy YAML."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

try:
    from scripts.webull_env_router import resolve_openapi_host
except ModuleNotFoundError:  # running as plain script from scripts/
    from webull_env_router import resolve_openapi_host


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_path(raw: str) -> Path:
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    if candidate.exists():
        return candidate.resolve()
    return (_project_root() / candidate).resolve()


def _prompt_text(label: str, default: str = "", required: bool = False) -> str:
    while True:
        suffix = f" [{default}]" if default else ""
        value = input(f"{label}{suffix}: ").strip()
        if not value:
            value = default
        if value or not required:
            return value
        print("This field is required.")


def _prompt_bool(label: str, default: bool) -> bool:
    default_text = "y" if default else "n"
    while True:
        raw = input(f"{label} [y/n, default={default_text}]: ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes", "true", "1"}:
            return True
        if raw in {"n", "no", "false", "0"}:
            return False
        print("Please enter y or n.")


def _parse_bool_text(raw: str, default: Optional[bool] = None) -> Optional[bool]:
    text = (raw or "").strip().lower()
    if not text:
        return default
    if text in {"y", "yes", "true", "1"}:
        return True
    if text in {"n", "no", "false", "0"}:
        return False
    raise SystemExit(f"Invalid boolean value '{raw}'. Use true/false.")


def _load_json_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"Failed to parse JSON file '{path}': {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"JSON file '{path}' must have object/map top-level.")
    return data


def _save_json_file(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_policy(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        if yaml is not None:
            data = yaml.safe_load(text)
        else:
            data = json.loads(text)
    except Exception as exc:
        raise SystemExit(f"Failed to parse policy file '{path}': {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise SystemExit(f"Policy file '{path}' must have object/map top-level.")
    return data


def _save_policy(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if yaml is not None:
        rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    else:
        rendered = json.dumps(data, ensure_ascii=False, indent=2)
    path.write_text(rendered + ("" if rendered.endswith("\n") else "\n"), encoding="utf-8")


def _merge_dict(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _merge_dict(out[key], value)
        else:
            out[key] = value
    return out


def _run_profile_wizard(args: argparse.Namespace) -> int:
    target = _resolve_path(args.file)
    data = _load_json_file(target)
    profiles = data.get("profiles", data)
    if not isinstance(profiles, dict):
        raise SystemExit("Credential JSON must be an object or contain object field 'profiles'.")

    print("\nProfile Setup Wizard")
    print("- profile name: your runtime identifier (e.g. my-prod)")
    print("- app_key/app_secret: Webull OpenAPI credentials")
    print("- region_id: us or hk")
    print("- env: used to infer default endpoint when endpoint is omitted")
    print("- account_id_hint: optional default account id")

    existing = profiles.get(args.name or "", {}) if args.name else {}
    existing = existing if isinstance(existing, dict) else {}

    if args.non_interactive:
        if not args.name or not args.app_key or not args.app_secret:
            raise SystemExit("Non-interactive mode requires --name, --app-key, --app-secret.")
        name = args.name.strip()
        app_key = args.app_key.strip()
        app_secret = args.app_secret.strip()
        region_id = (args.region_id or existing.get("region_id") or "us").strip().lower()
        env = (args.env or "prod").strip().lower()
        account_id_hint = (args.account_id_hint if args.account_id_hint is not None else existing.get("account_id_hint", "")).strip()
        endpoint = (args.endpoint or existing.get("endpoint") or resolve_openapi_host(env, region_id)).strip()
    else:
        name = _prompt_text("Profile name", default=(args.name or "my-prod"), required=True)
        app_key = _prompt_text("App key", default=(args.app_key or existing.get("app_key", "")), required=True)
        app_secret = _prompt_text(
            "App secret",
            default=(args.app_secret or existing.get("app_secret", "")),
            required=True,
        )
        region_id = _prompt_text("Region id (us/hk)", default=(args.region_id or existing.get("region_id", "us")), required=True).lower()
        env = _prompt_text("Env used for default endpoint (uat/prod)", default=(args.env or "prod"), required=True).lower()
        account_id_hint = _prompt_text(
            "Account id hint (optional)", default=(args.account_id_hint or existing.get("account_id_hint", ""))
        )
        endpoint_default = args.endpoint or existing.get("endpoint", "") or resolve_openapi_host(env, region_id)
        endpoint = _prompt_text("OpenAPI endpoint", default=endpoint_default, required=True)

    if region_id not in {"us", "hk"}:
        raise SystemExit("region_id must be 'us' or 'hk'.")
    if env not in {"uat", "prod"}:
        raise SystemExit("env must be 'uat' or 'prod'.")

    profiles[name] = {
        "app_key": app_key,
        "app_secret": app_secret,
        "account_id_hint": account_id_hint,
        "region_id": region_id,
        "endpoint": endpoint,
    }

    if "profiles" in data and isinstance(data["profiles"], dict):
        data["profiles"] = profiles
    else:
        data = {"profiles": profiles}

    _save_json_file(target, data)
    print(f"\nSaved profile '{name}' -> {target}")
    print("Tip: run with --profile auto to use local configured default profile.")
    return 0


def _run_risk_wizard(args: argparse.Namespace) -> int:
    target = _resolve_path(args.file)

    baseline = {
        "global": {
            "max_orders_per_request": 10,
            "allowed_instrument_types": ["EQUITY", "OPTION", "FUTURES", "CRYPTO", "EVENT"],
            "allowed_sides": ["BUY", "SELL"],
            "require_client_order_id": True,
            "auto_generate_client_order_id": True,
            "enforce_unique_client_order_id": True,
        },
        "live": {
            "enabled": True,
            "require_confirm_live": True,
            "require_preview_before_live": True,
            "allowed_endpoints": [
                "api.webull.com",
                "us-openapi-alb.uat.webullbroker.com",
                "api.webull.hk",
                "api.sandbox.webull.hk",
            ],
        },
    }

    current = _merge_dict(baseline, _load_policy(target))

    print("\nRisk Policy Wizard")
    print("- live.enabled: whether live mutating actions are enabled")
    print("- require_confirm_live: require --confirm-live for place/cancel/replace")
    print("- require_preview_before_live: auto preview before live mutating actions")
    print("- max_orders_per_request: batch safety limit")
    print("- allowed_endpoints: whitelist for runtime API hosts")

    live_cfg = current.setdefault("live", {})
    global_cfg = current.setdefault("global", {})

    if args.non_interactive:
        live_enabled = _parse_bool_text(args.live_enabled, default=bool(live_cfg.get("enabled", True)))
        require_confirm_live = _parse_bool_text(
            args.require_confirm_live,
            default=bool(live_cfg.get("require_confirm_live", True)),
        )
        require_preview = _parse_bool_text(
            args.require_preview_before_live,
            default=bool(live_cfg.get("require_preview_before_live", True)),
        )
        max_orders = args.max_orders_per_request if args.max_orders_per_request is not None else int(
            global_cfg.get("max_orders_per_request", 10)
        )
        endpoints_raw = args.allowed_endpoints.strip()
        if endpoints_raw:
            allowed_endpoints = [item.strip() for item in endpoints_raw.split(",") if item.strip()]
        else:
            allowed_endpoints = list(live_cfg.get("allowed_endpoints", []))
    else:
        live_enabled = _prompt_bool("Enable live mutating actions", bool(live_cfg.get("enabled", True)))
        require_confirm_live = _prompt_bool(
            "Require --confirm-live before mutating actions", bool(live_cfg.get("require_confirm_live", True))
        )
        require_preview = _prompt_bool(
            "Require preview before mutating actions", bool(live_cfg.get("require_preview_before_live", True))
        )
        max_orders_default = str(int(global_cfg.get("max_orders_per_request", 10)))
        max_orders = int(_prompt_text("Max orders per request", default=max_orders_default, required=True))
        endpoints_default = ",".join(live_cfg.get("allowed_endpoints", []))
        endpoints_raw = _prompt_text("Allowed endpoints (comma-separated)", default=endpoints_default)
        allowed_endpoints = [item.strip() for item in endpoints_raw.split(",") if item.strip()]

    global_cfg["max_orders_per_request"] = int(max_orders)
    live_cfg["enabled"] = bool(live_enabled)
    live_cfg["require_confirm_live"] = bool(require_confirm_live)
    live_cfg["require_preview_before_live"] = bool(require_preview)
    live_cfg["allowed_endpoints"] = allowed_endpoints

    _save_policy(target, current)
    print(f"\nSaved risk policy -> {target}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactive config wizard for Webull profile JSON and risk YAML")
    sub = parser.add_subparsers(dest="command", required=True)

    profile = sub.add_parser("profile", help="Create/update conf/webull_profiles.json")
    profile.add_argument("--file", default="conf/webull_profiles.json", help="Target profile json file")
    profile.add_argument("--name", default="", help="Profile name")
    profile.add_argument("--app-key", default="", help="App key")
    profile.add_argument("--app-secret", default="", help="App secret")
    profile.add_argument("--account-id-hint", default="", help="Optional account id hint")
    profile.add_argument("--region-id", default="", choices=["", "us", "hk"], help="Region id")
    profile.add_argument("--env", default="prod", choices=["uat", "prod"], help="Env for endpoint default")
    profile.add_argument("--endpoint", default="", help="OpenAPI endpoint")
    profile.add_argument("--non-interactive", action="store_true", help="Do not prompt; use provided flags only")

    risk = sub.add_parser("risk", help="Create/update scripts/risk_policy.yaml")
    risk.add_argument("--file", default="scripts/risk_policy.yaml", help="Target policy file")
    risk.add_argument("--live-enabled", default="", help="true/false")
    risk.add_argument("--require-confirm-live", default="", help="true/false")
    risk.add_argument("--require-preview-before-live", default="", help="true/false")
    risk.add_argument("--max-orders-per-request", type=int, default=None, help="Positive integer")
    risk.add_argument("--allowed-endpoints", default="", help="Comma-separated hosts")
    risk.add_argument("--non-interactive", action="store_true", help="Do not prompt; use provided flags only")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "profile":
        return _run_profile_wizard(args)
    if args.command == "risk":
        return _run_risk_wizard(args)
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
