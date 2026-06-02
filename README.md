# ⚠️ DEPRECATED — This project is no longer maintained

> **This repository has been deprecated and will be archived soon.**
>
> All development has moved to the new repository: **[webull-openapi-skills](https://github.com/webull-inc/webull-openapi-skills)**
>
> Please migrate to the new project for continued support, bug fixes, and new features.
> No further updates will be made to this repository.

---

# Webull OpenAPI Skill

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)

AI agent skill for [Webull OpenAPI](https://developer.webull.com) — enables AI assistants to trade stocks, options, futures, crypto, and event contracts, query market data, and manage accounts via CLI.

Built on the official [webull-openapi-python-sdk](https://github.com/webull-inc/webull-openapi-python-sdk). Supports US and HK regions with configurable risk controls.

---

## ⚠️ Disclaimer

The information provided by this tool is for reference only and does not constitute investment advice. Trading involves risk; please make decisions carefully.

See [DISCLAIMER.md](DISCLAIMER.md) for the full disclaimer.

---

## Features

- **Multi-Region Support** — US and HK regions with region-specific order types, trading sessions, and validation
- **Market Data** — Real-time snapshots, tick data, quotes (depth), footprint, and OHLCV bars for stocks, futures, crypto, and event contracts
- **Trading** — Place, modify, cancel orders for stocks, options, futures, crypto, and event contracts
- **Combo Orders** — OTO, OCO, OTOCO combo orders (US only)
- **Option Strategies** — Multi-leg option strategies: vertical, straddle, strangle, butterfly, condor, etc. (US only)
- **Algo Orders** — TWAP, VWAP, POV algorithmic orders (US only)
- **Risk Controls** — Market-specific notional limits (USD/HKD/CNH), quantity limits, symbol whitelist
- **Auto Account Resolution** — Automatically selects the correct account based on asset type
- **Audit Logging** — All order operations are logged for compliance
- **2FA Support** — Interactive authentication flow for accounts with Two-Factor Authentication
- **Region-Aware Disclaimer** — Output includes region-appropriate disclaimer (English for US, trilingual for HK)

---

## Example Prompts

Here are some prompts you can use with your AI assistant:

**Market Data**
- Show me AAPL's daily bars for the last 5 days
- Get a real-time snapshot for AAPL, MSFT, and GOOGL
- What's the current bid/ask for TSLA?

**Account & Portfolio**
- What's my account balance and buying power?
- Show me all my current positions
- List all my linked accounts

**Stock Trading**
- Place a limit order to buy 100 shares of AAPL at $250
- Place a market order to sell 50 shares of TSLA
- Short 10 shares of NVDA at $120

**Options Trading**
- Buy 1 AAPL call option, strike $250, expiring 2026-04-17, limit price $5.00

**Order Management**
- Show me my order history for the last 7 days
- Cancel order with ID abc123

---

## Prerequisites

1. **Webull Developer Account** — Register at:
   - US: [developer.webull.com](https://developer.webull.com/apis/home)
   - HK: [developer.webull.hk](https://developer.webull.hk/apis/home)
2. **API Credentials** — Obtain your `App Key` and `App Secret`
3. **Market Data Subscription** — Subscribe to quotes for market data access:
   - US: [webullapp.com/quote](https://www.webullapp.com/quote) | [Guide](https://developer.webull.com/apis/docs/market-data-api/subscribe-quotes)
   - HK: [webullapp.hk/quote](https://www.webullapp.hk/quote) | [Guide](https://developer.webull.hk/apis/docs/market-data-api/subscribe-quotes)
4. **Python 3.10+**

> **Note:** On macOS/Linux use `python3`, on Windows use `python`. All examples in this README use `python3`.

---

## Installation

```bash
git clone https://github.com/webull-inc/webull-agent-skills.git
cd webull-agent-skills
pip install -e .
```

Or with dev dependencies:

```bash
pip install -e ".[dev]"
```

---

## Quick Start

### 1. Configure Credentials

```bash
cp .env.example .env
# Edit .env — fill in WEBULL_APP_KEY and WEBULL_APP_SECRET
```

> To keep credentials outside the project directory, set `WEBULL_CONFIG_DIR` to any path (e.g. `~/.config/webull-skill`) and place your `.env` there.

### 2. Authenticate (when token is missing or expired)

```bash
python3 webull_openapi_skills/scripts/cli.py auth
# Approve the 2FA request in your Webull mobile app
```

### 3. Use It

```bash
# List accounts
python3 webull_openapi_skills/scripts/cli.py trading --action account-list

# Stock snapshot
python3 webull_openapi_skills/scripts/cli.py market-data --action stock-snapshot --symbols AAPL,TSLA

# Place an order
python3 webull_openapi_skills/scripts/cli.py trading --action place --account-id <id> \
  --order-json '{"symbol":"AAPL","side":"BUY","order_type":"LIMIT","limit_price":"180","quantity":"10","instrument_type":"EQUITY","market":"US","time_in_force":"DAY","entrust_type":"QTY","support_trading_session":"CORE","combo_type":"NORMAL"}'
```

---

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `WEBULL_APP_KEY` | App Key (required) | — |
| `WEBULL_APP_SECRET` | App Secret (required) | — |
| `WEBULL_ENVIRONMENT` | `uat` (sandbox) or `prod` | `uat` |
| `WEBULL_REGION_ID` | `us` or `hk` | `us` |
| `WEBULL_MAX_ORDER_NOTIONAL_USD` | Max order value for US market (USD) | `10000` |
| `WEBULL_MAX_ORDER_NOTIONAL_HKD` | Max order value for HK market (HKD) | `80000` |
| `WEBULL_MAX_ORDER_NOTIONAL_CNH` | Max order value for CN market (CNH) | `70000` |
| `WEBULL_MAX_ORDER_QUANTITY` | Max order quantity | `1000` |
| `WEBULL_SYMBOL_WHITELIST` | Allowed symbols (comma-separated) | (no restriction) |
| `WEBULL_CONFIG_DIR` | Custom config directory for `.env` and token files | (none) |
| `WEBULL_TOKEN_DIR` | Token storage directory | `<project_root>/conf/` |
| `WEBULL_AUDIT_LOG_FILE` | Audit log file path | stderr only |
| `WEBULL_LOG_LEVEL` | SDK log level | `WARNING` |

> **Note:** `WEBULL_REGION_ID=us` represents **Webull US** ([developer.webull.com](https://developer.webull.com/apis/home)), and `WEBULL_REGION_ID=hk` represents **Webull Hong Kong** ([developer.webull.hk](https://developer.webull.hk/apis/home)).

See [webull_openapi_skills/.env.example](webull_openapi_skills/.env.example) for full configuration template.

---

## Available Actions

### Market Data

| Category | Actions | Region |
|----------|---------|--------|
| **Stock** | `stock-snapshot`, `stock-bars`, `stock-batch-bars`, `stock-tick`, `stock-quotes`, `stock-footprint` | US, HK |
| **Futures** | `futures-snapshot`, `futures-bars`, `futures-tick`, `futures-depth`, `futures-footprint` | US |
| **Crypto** | `crypto-snapshot`, `crypto-bars` | US |
| **Event** | `event-snapshot`, `event-depth`, `event-bars`, `event-tick` | US |

### Trading

| Category | Actions | Region |
|----------|---------|--------|
| **Account** | `account-list` | US, HK |
| **Assets** | `balance`, `position` | US, HK |
| **Instrument** | `instrument-stock`, `instrument-crypto`, `instrument-futures-products`, `instrument-futures-list`, `instrument-futures-by-code`, `instrument-event-series`, `instrument-event-list`, `instrument-event-categories`, `instrument-event-events` | varies |
| **Stock Order** | `place`, `preview`, `replace` | US, HK |
| **Combo Order** | `batch-place` (OTO/OCO/OTOCO) | US |
| **Option Order** | `option-place`, `option-preview`, `option-replace`, `option-strategy-place` | US, HK |
| **Algo Order** | `algo-place` (TWAP/VWAP/POV) | US |
| **Futures Order** | `futures-place`, `futures-replace` | US |
| **Crypto Order** | `crypto-place` | US |
| **Event Order** | `event-place`, `event-replace` | US |
| **Order Mgmt** | `cancel`, `open`, `history`, `detail`, `local-check` | US, HK |

### Region Differences

| Feature | US | HK |
|---------|:--:|:--:|
| Stock/Option Trading | ✅ | ✅ |
| Futures Trading | ✅ | ❌ |
| Crypto Trading | ✅ | ❌ |
| Event Contracts | ✅ | ❌ |
| Combo Orders | ✅ | ❌ |
| Option Strategies | ✅ | ❌ |
| Algo Orders | ✅ | ❌ |
| Markets | US | US, HK, CN |

---

## Security

- **Never share your AK/SK with AI models** — Do not paste your App Key or App Secret into chat prompts, AI assistants, or any LLM conversation. These credentials should only be configured via environment variables or `.env` files, never exposed in plain text to the model.
- **Credential isolation** — AK/SK are used only inside the SDK client process for initialization and request signing. They never appear in tool outputs, logs, or error messages.
- **Audit logging** — All order operations are logged with sanitized parameters (credentials stripped, prices masked) for compliance tracking.
- **Review before trading** — Always review order details proposed by the AI before confirming. Use `preview` actions before placing orders.
- **Default sandbox** — The skill defaults to UAT (sandbox) environment. You must explicitly set `WEBULL_ENVIRONMENT=prod` for live trading.
- **Risk controls** — Configurable notional limits, quantity limits, and symbol whitelist prevent accidental large orders.

---

## Troubleshooting

### 2FA Authentication Required

```bash
python3 webull_openapi_skills/scripts/cli.py auth
# Approve in Webull app, then re-run your command
```

### Device Not Registered

1. Open Webull mobile app → log in with your API account → complete device registration
2. Run `python3 webull_openapi_skills/scripts/cli.py auth`

### Market Data 401/403

Subscribe to quotes:
- US: [webullapp.com/quote](https://www.webullapp.com/quote) | [Guide](https://developer.webull.com/apis/docs/market-data-api/subscribe-quotes)
- HK: [webullapp.hk/quote](https://www.webullapp.hk/quote) | [Guide](https://developer.webull.hk/apis/docs/market-data-api/subscribe-quotes)

### Token Expired

```bash
rm -rf conf/token.txt
python3 webull_openapi_skills/scripts/cli.py auth
```

---

## Project Structure

```
webull-agent-skills/
├── pyproject.toml              # Package configuration
├── .env.example                # Configuration template
├── DISCLAIMER.md               # Risk disclaimer
├── LICENSE
├── README.md                   # This file
├── webull_openapi_skills/
│   ├── SKILL.md                # Skill metadata for AI agents
│   ├── scripts/
│   │   ├── cli.py              # CLI entry point
│   │   ├── config.py           # Configuration management
│   │   ├── sdk_client.py       # Webull SDK adapter
│   │   ├── audit.py            # Audit logging
│   │   ├── errors.py           # Error handling
│   │   ├── formatters.py       # Response formatting (region-aware)
│   │   ├── guards.py           # Order validation
│   │   ├── constants.py        # Enum constants
│   │   ├── region_config.py    # Region-specific settings
│   │   ├── risk_engine.py      # Risk limit checks
│   │   ├── env_router.py       # Endpoint routing
│   │   ├── result.py           # Structured JSON output
│   │   ├── runtime.py          # SDK logging control
│   │   ├── trading/            # Account, asset, instrument, order modules
│   │   └── market_data/        # Stock, futures, crypto, event modules
│   ├── references/             # API reference docs
│   └── tests/                  # Unit tests
└── conf/                       # Token storage (gitignored)
```

---

## Related Projects

- [webull-openapi-python-sdk](https://github.com/webull-inc/webull-openapi-python-sdk) — Official Python SDK
- [webull-mcp-server](https://github.com/webull-inc/webull-mcp-server) — MCP server for AI assistants

## Documentation

- US API: https://developer.webull.com/apis/docs
- HK API: https://developer.webull.hk/apis/docs
- US LLM-friendly: https://developer.webull.com/apis/llms.txt
- HK LLM-friendly: https://developer.webull.hk/apis/llms.txt

## License

Apache License 2.0 — see [LICENSE](LICENSE) for details.
