---
name: webull-openapi
description: Use this skill for production-grade Webull OpenAPI operations in OpenClaw/OpenWork, including configurable env/region routing, market/instrument/account queries, trade actions with risk controls, and raw signed auth/connect API calls across UAT/PROD.
---

# Webull OpenAPI Skill (Full Open)

This skill exposes production runtime capabilities in `scripts/`.

## Runtime Files

- `scripts/webull_profiles.py`
  - Built-in + custom profile metadata:
    - `uat-doc-1/2/3` (docs profile names)
    - `prod-us-ref`, `prod-hk-ref` (reference profile names)
    - custom profile names from `conf/webull_profiles.json` (recommended, e.g. `my-prod`)
  - Group selectors: `all-uat-doc`, `all-prod-ref`, `all`
- `scripts/webull_env_router.py`
  - Environment host routing for `uat/prod` + `us/hk`
- `scripts/webull_market_ops.py`
  - Full market/instrument/account query operations
- `scripts/webull_trade_ops.py`
  - Full trading operations, including live mutating actions
- `scripts/webull_auth_raw.py`
  - Raw signed HTTP for auth/connect APIs
- `scripts/webull_config_wizard.py`
  - Interactive setup/update wizard for `conf/webull_profiles.json` and `scripts/risk_policy.yaml`
- `scripts/webull_cli.py`
  - Unified wrapper entry (`market|trade|auth`)
- `scripts/risk_policy.yaml`
  - Risk policy file (default fail-closed for live mutating actions)

## Credential Setup

No credentials are hardcoded in code.

- Default for OpenClaw/OpenWork usage: local file `conf/webull_profiles.json`
  - Template: `conf/webull_profiles.example.json`
- Optional env-var mode (only if your runtime tool supports env injection):
  - `WEBULL_<PROFILE_TOKEN>_APP_KEY`
  - `WEBULL_<PROFILE_TOKEN>_APP_SECRET`
  - optional: `WEBULL_<PROFILE_TOKEN>_ACCOUNT_ID_HINT`
- Auto profile selection (`--profile auto`) resolves in this order:
  1. `WEBULL_DEFAULT_PROFILE`
  2. configured `prod-us-ref`
  3. the only configured profile
  4. `prod-us-ref` -> `prod-hk-ref` -> first configured profile

### Assistant Onboarding Workflow (OpenClaw/OpenWork)

When user credentials or policy are not ready, do guided setup instead of only asking manual edits:

1. Ask for required fields:
   - profile name (allow custom names, e.g. `my-prod`)
   - app key / app secret
   - env (`uat`/`prod`) + region (`us`/`hk`)
   - optional account id hint
2. Update credential file via wizard:
   - `python3 scripts/webull_config_wizard.py profile`
3. If user wants to tune risk policy, explain key fields and update with:
   - `python3 scripts/webull_config_wizard.py risk`

Profile handling rules:
- Never silently replace user-specified profile with `prod-us-ref`.
- Use exact profile provided by user.
- If user omits profile, prefer `--profile auto` (auto-picks from local configured credentials).

## Environment Routing Overrides

- Runtime routes support `uat/prod` + `us/hk`.
- Documented OpenAPI endpoints:
  - US/Global production: `https://api.webull.com/`
  - US/Global test: `http://us-openapi-alb.uat.webullbroker.com/`
  - HK production: `https://api.webull.hk/`
  - HK sandbox: `https://api.sandbox.webull.hk`
- For HK region, runtime uses `--env uat` as sandbox routing.
- Default route map can be overridden by local file `conf/webull_env_routes.json`:
  - template: `conf/webull_env_routes.example.json`
- Optional env-var mode (only if your runtime tool supports env injection):
  - `WEBULL_OPENAPI_HOST_<ENV>_<REGION>`
  - `WEBULL_OAUTH_HOST_<ENV>_<REGION>`

## Unified Entry

Use one wrapper for all modules:

```bash
python3 scripts/webull_cli.py <module> [module args...]
```

Modules:

- `market` -> `scripts/webull_market_ops.py`
- `trade` -> `scripts/webull_trade_ops.py`
- `auth` -> `scripts/webull_auth_raw.py`

## 1) Market / Instrument / Account Queries

Main script:

```bash
python3 scripts/webull_market_ops.py --profile auto --action <ACTION> [args...]
```

Supported actions:

- instrument:
  - `instrument-stock`
  - `instrument-crypto`
  - `instrument-futures-products`
  - `instrument-futures-list`
  - `instrument-futures-by-code`
  - `instrument-event-series`
  - `instrument-event-list`
- stock:
  - `stock-snapshot`
  - `stock-bars`
  - `stock-batch-bars`
  - `stock-tick`
  - `stock-quotes`
  - `stock-footprint`
- futures:
  - `futures-snapshot`
  - `futures-bars`
  - `futures-tick`
  - `futures-depth`
  - `futures-footprint`
- crypto/event:
  - `crypto-snapshot`
  - `crypto-bars`
  - `event-snapshot`
  - `event-depth`
- account/instrument detail:
  - `account-list`
  - `balance`
  - `position`
  - `trade-calendar`
  - `trade-instrument-detail`
  - `trade-security-detail`
  - `tradeable-instruments`

Examples:

```bash
python3 scripts/webull_market_ops.py --profile auto --action stock-snapshot --symbols AAPL,TSLA --category US_STOCK
python3 scripts/webull_market_ops.py --profile auto --action stock-quotes --symbol AAPL --depth 1
python3 scripts/webull_market_ops.py --profile auto --action futures-snapshot --symbols ESM6 --category US_FUTURES
python3 scripts/webull_market_ops.py --profile auto --action account-list
python3 scripts/webull_market_ops.py --profile auto --action balance
```

## 2) Trade Ops (Full Open)

Main script:

```bash
python3 scripts/webull_trade_ops.py --profile auto --action <ACTION> [args...]
```

Supported actions:

- risk/dry-run:
  - `local-check`
  - `preview`
- common v3:
  - `place`
  - `batch-place`
  - `replace`
  - `cancel`
  - `open`
  - `history`
  - `detail`
- option v2:
  - `option-preview`
  - `option-place`
  - `option-replace`
  - `option-cancel`
- account:
  - `account-list`
  - `balance`
  - `position`

Current defaults are fail-closed:

- `scripts/risk_policy.yaml` has `live.enabled=true`
- `require_confirm_live=true`
- `require_preview_before_live=true`
- `allowed_endpoints` defaults to US + HK documented endpoints
- `--risk-mode` default is `enforce`

Risk and safety behavior:

- Mutating actions require `--confirm-live` by default policy.
- Policy may require preview-before-live for `place` / `batch-place` / `option-place` (`--skip-preview` is ignored when policy enforces preview).
- If multiple accounts are detected:
  - interactive terminal: user is prompted to select one account
  - non-interactive mode: command fails with clear error and asks for `--account-id`
- Mutating output includes:
  - `live_result`
  - `post_trade_check`
  - `trade_outcome` (`success|failure|pending|partial_fill|unknown|not_applicable`)

Examples:

```bash
python3 scripts/webull_trade_ops.py --profile auto --action preview --order-file /path/to/order.json
python3 scripts/webull_trade_ops.py --profile auto --action place --order-file /path/to/order.json
python3 scripts/webull_trade_ops.py --profile auto --action batch-place --order-json '{"batch_orders":[{"combo_type":"NORMAL","client_order_id":"<id1>","instrument_type":"EQUITY","market":"US","symbol":"AAPL","order_type":"MARKET","entrust_type":"QTY","support_trading_session":"N","time_in_force":"DAY","side":"BUY","quantity":"1"}]}'
python3 scripts/webull_trade_ops.py --profile auto --action option-preview --order-file /path/to/option_order.json
python3 scripts/webull_trade_ops.py --profile auto --action option-place --order-file /path/to/option_order.json
python3 scripts/webull_trade_ops.py --profile auto --action cancel --client-order-id "<id>"
python3 scripts/webull_trade_ops.py --profile auto --action option-cancel --client-order-id "<id>"
```

Environment routing:

```bash
python3 scripts/webull_trade_ops.py --profile auto --env prod --region-id us --action account-list
python3 scripts/webull_trade_ops.py --profile uat-doc-1 --env uat --region-id us --action account-list
```

Only use explicit UAT profile examples when UAT credentials are actually configured.

## 3) Raw Auth / Connect API (Signed HTTP)

Main script:

```bash
python3 scripts/webull_auth_raw.py --profile auto --action <ACTION> [args...]
```

Supported actions:

- `auth-create-token`
- `auth-check-token`
- `oauth2-login`
- `oauth2-token`
- `raw-get`
- `raw-post`

Examples:

```bash
python3 scripts/webull_auth_raw.py --profile auto --action auth-check-token --body-json '{"token":"<token>"}'
python3 scripts/webull_auth_raw.py --profile auto --action oauth2-login --query-json '{"response_type":"code","client_id":"<client_id>","redirect_uri":"https://example.com/callback"}'
python3 scripts/webull_auth_raw.py --profile auto --action raw-get --path /openapi/account/list --access-token "<token>"
```

## Output Contract

All module scripts print structured JSON.

- Success:
  - `ok=true` (all modules), with `allow=true` also present in trade ops
- Failure:
  - `ok=false` or `allow=false`
  - includes `status_code`, `detail`, and `payload` when available
- For mutating trade actions (`place/replace/cancel/...`), output includes:
  - `post_trade_check` (order-detail verification by `client_order_id`)
  - `trade_outcome.status` (`success|failure|pending|partial_fill|unknown`)

Exit code:

- `0` success
- `1` failed

Failure reporting:

- For API failures, output includes `status_code`, `detail`, and payload when available.
- For policy/validation failures, output includes specific field-level messages (for example parse/line-column/type constraints).

## Failure Diagnosis Rules (Important)

Before suggesting environment switch (for example `prod -> uat`), classify failure cause first:

- If message contains `Insufficient permission` / `subscribe to stock quotes` / `permission denied`:
  - treat as data-permission issue
  - do **not** suggest switching env by default
- If message contains `HTTP Status: 401` / `UNAUTHORIZED`:
  - treat as env/credential mismatch or auth issue (not DNS)
  - verify profile + env + endpoint mapping first
- If message contains `HTTP Status: 417` / `INVALID_TOKEN`:
  - treat as token/session cache issue
  - suggest clearing `conf/token.txt` or isolating token dir with `WEBULL_OPENAPI_TOKEN_DIR`
- If message contains `Failed to resolve` / `NameResolutionError`:
  - treat as DNS/network issue
  - suggest network/proxy/host-allowlist checks

For smoke reports, prefer `failure_cause` and `stock_quotes_permission` fields when available.

## References

- Capability summary: `memory.md`
- Endpoint/runtime notes: `references/api_reference.md`
