# ClawBot Tom - OpenClaw Project

## What is this?
This project uses **OpenClaw** (formerly Clawdbot/Moltbot), an open-source self-hosted AI agent platform.
OpenClaw acts as a gateway between messaging channels and LLM backends, enabling autonomous AI agents
that can execute shell commands, write code, control browsers, and perform real-world tasks.

## Setup
- **OpenClaw version**: 2026.2.9 (installed globally via npm)
- **LLM backend**: OpenRouter (openrouter/auto model)
- **Gateway**: localhost:18789 (loopback bind)
- **Config file**: `~/.openclaw/openclaw.json`
- **Workspace**: `~/.openclaw/workspace/`
- **Node manager**: npm

## How to start the gateway
```bash
# Start gateway (foreground)
openclaw gateway run

# Check status
openclaw gateway status

# Dashboard
# Open http://127.0.0.1:18789/ in browser
```

## Key directories
- `~/.openclaw/` - Config directory
- `~/.openclaw/workspace/` - Agent workspace (files created by agent)
- `~/.openclaw/workspace/skills/` - Custom skills
- `~/.openclaw/agents/` - Agent sessions
- `~/.openclaw/canvas/` - Canvas files

## Web UI
- **File**: `web_ui.py` — thin frontend that proxies all requests through the OpenClaw gateway
- **Start**: `start.bat` (opens browser + starts server on port 5000)
- **Stop**: `stop.bat`
- **Architecture**: Web UI → OpenClaw Gateway (localhost:18789) → ClawBot Agent → reddit-scanner skill
- The web UI does NOT call Python scripts directly — all search/login goes through the agent

## Custom Skills

### reddit-scanner
- **Location**: `~/.openclaw/workspace/skills/reddit-scanner/`
- **Scripts**: `scripts/reddit_scan.py` (search), `scripts/reddit_login.py` (login), `scripts/reddit_auth.py` (session management)
- **Purpose**: Scans Reddit for posts/comments about specific topics. Used for market research and lead generation. Also supports Reddit login (browser-based, saves cookies for future use).
- **No API key needed** — uses PullPush + Arctic Shift + Reddit public APIs
- **Run with `python`** (not `python3` — Windows)
- **Interface**: Web UI (localhost:5000) + ClawBot agent chat

## Notes
- Gateway service (daemon) not installed (requires admin PowerShell)
- To install daemon: run `openclaw gateway install` from elevated PowerShell
- Windows native support is experimental; WSL2 available as fallback
- The `gateway status` probe may show "token mismatch" on Windows - this is cosmetic; the gateway works fine
