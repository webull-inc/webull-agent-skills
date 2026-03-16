# Webull OpenAPI Runtime Guide

This repository provides runnable Webull OpenAPI scripts and an OpenClaw-ready skill for:
- market / instrument / account queries
- trade operations with risk controls and post-trade checks
- raw signed auth/connect calls

Unified runtime modules:
- `market`
- `trade`
- `auth`

---

## Part 1: Script Quick Start (Run Locally)

### 1. Requirements

- Python 3.10+
- Dependencies:
  - `webull-openapi-python-sdk`
  - `requests`
  - `PyYAML` (recommended for risk YAML)

Install:

```bash
python3 -m pip install -r requirements.txt
```

### 2. Apply for App Key / App Secret

Official docs:
- Authentication Overview: <https://developer.webull.com/apis/docs/authentication/overview>
- Individual Application: <https://developer.webull.com/apis/docs/authentication/individual-app>
- Institution Application: <https://developer.webull.com/apis/docs/authentication/institution-app>

Individual flow:
1. Open `API Management` -> `Individual Application` in Webull Developer.
2. Click `Open an Application` and submit required information.
3. After approval, return to `API Management` and click `Generate Key`.
4. Complete SMS and trading-password verification to generate `App Key` / `App Secret`.

Institution flow:
1. Institution admin submits the request in `Institution Application`.
2. After approval, admin grants OpenAPI permissions (including `Generate Key`) to members.
3. Authorized members generate their own `App Key` / `App Secret`.

### 3. Configure Credentials

#### 3.1 Local file

```bash
cp conf/webull_profiles.example.json conf/webull_profiles.json
```

Fill real `app_key` / `app_secret` in `conf/webull_profiles.json`.

Notes:
- `conf/webull_profiles.json` is gitignored.
- Keep real credentials local only.

#### 3.2 Interactive wizard

```bash
python3 scripts/webull_config_wizard.py profile
```

#### 3.3 Non-interactive setup

```bash
python3 scripts/webull_config_wizard.py profile \
  --non-interactive \
  --name "my-prod" \
  --app-key "<app_key>" \
  --app-secret "<app_secret>" \
  --env prod \
  --region-id us \
  --account-id-hint "<account_id>"
```

### 4. First End-to-End Validation Path

Step 1: account list

```bash
python3 scripts/webull_cli.py market --profile my-prod --env prod --region-id us --action account-list
```

Step 2: balance and position

```bash
python3 scripts/webull_market_ops.py --profile my-prod --env prod --region-id us --action balance --account-id <account_id>
python3 scripts/webull_market_ops.py --profile my-prod --env prod --region-id us --action position --account-id <account_id>
```

Step 3: trade preview (no live mutation)

`order_preview.json`:

```json
{
  "new_orders": [
    {
      "combo_type": "NORMAL",
      "client_order_id": "quickstart_preview_001",
      "symbol": "AAPL",
      "instrument_type": "EQUITY",
      "market": "US",
      "order_type": "MARKET",
      "quantity": "1",
      "support_trading_session": "N",
      "side": "BUY",
      "time_in_force": "DAY",
      "entrust_type": "QTY"
    }
  ]
}
```

```bash
python3 scripts/webull_trade_ops.py \
  --profile my-prod \
  --env prod \
  --region-id us \
  --action preview \
  --order-file ./order_preview.json \
  --account-id <account_id>
```

### 5. Standard Live Trading Flow

Recommended order: `local-check -> preview -> place`

```bash
python3 scripts/webull_trade_ops.py --profile my-prod --action local-check --order-file ./order_live.json
python3 scripts/webull_trade_ops.py --profile my-prod --env prod --region-id us --action preview --order-file ./order_live.json --account-id <account_id>
python3 scripts/webull_trade_ops.py --profile my-prod --env prod --region-id us --action place --order-file ./order_live.json --account-id <account_id> --confirm-live
```

### 6. Extended-Hours Example (ALL Session)

`order_all_session.json`:

```json
{
  "new_orders": [
    {
      "combo_type": "NORMAL",
      "client_order_id": "aapl_limit_all_001",
      "symbol": "AAPL",
      "instrument_type": "EQUITY",
      "market": "US",
      "order_type": "LIMIT",
      "price": "260.60",
      "quantity": "100",
      "support_trading_session": "ALL",
      "side": "BUY",
      "time_in_force": "DAY",
      "entrust_type": "QTY"
    }
  ]
}
```

```bash
python3 scripts/webull_trade_ops.py --profile my-prod --env prod --region-id us --action preview --order-file ./order_all_session.json --account-id <account_id>
python3 scripts/webull_trade_ops.py --profile my-prod --env prod --region-id us --action place --order-file ./order_all_session.json --account-id <account_id> --confirm-live
```

### 7. Useful Commands

Unified entry:

```bash
python3 scripts/webull_cli.py <module> [module args...]
```

Examples:

```bash
python3 scripts/webull_market_ops.py --profile my-prod --action account-list
python3 scripts/webull_trade_ops.py --profile my-prod --action open --account-id <account_id>
python3 scripts/webull_trade_ops.py --profile my-prod --action history --account-id <account_id>
python3 scripts/webull_auth_raw.py --profile my-prod --action auth-check-token --body-json '{"token":"<token>"}'
```

### 8. Output and Risk Contract

- All modules print JSON.
- Key trade fields:
  - `allow` / `ok`
  - `risk.violations`
  - `action_result`
  - `preview_result`
  - `live_result`
  - `post_trade_check`
  - `trade_outcome.status`
- Default risk policy is fail-closed in `scripts/risk_policy.yaml`.

---

## Part 2: Install, Configure, and Run This Skill in OpenClaw

This section provides release-ready operational guidance for OpenClaw deployment and daily use.

### 1. Install the skill in OpenClaw

For released packages, direct installation is enough and no folder exclusion is required.

Example input:

```text
Install the webull skill from the current directory.
```

After installation, the target skill directory typically includes:
- `SKILL.md`
- `requirements.txt`
- `scripts/`
- `conf/`

### 2. Configure App Key / App Secret in OpenClaw (Both Ways Are Valid)

Choose either approach based on preference:
- Option A: enter `app_key` / `app_secret` and profile fields directly in chat, and let OpenClaw update the profile.
- Option B: update via commands (run manually or ask OpenClaw to run them).

#### 2.1 Option A: Update directly in chat

Example input:

```text
Update profile=my-prod with app_key=..., app_secret=..., env=prod, region_id=us, and account_id_hint=...
```

#### 2.2 Option B: Update via commands

Interactive command:

```bash
python3 scripts/webull_config_wizard.py profile
```

Non-interactive command:

```bash
python3 scripts/webull_config_wizard.py profile \
  --non-interactive \
  --name "my-prod" \
  --app-key "<app_key>" \
  --app-secret "<app_secret>" \
  --env prod \
  --region-id us \
  --account-id-hint "<account_id>"
```

### 3. OpenClaw runtime examples

Example A: account and asset checks

Example input:

```text
Query account list, account balance, and positions.
```

Commands:

```bash
python3 scripts/webull_cli.py market --profile my-prod --env prod --region-id us --action account-list
python3 scripts/webull_market_ops.py --profile my-prod --env prod --region-id us --action balance --account-id <account_id>
python3 scripts/webull_market_ops.py --profile my-prod --env prod --region-id us --action position --account-id <account_id>
```

Example B: preview first, then place

Example input:

```text
Submit an all-session AAPL limit order (100 shares @ 260.6): run preview first, then place after confirmation.
```

Commands:

```bash
python3 scripts/webull_trade_ops.py --profile my-prod --env prod --region-id us --action preview --order-file ./order_all_session.json --account-id <account_id>
python3 scripts/webull_trade_ops.py --profile my-prod --env prod --region-id us --action place --order-file ./order_all_session.json --account-id <account_id> --confirm-live
```

Example C: replace fallback to cancel-and-replace

Example input:

```text
Update this order to ALL session. If replace does not update target fields, run cancel-and-replace automatically and verify.
```

Suggested execution flow:
1. run `replace`
2. verify via `detail` / `open`
3. if unchanged, run `cancel` then `place` with a new `client_order_id`

### 4. OpenClaw Usage Examples (More Scenarios)

Example 1: discover and choose an account

```text
Query account-list, format account_id options in a table, and suggest the best account_id for this task.
```

Example 2: asset snapshot

```text
Use account_id=<id> to query balance and position, output a 3-line summary first, then attach raw JSON.
```

Example 3: safe order execution

```text
Execute local-check -> preview -> place for this order; stop on any failure and provide next-step advice.
```

Example 4: replace fallback policy

```text
Modify this order to ALL session; if replace result is unchanged, automatically run cancel-and-replace and verify.
```

### 5. Practical Tips

- Keep `uat` and `prod` credentials isolated.
- Always execute `local-check -> preview -> place` for live mutations.
- Never commit real `app_secret`, account IDs, or tokens.
- Treat `conf/webull_profiles.json` as local secret material.
