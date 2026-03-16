#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${ROOT_DIR}/dist"
STAMP="$(date +%Y%m%d_%H%M%S)"
PACKAGE_BASENAME="${1:-webull_openapi_skill}"
OUT_FILE="${DIST_DIR}/${PACKAGE_BASENAME}_${STAMP}.tar.gz"

mkdir -p "${DIST_DIR}"

INCLUDE_PATHS=(
  "README.md"
  "README.zh-CN.md"
  "SKILL.md"
  "requirements.txt"
  ".gitignore"
  "scripts/webull_cli.py"
  "scripts/webull_market_ops.py"
  "scripts/webull_trade_ops.py"
  "scripts/webull_auth_raw.py"
  "scripts/webull_config_wizard.py"
  "scripts/webull_profiles.py"
  "scripts/webull_env_router.py"
  "scripts/webull_runtime.py"
  "scripts/risk_policy.yaml"
  "conf/webull_profiles.example.json"
  "conf/webull_env_routes.example.json"
)

pushd "${ROOT_DIR}" >/dev/null
tar -czf "${OUT_FILE}" "${INCLUDE_PATHS[@]}"
popd >/dev/null

echo "Release bundle created: ${OUT_FILE}"
