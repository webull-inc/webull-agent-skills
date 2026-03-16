"""Credential/profile registry for Webull runtime scripts."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


class CredentialConfigError(ValueError):
    """Raised when credential configuration is missing or malformed."""


@dataclass(frozen=True)
class CredentialProfile:
    """Runtime profile for one Webull app credential set."""

    name: str
    app_key: str
    app_secret: str
    account_id_hint: str = ""
    region_id: str = "us"
    endpoint: str = "api.webull.com"
    notes: str = ""


@dataclass(frozen=True)
class ProfileDefinition:
    """Static profile metadata without secrets."""

    name: str
    account_id_hint: str = ""
    region_id: str = "us"
    endpoint: str = "api.webull.com"
    notes: str = ""


PROFILE_DEFINITIONS: Dict[str, ProfileDefinition] = {
    # UAT doc test profile names (no builtin account IDs).
    "uat-doc-1": ProfileDefinition(
        name="uat-doc-1",
        account_id_hint="",
        region_id="us",
        endpoint="us-openapi-alb.uat.webullbroker.com",
        notes="UAT profile metadata",
    ),
    "uat-doc-2": ProfileDefinition(
        name="uat-doc-2",
        account_id_hint="",
        region_id="us",
        endpoint="us-openapi-alb.uat.webullbroker.com",
        notes="UAT profile metadata",
    ),
    "uat-doc-3": ProfileDefinition(
        name="uat-doc-3",
        account_id_hint="",
        region_id="us",
        endpoint="us-openapi-alb.uat.webullbroker.com",
        notes="UAT profile metadata",
    ),
    # Prod reference profile metadata.
    "prod-us-ref": ProfileDefinition(
        name="prod-us-ref",
        account_id_hint="",
        region_id="us",
        endpoint="api.webull.com",
        notes="Prod environment reference profile metadata",
    ),
    # Optional HK prod reference metadata.
    "prod-hk-ref": ProfileDefinition(
        name="prod-hk-ref",
        account_id_hint="",
        region_id="hk",
        endpoint="api.webull.hk",
        notes="Prod environment HK reference profile metadata",
    ),
}


PROFILE_GROUPS: Dict[str, List[str]] = {
    "all-uat-doc": ["uat-doc-1", "uat-doc-2", "uat-doc-3"],
    "all-prod-ref": ["prod-us-ref", "prod-hk-ref"],
    "all": list(PROFILE_DEFINITIONS.keys()),
}


_ALLOWED_REGION_IDS = {"us", "hk"}


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _profile_env_names(name: str) -> Tuple[str, str]:
    token = re.sub(r"[^A-Za-z0-9]+", "_", name).upper()
    return f"WEBULL_{token}_APP_KEY", f"WEBULL_{token}_APP_SECRET"


def _profile_env_token(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).upper()


def _credential_file_path() -> Path:
    raw = os.getenv("WEBULL_PROFILE_CREDENTIAL_FILE", "conf/webull_profiles.json").strip()
    chosen = Path(raw or "conf/webull_profiles.json")
    if chosen.is_absolute():
        return chosen
    if chosen.exists():
        return chosen.resolve()
    return (_project_root() / chosen).resolve()


def _default_endpoint_for_region(region_id: str) -> str:
    region = (region_id or "us").strip().lower()
    if region == "hk":
        return "api.webull.hk"
    return "api.webull.com"


def _normalize_credential_entry(name: str, entry: Any, source_label: str) -> Dict[str, str]:
    if not isinstance(entry, dict):
        raise CredentialConfigError(
            f"Credential config error ({source_label}): profile '{name}' must be an object with app_key/app_secret."
        )

    app_key = entry.get("app_key", entry.get("appKey", ""))
    app_secret = entry.get("app_secret", entry.get("appSecret", ""))
    account_id_hint = entry.get("account_id_hint", entry.get("accountIdHint", ""))
    region_id = entry.get("region_id", entry.get("regionId", ""))
    endpoint = entry.get("endpoint", "")
    notes = entry.get("notes", "")

    app_key = app_key.strip() if isinstance(app_key, str) else ""
    app_secret = app_secret.strip() if isinstance(app_secret, str) else ""
    account_id_hint = account_id_hint.strip() if isinstance(account_id_hint, str) else ""
    region_id = region_id.strip().lower() if isinstance(region_id, str) else ""
    endpoint = endpoint.strip() if isinstance(endpoint, str) else ""
    notes = notes.strip() if isinstance(notes, str) else ""

    if not app_key or not app_secret:
        raise CredentialConfigError(
            f"Credential config error ({source_label}): profile '{name}' missing app_key/app_secret."
        )
    if region_id and region_id not in _ALLOWED_REGION_IDS:
        raise CredentialConfigError(
            f"Credential config error ({source_label}): profile '{name}' has invalid region_id '{region_id}'. "
            "Allowed values: us, hk."
        )

    return {
        "app_key": app_key,
        "app_secret": app_secret,
        "account_id_hint": account_id_hint,
        "region_id": region_id,
        "endpoint": endpoint,
        "notes": notes,
    }


def _load_file_credentials() -> Dict[str, Dict[str, str]]:
    path = _credential_file_path()
    if not path.exists():
        return {}

    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CredentialConfigError(f"Credential config error ({path}): failed to parse JSON: {exc}") from exc

    if not isinstance(loaded, dict):
        raise CredentialConfigError(f"Credential config error ({path}): top-level JSON must be an object.")

    profiles_obj = loaded.get("profiles", loaded)
    if not isinstance(profiles_obj, dict):
        raise CredentialConfigError(f"Credential config error ({path}): 'profiles' must be an object.")

    normalized: Dict[str, Dict[str, str]] = {}
    for name, entry in profiles_obj.items():
        if not isinstance(name, str) or not name.strip():
            continue
        normalized[name.strip()] = _normalize_credential_entry(name.strip(), entry, str(path))
    return normalized


def _resolve_profile_credentials(name: str) -> Tuple[str, str, str, str]:
    key_env, secret_env = _profile_env_names(name)
    token = _profile_env_token(name)
    env_key = os.getenv(key_env, "").strip()
    env_secret = os.getenv(secret_env, "").strip()
    env_hint = os.getenv(f"WEBULL_{token}_ACCOUNT_ID_HINT", "").strip()

    if env_key or env_secret:
        if not env_key or not env_secret:
            missing = key_env if not env_key else secret_env
            raise CredentialConfigError(
                f"Profile '{name}' credentials are incomplete in environment variables. Missing {missing}."
            )
        return env_key, env_secret, env_hint, f"env:{key_env}/{secret_env}"

    file_credentials = _load_file_credentials()
    if name in file_credentials:
        entry = file_credentials[name]
        return entry["app_key"], entry["app_secret"], entry.get("account_id_hint", ""), f"file:{_credential_file_path()}"

    credential_file = _credential_file_path()
    raise CredentialConfigError(
        (
            f"Profile '{name}' credentials are not configured. Set environment variables "
            f"{key_env} and {secret_env}, or add profile '{name}' to {credential_file}."
        )
    )


def list_profile_names() -> List[str]:
    """Return all builtin profile names in stable order."""
    return list(PROFILE_DEFINITIONS.keys())


def list_configured_profile_names() -> List[str]:
    """Return profile names discovered from credential file."""
    try:
        return sorted(_load_file_credentials().keys())
    except CredentialConfigError:
        return []


def choose_default_profile(preferred: str = "prod-us-ref") -> str:
    """Pick a sensible default profile from current config."""
    override = os.getenv("WEBULL_DEFAULT_PROFILE", "").strip()
    if override:
        return override

    configured = list_configured_profile_names()
    if not configured:
        return preferred
    if preferred in configured:
        return preferred
    if len(configured) == 1:
        return configured[0]

    for candidate in ["prod-us-ref", "prod-hk-ref"]:
        if candidate in configured:
            return candidate
    return configured[0]


def _known_profiles_and_groups() -> str:
    known = list_profile_names() + list(PROFILE_GROUPS.keys())
    configured = list_configured_profile_names()
    for name in configured:
        if name not in known:
            known.append(name)
    return ", ".join(known)


def get_profile(name: str) -> CredentialProfile:
    """Get one profile by name (builtin or custom from credentials file/env)."""
    definition = PROFILE_DEFINITIONS.get(name)

    file_entry: Dict[str, str] = {}
    try:
        file_entry = _load_file_credentials().get(name, {})
    except CredentialConfigError as exc:
        raise CredentialConfigError(str(exc))

    key_env, secret_env = _profile_env_names(name)
    has_env = bool(os.getenv(key_env, "").strip() or os.getenv(secret_env, "").strip())

    if definition is None and not file_entry and not has_env:
        raise KeyError(f"Unknown profile '{name}'. Known profiles/groups: {_known_profiles_and_groups()}")

    app_key, app_secret, hint_override, source = _resolve_profile_credentials(name)

    if definition is not None:
        account_id_hint = hint_override or definition.account_id_hint
        region_id = definition.region_id
        endpoint = definition.endpoint
        notes = definition.notes
    else:
        account_id_hint = hint_override or file_entry.get("account_id_hint", "")
        region_id = file_entry.get("region_id", "") or "us"
        region_id = region_id.lower() if region_id.lower() in _ALLOWED_REGION_IDS else "us"
        endpoint = file_entry.get("endpoint", "") or _default_endpoint_for_region(region_id)
        notes = file_entry.get("notes", "") or "Custom profile metadata"

    if notes:
        notes = f"{notes}; credential_source={source}"
    else:
        notes = f"credential_source={source}"

    return CredentialProfile(
        name=name,
        app_key=app_key,
        app_secret=app_secret,
        account_id_hint=account_id_hint,
        region_id=region_id,
        endpoint=endpoint,
        notes=notes,
    )


def expand_selector(selector: str) -> Iterable[str]:
    """Expand one selector into concrete profile names."""
    cleaned = (selector or "").strip()
    if cleaned in PROFILE_GROUPS:
        return PROFILE_GROUPS[cleaned]
    if "," in cleaned:
        names: List[str] = []
        for part in cleaned.split(","):
            name = part.strip()
            if not name:
                continue
            if name in PROFILE_GROUPS:
                names.extend(PROFILE_GROUPS[name])
            else:
                names.append(name)
        return names
    return [cleaned] if cleaned else []


def make_custom_profile(
    name: str,
    app_key: str,
    app_secret: str,
    account_id_hint: str = "",
    region_id: str = "us",
    endpoint: str = "api.webull.com",
) -> CredentialProfile:
    """Build an ad-hoc profile from runtime inputs."""
    return CredentialProfile(
        name=name,
        app_key=app_key,
        app_secret=app_secret,
        account_id_hint=account_id_hint,
        region_id=region_id,
        endpoint=endpoint,
        notes="custom runtime profile",
    )
