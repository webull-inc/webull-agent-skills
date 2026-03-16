This repository hosts Webull-related Agent Skills to help you quickly integrate common trading workflows and API capabilities.  
The first published skill is [Webull API Skill (English README)](./webull_api_skills/README.md) (you can also read the [中文说明](./webull_api_skills/README.zh-CN.md)).  
More skills will be added over time in dedicated subdirectories for easier maintenance and iteration.

## OpenCode / OpenClaw: Install and Update

This section is for installing/updating **OpenCode/OpenClaw itself** (not this skill repository).

### OpenCode

Install:

```bash
curl -fsSL https://opencode.ai/install | bash
```

Update:

```bash
opencode upgrade
```

Official docs: https://opencode.ai/docs

### OpenClaw

Install:

```bash
curl -fsSL https://openclaw.ai/install.sh | bash
```

Update:

```bash
openclaw update
```

Alternative update path (officially recommended): re-run installer

```bash
curl -fsSL https://openclaw.ai/install.sh | bash
```

Official docs:
- https://docs.openclaw.ai/install
- https://docs.openclaw.ai/install/updating

For complete setup and runtime examples:
- English: [webull_api_skills/README.md](./webull_api_skills/README.md)
- 中文: [webull_api_skills/README.zh-CN.md](./webull_api_skills/README.zh-CN.md)
