# Reddit Filter

Search Reddit posts and comments by keyword, then let an LLM drop the results that only *mention* your words without actually being about your topic.

Useful for market research, lead generation, or tracking discussion of a product or niche, where plain keyword search returns lots of noise.

- **No Reddit API key needed.** Results come from Reddit's public `.json` endpoints, [PullPush](https://pullpush.io) and [Arctic Shift](https://arctic-shift.photon-reddit.com).
- **AI relevance filter.** Results are sent in batches to an LLM through [OpenRouter](https://openrouter.ai), which keeps only the relevant ones. If too few pass, it fetches more until it reaches your limit (or a time cap).
- **Local web UI.** Search form, saved searches and result cards at `http://localhost:5000`.
- **Command line too.** `scripts/reddit_scan.py` works on its own and can output text or JSON.

## Requirements

- Windows (the helper `.bat` scripts are Windows-only; the Python code itself is cross-platform)
- Python 3.9+ (`install.bat` downloads Python 3.12 if none is found)
- An [OpenRouter API key](https://openrouter.ai/keys) for the AI filter
- Playwright + Chromium, only for the optional Reddit login (installed by `install.bat`)

## Quick start

1. **Install:** double-click `install.bat`. It checks for Python, then installs Playwright and Chromium.
2. **Set your OpenRouter key:**
   ```bat
   setx OPENROUTER_API_KEY "sk-or-..."
   ```
   Open a new terminal afterwards so the variable is picked up.
3. **Start:** double-click `start.bat`. The server starts and your browser opens `http://localhost:5000`.
4. **Stop:** run `stop.bat` (it kills whatever is listening on port 5000).

## Using the web UI

| Control | Options |
|---|---|
| Query | Keywords or a short description of what you're looking for |
| Time | Past hour / 24h / week / month / year / all time |
| Sort | Relevance, new, hot, top, comments |
| Search posts / comments | Either or both |
| Limit | Number of relevant results to return (1–100) |

The web UI always applies the AI filter. Click a result card to open it on Reddit. Use **+ Save** to keep a search as a preset chip (stored in `presets.json`).

The bar at the top shows whether a Reddit account is logged in. Logging in opens a Chromium window where you sign in manually. The cookies are saved to `reddit_session.json`, which is git-ignored.

## Command line

```bash
python scripts/reddit_scan.py "standing desk recommendations" --time month --limit 50 --filter
```

| Flag | Description | Default |
|---|---|---|
| `query` | Search keywords | (required) |
| `-t`, `--time` | `hour`, `day`, `week`, `month`, `year`, `all` | `week` |
| `--sort` | `relevance`, `new`, `hot`, `top`, `comments` | `relevance` |
| `-n`, `--limit` | Max results (1–500) | `25` |
| `--min-score` | Skip results below this score | `0` |
| `--deep` | Search comments as well as posts | off |
| `--comments-only` | Search comments only | off |
| `--filter` | Apply the LLM relevance filter (needs an OpenRouter key) | off |
| `--json` | Print JSON instead of text | off |
| `-o`, `--output` | Write JSON results to a file | stdout |

Progress and errors go to stderr, results to stdout, so `--json` output can be piped straight into other tools.

## Configuration

| Environment variable | Purpose | Default |
|---|---|---|
| `OPENROUTER_API_KEY` | API key for the relevance filter | (none) |
| `OPENROUTER_MODEL` | OpenRouter model used for filtering | `moonshotai/kimi-k2.5` |

If `OPENROUTER_API_KEY` isn't set, the scanner looks for an OpenRouter key in an OpenClaw config (`~/.openclaw/agents/main/agent/auth-profiles.json`).

## How the filter works

1. Fetch a batch of posts/comments matching the query.
2. Drop results already seen.
3. Send them to the LLM in batches of 50, asking which are relevant to the query; keep only those.
4. If fewer than `limit` are kept, fetch older results and repeat. The next batch size is based on how many passed last time.
5. Stop at `limit` results, after 10 rounds, or after a time limit of about 3 minutes per 25 results (minimum 60 s).

## Project structure

```
web_ui.py               Local web server and UI (port 5000)
scripts/
  reddit_scan.py        Search + LLM filter (also a standalone CLI)
  reddit_login.py       Login / status / logout CLI used by the web UI
  reddit_auth.py        Playwright login and session cookie storage
presets.json            Saved searches
docs.html               Architecture notes
install.bat             One-time setup
start.bat / stop.bat    Start and stop the web UI
```

Runtime files (`scanner.log`, `reddit_session.json`) are created next to `web_ui.py` and are git-ignored.

## Troubleshooting

- **"Filter error: No OpenRouter API key found"**: set `OPENROUTER_API_KEY` and restart `start.bat` from a new terminal.
- **"Server failed to start"**: port 5000 is probably in use. Run `stop.bat`, or close whatever else is using it.
- **Few or no results**: try a wider time range, or a query that describes the topic instead of exact phrases. The filter is strict by design.
- **Searches are slow**: each round makes an LLM call; larger limits allow more time (about 3 minutes per 25 results).
