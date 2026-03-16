"""Environment/region router for Webull OpenAPI and OAuth hosts."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class EnvRoute:
    env: str
    region_id: str
    openapi_host: str
    oauth_host: str


DEFAULT_ROUTE_MAP: Dict[Tuple[str, str], EnvRoute] = {
    ("uat", "us"): EnvRoute(
        env="uat",
        region_id="us",
        openapi_host="us-openapi-alb.uat.webullbroker.com",
        oauth_host="us-oauth-open-api.uat.webullbroker.com",
    ),
    ("uat", "hk"): EnvRoute(
        env="uat",
        region_id="hk",
        openapi_host="api.sandbox.webull.hk",
        oauth_host="api.sandbox.webull.hk",
    ),
    ("prod", "us"): EnvRoute(
        env="prod",
        region_id="us",
        openapi_host="api.webull.com",
        oauth_host="us-oauth-open-api.webull.com",
    ),
    ("prod", "hk"): EnvRoute(
        env="prod",
        region_id="hk",
        openapi_host="api.webull.hk",
        oauth_host="api.webull.hk",
    ),
}


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _route_file_path() -> Path:
    raw = os.getenv("WEBULL_ENV_ROUTE_FILE", "conf/webull_env_routes.json").strip()
    chosen = Path(raw or "conf/webull_env_routes.json")
    if chosen.is_absolute():
        return chosen
    if chosen.exists():
        return chosen.resolve()
    return (_project_root() / chosen).resolve()


def _derive_oauth_host(openapi_host: str, region_id: str = "us") -> str:
    host = (openapi_host or "").strip()
    region = (region_id or "us").strip().lower()
    if host == "api.webull.com":
        return "oauth-open-api.webull.com" if region == "hk" else "us-oauth-open-api.webull.com"
    if host in {"api.webull.hk", "api.sandbox.webull.hk"}:
        return host
    if "openapi-us-alb" in host:
        return host.replace("openapi-us-alb", "oauth-open-api", 1)
    if "openapi-alb" in host:
        return host.replace("openapi-alb", "oauth-open-api", 1)
    if "openapi" in host:
        return host.replace("openapi", "oauth-open-api", 1)
    return host


def _route_from_entry(env: str, region_id: str, entry: Any, source: str) -> Optional[EnvRoute]:
    if not isinstance(entry, dict):
        raise ValueError(f"Route config error ({source}): '{env}.{region_id}' must be an object.")

    openapi_host = entry.get("openapi_host", entry.get("openapiHost", ""))
    oauth_host = entry.get("oauth_host", entry.get("oauthHost", ""))
    openapi_host = openapi_host.strip() if isinstance(openapi_host, str) else ""
    oauth_host = oauth_host.strip() if isinstance(oauth_host, str) else ""

    if not openapi_host and not oauth_host:
        return None
    if not openapi_host:
        raise ValueError(f"Route config error ({source}): '{env}.{region_id}.openapi_host' is required.")
    if not oauth_host:
        oauth_host = _derive_oauth_host(openapi_host, region_id)
    return EnvRoute(env=env, region_id=region_id, openapi_host=openapi_host, oauth_host=oauth_host)


def _merge_route(
    routes: Dict[Tuple[str, str], EnvRoute],
    env: str,
    region_id: str,
    openapi_host: str,
    oauth_host: str = "",
) -> None:
    env_l = env.lower()
    region_l = region_id.lower()
    key = (env_l, region_l)
    current = routes.get(key)

    openapi_raw = openapi_host.strip()
    oauth_raw = oauth_host.strip()
    has_openapi_override = bool(openapi_raw)

    if openapi_raw:
        openapi = openapi_raw
    elif current:
        openapi = current.openapi_host
    else:
        openapi = ""

    if oauth_raw:
        oauth = oauth_raw
    elif has_openapi_override and openapi:
        # Keep OPENAPI/OAUTH pair consistent when only OPENAPI is overridden.
        oauth = _derive_oauth_host(openapi, region_l)
    elif current:
        oauth = current.oauth_host
    else:
        oauth = ""
    if openapi and oauth:
        routes[key] = EnvRoute(env=env_l, region_id=region_l, openapi_host=openapi, oauth_host=oauth)


def _load_route_file_overrides() -> Dict[Tuple[str, str], EnvRoute]:
    path = _route_file_path()
    if not path.exists():
        return {}

    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Route config error ({path}): failed to parse JSON: {exc}") from exc

    if not isinstance(loaded, dict):
        raise ValueError(f"Route config error ({path}): top-level JSON must be an object.")

    routes_obj = loaded.get("routes", loaded)
    if not isinstance(routes_obj, dict):
        raise ValueError(f"Route config error ({path}): 'routes' must be an object.")

    overrides: Dict[Tuple[str, str], EnvRoute] = {}
    for env, by_region in routes_obj.items():
        if not isinstance(env, str):
            continue
        env_l = env.lower().strip()
        if env_l not in {"uat", "prod"}:
            continue
        if not isinstance(by_region, dict):
            raise ValueError(f"Route config error ({path}): '{env_l}' must map to an object of regions.")
        for region_id, entry in by_region.items():
            if not isinstance(region_id, str):
                continue
            region_l = region_id.lower().strip()
            if region_l not in {"us", "hk"}:
                continue
            route = _route_from_entry(env_l, region_l, entry, str(path))
            if route is not None:
                overrides[(env_l, region_l)] = route
    return overrides


def _apply_env_var_overrides(routes: Dict[Tuple[str, str], EnvRoute]) -> None:
    for env in ("uat", "prod"):
        for region in ("us", "hk"):
            openapi_var = f"WEBULL_OPENAPI_HOST_{env.upper()}_{region.upper()}"
            oauth_var = f"WEBULL_OAUTH_HOST_{env.upper()}_{region.upper()}"
            openapi_host = os.getenv(openapi_var, "").strip()
            oauth_host = os.getenv(oauth_var, "").strip()
            if openapi_host or oauth_host:
                _merge_route(routes, env, region, openapi_host, oauth_host)


@lru_cache(maxsize=1)
def _build_route_map() -> Dict[Tuple[str, str], EnvRoute]:
    routes: Dict[Tuple[str, str], EnvRoute] = dict(DEFAULT_ROUTE_MAP)
    file_overrides = _load_route_file_overrides()
    routes.update(file_overrides)
    _apply_env_var_overrides(routes)
    return routes


def resolve_openapi_host(env: str, region_id: str) -> str:
    key = (env.lower(), region_id.lower())
    route = _build_route_map().get(key)
    if route:
        return route.openapi_host
    raise KeyError(f"No route for env={env}, region_id={region_id}")


def resolve_oauth_host(env: str, region_id: str) -> str:
    key = (env.lower(), region_id.lower())
    route = _build_route_map().get(key)
    if route:
        return route.oauth_host
    raise KeyError(f"No route for env={env}, region_id={region_id}")


def guess_oauth_host(openapi_host: str, region_id: str = "us") -> str:
    host = (openapi_host or "").strip()
    region = (region_id or "us").strip().lower()
    if not host:
        return resolve_oauth_host("prod", region)

    for route in _build_route_map().values():
        if route.region_id == region and route.openapi_host == host:
            return route.oauth_host
    for route in _build_route_map().values():
        if route.openapi_host == host:
            return route.oauth_host

    return _derive_oauth_host(host, region)
