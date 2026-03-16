# Webull OpenAPI 运行文档

[English](README.md) | 简体中文

本仓库提供 Webull OpenAPI 的可运行脚本与 OpenClaw Skill，覆盖：
- 行情 / 标的 / 账户查询
- 带风控与交易后校验的交易操作
- 原始签名方式的 auth/connect 接口调用

统一入口模块：
- `market`
- `trade`
- `auth`

---

## 第一部分：脚本上手使用（本地直接运行）

### 1. 环境准备

- Python 3.10+
- 依赖：
  - `webull-openapi-python-sdk`
  - `requests`
  - `PyYAML`（建议安装，用于风险策略 YAML）

安装依赖：

```bash
python3 -m pip install -r requirements.txt
```

### 2. 申请 App Key / App Secret

官方文档：
- Authentication Overview: <https://developer.webull.com/apis/docs/authentication/overview>
- Individual Application: <https://developer.webull.com/apis/docs/authentication/individual-app>
- Institution Application: <https://developer.webull.com/apis/docs/authentication/institution-app>

个人开发者（Individual）流程：
1. 登录 Webull Developer，进入 `API Management` -> `Individual Application`。
2. 点击 `Open an Application`，填写信息并提交。
3. 审核通过后，在 `API Management` 点击 `Generate Key`。
4. 完成短信验证码与交易密码验证，生成 `App Key` / `App Secret`。

机构开发者（Institution）流程：
1. 机构管理员在 `Institution Application` 提交资料。
2. 审核通过后，管理员在 `API Management` 授权成员 OpenAPI 权限（含 `Generate Key`）。
3. 成员在自己的账号下生成 `App Key` / `App Secret`。

### 3. 配置凭证

#### 3.1 本地文件方式

```bash
cp conf/webull_profiles.example.json conf/webull_profiles.json
```

将真实 `app_key` / `app_secret` 写入 `conf/webull_profiles.json`。

说明：
- `conf/webull_profiles.json` 已被 `.gitignore` 忽略。
- 请仅本地保存，避免提交真实凭证。

#### 3.2 交互式配置

```bash
python3 scripts/webull_config_wizard.py profile
```

向导会提示你填写：
- `profile name`
- `app_key`
- `app_secret`
- `env`
- `region_id`
- `endpoint`（可空）
- `account_id_hint`（可空）

#### 3.3 非交互式配置（适合自动化）

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

### 4. 首次联调最短链路

#### 步骤 1：查询账户列表

```bash
python3 scripts/webull_cli.py market --profile my-prod --env prod --region-id us --action account-list
```

#### 步骤 2：查询余额与持仓

```bash
python3 scripts/webull_market_ops.py --profile my-prod --env prod --region-id us --action balance --account-id <account_id>
python3 scripts/webull_market_ops.py --profile my-prod --env prod --region-id us --action position --account-id <account_id>
```

#### 步骤 3：先做交易预演（不下实单）

创建 `order_preview.json`：

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

执行预演：

```bash
python3 scripts/webull_trade_ops.py \
  --profile my-prod \
  --env prod \
  --region-id us \
  --action preview \
  --order-file ./order_preview.json \
  --account-id <account_id>
```

### 5. 标准交易流程（推荐顺序）

固定顺序：`local-check -> preview -> place`

1. 本地校验：

```bash
python3 scripts/webull_trade_ops.py --profile my-prod --action local-check --order-file ./order_live.json
```

2. 服务端预演：

```bash
python3 scripts/webull_trade_ops.py --profile my-prod --env prod --region-id us --action preview --order-file ./order_live.json --account-id <account_id>
```

3. 实盘下单：

```bash
python3 scripts/webull_trade_ops.py --profile my-prod --env prod --region-id us --action place --order-file ./order_live.json --account-id <account_id> --confirm-live
```

### 6. 全时段订单示例（盘前/盘后）

盘前/盘后建议使用限价单，`support_trading_session` 设为 `ALL`。

`order_all_session.json`：

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

### 7. 常用命令速查

统一入口：

```bash
python3 scripts/webull_cli.py <module> [module args...]
```

常见动作：

```bash
python3 scripts/webull_market_ops.py --profile my-prod --action account-list
python3 scripts/webull_trade_ops.py --profile my-prod --action open --account-id <account_id>
python3 scripts/webull_trade_ops.py --profile my-prod --action history --account-id <account_id>
python3 scripts/webull_auth_raw.py --profile my-prod --action auth-check-token --body-json '{"token":"<token>"}'
```

### 8. 输出与风控约定

- 所有模块输出 JSON。
- 交易结果重点字段：
  - `allow` / `ok`
  - `risk.violations`
  - `action_result`
  - `preview_result`
  - `live_result`
  - `post_trade_check`
  - `trade_outcome.status`
- 默认风险策略为失败闭合（`scripts/risk_policy.yaml`），生产变更需显式 `--confirm-live`。

---

## 第二部分：在 OpenClaw 中安装、配置与运行 Skill

本节用于正式部署和团队复用，提供标准安装、凭证配置和运行示例。

### 1. 在 OpenClaw 安装 Skill

发布包场景下可直接安装，无需排除子目录。

示例输入：

```text
请直接安装当前目录中的 webull skill。
```

安装完成后，目标 Skill 目录通常包含：
- `SKILL.md`
- `requirements.txt`
- `scripts/`
- `conf/`

### 2. 在 OpenClaw 配置 App Key / App Secret（两种方式都可以）

可以根据习惯任选其一：
- 方式 A：在对话框直接输入 `app_key` / `app_secret` 等信息，由助手代为更新 profile。
- 方式 B：使用命令方式更新（可手动执行，也可让助手代执行）。

#### 2.1 方式 A：对话框直接更新

示例输入：

```text
请把 profile=my-prod 更新为以下凭证：app_key=...，app_secret=...，env=prod，region_id=us，account_id_hint=...
```

#### 2.2 方式 B：命令方式更新

交互式命令：

```bash
python3 scripts/webull_config_wizard.py profile
```

非交互式命令：

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

### 3. OpenClaw 运行示例

#### 示例 A：账户与资产查询

示例输入：

```text
查询账户列表、账户余额和持仓信息。
```

对应执行命令：

```bash
python3 scripts/webull_cli.py market --profile my-prod --env prod --region-id us --action account-list
python3 scripts/webull_market_ops.py --profile my-prod --env prod --region-id us --action balance --account-id <account_id>
python3 scripts/webull_market_ops.py --profile my-prod --env prod --region-id us --action position --account-id <account_id>
```

#### 示例 B：先 preview，再 place

示例输入：

```text
提交 AAPL 全时段限价单（100 股，260.6），先执行 preview，确认后再 place。
```

对应执行命令：

```bash
python3 scripts/webull_trade_ops.py --profile my-prod --env prod --region-id us --action preview --order-file ./order_all_session.json --account-id <account_id>
python3 scripts/webull_trade_ops.py --profile my-prod --env prod --region-id us --action place --order-file ./order_all_session.json --account-id <account_id> --confirm-live
```

#### 示例 C：改单与撤单重下策略

示例输入：

```text
将订单修改为 ALL 时段；若 replace 后目标字段未更新，则自动执行撤单重下并回查确认。
```

建议执行顺序：
1. 执行 `replace`
2. 通过 `detail` / `open` 回查目标字段
3. 若不满足预期，执行 `cancel` + 新 `client_order_id` 重新 `place`

### 4. OpenClaw 使用示例（更多场景）

示例 1：账户发现与选择

```text
先查询 account-list，并把可用 account_id 按用途做成表格，最后给出建议使用的 account_id。
```

示例 2：资产快照

```text
使用 account_id=<id> 查询 balance 和 position，先给 3 行摘要，再附原始 JSON。
```

示例 3：安全下单流程

```text
按 local-check -> preview -> place 执行这笔订单；任一步失败就停止，并给出下一步建议。
```

示例 4：改单失败回退策略

```text
将订单改为 ALL 时段；如果 replace 后字段无变化，自动执行撤单重下并回查确认。
```

### 5. 使用小贴士

- `uat` 与 `prod` 使用隔离凭证。
- 每次实盘变更固定执行：`local-check -> preview -> place`。
- 禁止提交真实 `app_secret`、账户信息、token。
- 将 `conf/webull_profiles.json` 作为本地机密文件管理。
