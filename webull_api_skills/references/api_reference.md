# Webull OpenAPI Reference (Skill Runtime)

This file is the runtime-oriented reference for this skill.

## Runtime Architecture

- Primary execution path: Webull Python SDK (`DataClient`, `TradeClient`, `DataStreamingClient`)
- Fallback execution path: signed raw HTTP only for:
  - `auth-create-token`
  - `auth-check-token`
  - `oauth2-login`
  - `oauth2-token`

Reason: current sample set in `requests_reference/` does not show dedicated SDK wrappers for those auth/connect REST paths.

## Auth Model Notes

- SDK auth model and raw WebAPI auth model are not identical.
- CLI default behavior for SDK commands:
  - does **not** auto-inject `WEBULL_ACCESS_TOKEN` into `ApiClient`
  - expects SDK/token-dir style auth unless explicitly overridden
- To force SDK to use access token injection, enable:
  - `--sdk-use-access-token`
  - or env `WEBULL_SDK_USE_ACCESS_TOKEN=true`

## Official Docs

- Webull Open API reference root:
  - https://developer.webull.com/apis/docs/webull-open-api-reference
- Authentication:
  - https://developer.webull.com/apis/docs/reference/auth-token-create
  - https://developer.webull.com/apis/docs/reference/auth-token-check
- Trading API overview:
  - https://developer.webull.com/apis/docs/reference/custom/trading-api
- Market Data API overview:
  - https://developer.webull.com/apis/docs/reference/custom/market-data-api
- HK Trading API docs:
  - https://developer.webull.hk/apis/docs/trade-api/account

## Python SDK Repos

- OpenAPI Python SDK:
  - https://github.com/webull-inc/webull-openapi-python-sdk
- OAuth2 SDK:
  - https://github.com/webull-inc/oauth2-authentication-sdk

## Runtime Hosts

- US/Global production OpenAPI (REST): `https://api.webull.com`
- US/Global test OpenAPI (REST): `http://us-openapi-alb.uat.webullbroker.com`
- HK production OpenAPI (REST): `https://api.webull.hk`
- HK sandbox OpenAPI (REST): `https://api.sandbox.webull.hk`
- US/Global OAuth2 (test): `https://us-oauth-open-api.uat.webullbroker.com`

## Required Headers (Raw Fallback Path Only)

- `x-app-key`
- `x-signature-algorithm` (`HMAC-SHA1`)
- `x-signature-version` (`1.0`)
- `x-signature-nonce`
- `x-timestamp`
- `x-signature`
- `x-version` (`v2`)
- `x-access-token` (most business APIs)

## Signature Notes (Raw Fallback Path Only, Implemented in `scripts/webull_auth_raw.py`)

Signature source uses:

1. URI path (for example `/openapi/account/list`)
2. Sorted key/value concat of URL query + signing headers + `host`
3. Optional uppercase MD5 of JSON body

Then:

- URL-encode source string
- HMAC-SHA1 with key `${app_secret}&`
- Base64 encode result as `x-signature`

Unified entrypoint `scripts/webull_cli.py` can dispatch to:

- `market` -> `scripts/webull_market_ops.py`
- `trade` -> `scripts/webull_trade_ops.py`
- `auth` -> `scripts/webull_auth_raw.py`

Test-only smoke checks are located at `test/webull_smoke.py`.

## Endpoint Map Used by CLI

### Auth / Connect

- `POST /openapi/auth/token/create`
- `POST /openapi/auth/token/check`
- `GET /oauth2/authenticate/login`
- `POST /openapi/oauth2/token`

### Account / Assets

- `GET /openapi/account/list`
- `GET /openapi/assets/balance`
- `GET /openapi/assets/positions`

### Instrument

- `GET /openapi/instrument/stock/list`
- `GET /openapi/instrument/crypto/list`
- `GET /openapi/instrument/futures/products`
- `GET /openapi/instrument/futures/by-code`
- `GET /openapi/instrument/futures/list`
- `GET /openapi/instrument/event/series/list`
- `GET /openapi/instrument/event/market/list`

### Market Data

- `GET /openapi/market-data/stock/tick`
- `GET /openapi/market-data/stock/snapshot`
- `GET /openapi/market-data/stock/quotes`
- `GET /openapi/market-data/stock/footprint`
- `GET /openapi/market-data/stock/bars`
- `GET /openapi/market-data/stock/batch-bars`
- `GET /openapi/market-data/futures/tick`
- `GET /openapi/market-data/futures/snapshot`
- `GET /openapi/market-data/futures/footprint`
- `GET /openapi/market-data/futures/depth`
- `GET /openapi/market-data/futures/bars`
- `GET /openapi/market-data/crypto/snapshot`
- `GET /openapi/market-data/event/snapshot`
- `GET /openapi/market-data/event/depth`
- `GET /openapi/market-data/crypto/bars`

### Trading (Common)

- `GET /openapi/trade/order/open`
- `GET /openapi/trade/order/history`
- `GET /openapi/trade/order/detail`
- `POST /openapi/trade/order/preview`
- `POST /openapi/trade/order/place`
- `POST /openapi/trade/order/replace`
- `POST /openapi/trade/order/cancel`
- `POST /openapi/trade/order/batch-place`

### Trading (Stock)

- `POST /openapi/trade/stock/order/preview`
- `POST /openapi/trade/stock/order/place`
- `POST /openapi/trade/stock/order/replace`
- `POST /openapi/trade/stock/order/cancel`

### Trading (Option)

- `POST /openapi/trade/option/order/preview`
- `POST /openapi/trade/option/order/place`
- `POST /openapi/trade/option/order/replace`
- `POST /openapi/trade/option/order/cancel`

### Streaming

- `POST /openapi/market-data/streaming/subscribe`
- `POST /openapi/market-data/streaming/unsubscribe`

## Rate Limit Highlights

- Auth create/check: `10 requests / 30 seconds`
- Assets balance/positions: `2 requests / 2 seconds`
- Common preview: `150 requests / 10 seconds`
- Place/replace/cancel: `600 requests / minute`
- Open/history/detail: `2 requests / 2 seconds`
- Most market data: `600 requests / minute`

For full rate and schema details, cross-check with `memory.md` and official endpoint pages.
