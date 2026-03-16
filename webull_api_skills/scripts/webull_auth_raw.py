#!/usr/bin/env python3
"""Raw signed HTTP operations for Webull auth/connect APIs."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import urllib.parse
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests

try:
    from scripts.webull_env_router import guess_oauth_host, resolve_openapi_host
    from scripts.webull_profiles import (
        CredentialConfigError,
        choose_default_profile,
        expand_selector,
        get_profile,
        make_custom_profile,
    )
except ModuleNotFoundError:  # running as plain script from scripts/
    from webull_env_router import guess_oauth_host, resolve_openapi_host
    from webull_profiles import CredentialConfigError, choose_default_profile, expand_selector, get_profile, make_custom_profile


ACTION_MAP: Dict[str, Tuple[str, str, str]] = {
    "auth-create-token": ("POST", "/openapi/auth/token/create", "openapi"),
    "auth-check-token": ("POST", "/openapi/auth/token/check", "openapi"),
    "oauth2-login": ("GET", "/oauth2/authenticate/login", "oauth"),
    "oauth2-token": ("POST", "/openapi/oauth2/token", "oauth"),
    "raw-get": ("GET", "", "openapi"),
    "raw-post": ("POST", "", "openapi"),
}


def _load_json(raw: str, file_path: str, default: Any) -> Any:
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


def _normalize_query(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SystemExit("Query payload must be a JSON object.")
    return value


def _normalize_body(value: Any) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise SystemExit("Body payload must be a JSON object.")
    return value


def _canonical_json(body: Dict[str, Any]) -> str:
    text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    return text.replace("\\u0026", "&").replace("\\u003c", "<").replace("\\u003e", ">")


def _build_signature(
    app_key: str,
    app_secret: str,
    host: str,
    path: str,
    query: Dict[str, Any],
    body: Optional[Dict[str, Any]],
) -> Dict[str, str]:
    sign_headers: Dict[str, str] = {
        "x-app-key": app_key,
        "x-signature-algorithm": "HMAC-SHA1",
        "x-signature-version": "1.0",
        "x-signature-nonce": uuid.uuid4().hex,
        "x-timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "host": host,
    }

    canonical_query: Dict[str, str] = {}
    for key, value in query.items():
        if value is None:
            continue
        if isinstance(value, list):
            canonical_query[key] = "&".join(sorted(str(item) for item in value))
        else:
            canonical_query[key] = str(value)

    params_for_sign = {**canonical_query, **sign_headers}
    sorted_pairs = sorted(params_for_sign.items(), key=lambda item: item[0])
    str1 = "&".join(f"{k}={v}" for k, v in sorted_pairs)

    str2 = ""
    if body:
        str2 = hashlib.md5(_canonical_json(body).encode("utf-8")).hexdigest().upper()
    str3 = f"{path}&{str1}" + (f"&{str2}" if str2 else "")
    encoded = urllib.parse.quote(str3, safe="")

    key = f"{app_secret}&".encode("utf-8")
    raw_sig = hmac.new(key=key, msg=encoded.encode("utf-8"), digestmod=hashlib.sha1).digest()
    signature = base64.b64encode(raw_sig).decode("utf-8")

    headers: Dict[str, str] = {
        "x-app-key": app_key,
        "x-signature-algorithm": "HMAC-SHA1",
        "x-signature-version": "1.0",
        "x-signature-nonce": sign_headers["x-signature-nonce"],
        "x-timestamp": sign_headers["x-timestamp"],
        "x-signature": signature,
        "x-version": "v2",
        "Content-Type": "application/json",
    }
    return headers


def _build_hosts(args: argparse.Namespace, profile) -> Tuple[str, str]:
    region_id = (args.region_id or profile.region_id or "us").lower()
    openapi_host = args.endpoint or profile.endpoint
    if args.env:
        openapi_host = resolve_openapi_host(args.env, region_id)
    oauth_host = args.oauth_endpoint or guess_oauth_host(openapi_host, region_id)
    return openapi_host, oauth_host


def build_profile(args: argparse.Namespace):
    region_override = args.region_id
    endpoint_override = args.endpoint

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
        raise SystemExit("webull_auth_raw.py expects one concrete profile.")
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Webull raw auth/connect API ops with signature")
    parser.add_argument(
        "--profile",
        default="auto",
        help="Profile name (single profile expected). Use 'auto' to choose from local credentials.",
    )
    parser.add_argument("--action", required=True, choices=list(ACTION_MAP.keys()), help="Action to execute")
    parser.add_argument("--env", choices=["uat", "prod"], default="", help="Environment router override")
    parser.add_argument("--endpoint", default="", help="OpenAPI endpoint override")
    parser.add_argument("--oauth-endpoint", default="", help="OAuth endpoint override")
    parser.add_argument("--region-id", default="", help="Region override")
    parser.add_argument("--path", default="", help="Required for raw-get/raw-post")
    parser.add_argument("--query-json", default="", help="Query JSON object")
    parser.add_argument("--query-file", default="", help="Query JSON file")
    parser.add_argument("--body-json", default="", help="Body JSON object")
    parser.add_argument("--body-file", default="", help="Body JSON file")
    parser.add_argument("--access-token", default="", help="Optional x-access-token")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds")
    parser.add_argument("--json", action="store_true", help="No-op flag, output is always JSON")

    parser.add_argument("--app-key", default="", help="Custom app key")
    parser.add_argument("--app-secret", default="", help="Custom app secret")
    parser.add_argument("--alias", default="custom", help="Alias for custom profile")
    parser.add_argument("--account-id-hint", default="", help="Unused here, kept for profile compatibility")
    return parser.parse_args()


def execute(args: argparse.Namespace) -> Dict[str, Any]:
    profile = build_profile(args)
    openapi_host, oauth_host = _build_hosts(args, profile)

    method, predefined_path, host_scope = ACTION_MAP[args.action]
    path = predefined_path or args.path
    if not path:
        raise SystemExit(f"--path is required for action '{args.action}'")
    if not path.startswith("/"):
        path = "/" + path

    query = _normalize_query(_load_json(args.query_json, args.query_file, default={}))
    body = _normalize_body(_load_json(args.body_json, args.body_file, default=None))
    if method == "GET":
        body = None

    host = openapi_host if host_scope == "openapi" else oauth_host
    headers = _build_signature(
        app_key=profile.app_key,
        app_secret=profile.app_secret,
        host=host,
        path=path,
        query=query,
        body=body,
    )
    if args.access_token:
        headers["x-access-token"] = args.access_token

    url = f"https://{host}{path}"
    request_body = _canonical_json(body) if body else None

    try:
        if method == "GET":
            resp = requests.get(url=url, params=query, headers=headers, timeout=args.timeout)
        else:
            resp = requests.post(
                url=url,
                params=query,
                data=(request_body.encode("utf-8") if request_body else None),
                headers=headers,
                timeout=args.timeout,
            )
        try:
            payload = resp.json()
        except Exception:
            payload = {"raw_text": resp.text}
        ok = resp.status_code == 200
        detail = "ok" if ok else str(payload)[:500]
        return {
            "profile": profile.name,
            "action": args.action,
            "method": method,
            "host": host,
            "url": url,
            "query": query,
            "request_body": body,
            "ok": ok,
            "status_code": resp.status_code,
            "detail": detail,
            "payload": payload,
        }
    except Exception as exc:  # pragma: no cover
        return {
            "profile": profile.name,
            "action": args.action,
            "method": method,
            "host": host,
            "url": url,
            "query": query,
            "request_body": body,
            "ok": False,
            "status_code": None,
            "detail": str(exc),
            "payload": None,
        }


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
            "method": "",
            "host": "",
            "url": "",
            "query": {},
            "request_body": None,
            "ok": False,
            "status_code": None,
            "detail": str(exc),
            "payload": None,
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
