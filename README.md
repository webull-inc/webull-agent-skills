# Webull Agent Skills

This repository is a central place for Webull-related agent skills, runtime scripts, and integration references.
It is designed to help teams ship trading-related agent workflows faster with clear, maintainable skill packages.

## What This Repository Contains

- Reusable Webull-focused skills
- Runnable OpenAPI scripts for local execution
- OpenClaw/OpenWork-ready skill assets and operational docs

## Published Skills

### 1. `webull_api_skills`

Path: [`webull_api_skills/`](./webull_api_skills/)

This skill package includes:
- Unified runtime modules for `market`, `trade`, and `auth`
- Trade workflows with risk controls and post-trade checks
- OpenClaw/OpenWork-ready files (`SKILL.md`, `scripts/`, `conf/`)

Documentation:
- English: [webull_api_skills/README.md](./webull_api_skills/README.md)
- 中文: [webull_api_skills/README.zh-CN.md](./webull_api_skills/README.zh-CN.md)

## OpenClaw / OpenWork Quick Start (`webull_api_skills`)

Note: this section is about using `webull_api_skills` inside OpenClaw/OpenWork.

1. Install the skill from this repository directory.

```text
Install the webull skill from the current directory.
```

2. Configure credentials (`app_key`, `app_secret`) in your profile.
3. Run market/trade/auth tasks through the skill workflow.

For full setup steps and command-level examples, read:
- [webull_api_skills/README.md](./webull_api_skills/README.md)
- [webull_api_skills/README.zh-CN.md](./webull_api_skills/README.zh-CN.md)
