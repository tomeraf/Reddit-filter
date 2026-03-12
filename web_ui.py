#!/usr/bin/env python3
"""Reddit Scanner — Web UI.

Standalone web frontend that calls reddit_scan.py / reddit_login.py directly.
No LLM or gateway middleman. Runs on http://localhost:5000.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, urlparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = 5000

# ── Script paths ─────────────────────────────────────────────────────────

SCRIPTS_DIR = os.path.join(SCRIPT_DIR, "scripts")
SCAN_SCRIPT = os.path.join(SCRIPTS_DIR, "reddit_scan.py")
LOGIN_SCRIPT = os.path.join(SCRIPTS_DIR, "reddit_login.py")

# ── Logging ──────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(os.path.join(SCRIPT_DIR, "scanner.log"), encoding="utf-8"),
    ],
)
log = logging.getLogger("scanner")


# ── Threaded server ──────────────────────────────────────────────────────

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        """Suppress noisy connection-reset errors (e.g. health checks)."""
        import traceback
        err = traceback.format_exc()
        if "ConnectionResetError" in err or "ConnectionAbortedError" in err:
            return  # Silently ignore
        super().handle_error(request, client_address)


# ── Presets (local, no gateway needed) ───────────────────────────────────

PRESETS_FILE = os.path.join(SCRIPT_DIR, "presets.json")


def load_presets() -> list[dict]:
    try:
        with open(PRESETS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_presets(presets: list[dict]) -> None:
    with open(PRESETS_FILE, "w", encoding="utf-8") as f:
        json.dump(presets, f, indent=2, ensure_ascii=False)




# ── HTML ─────────────────────────────────────────────────────────────────

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reddit Scanner</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f4f4f5; color: #1a1a1b; min-height: 100vh; }

.header { background: #ff4500; color: white; padding: 16px 24px; display: flex; align-items: center; gap: 12px; }
.header h1 { font-size: 20px; font-weight: 600; }
.header .logo { font-size: 28px; }
.header .powered { font-size: 12px; opacity: 0.8; margin-left: auto; }

.reddit-bar { background: #fff3e0; border-bottom: 1px solid #ffe0b2; padding: 8px 24px; display: flex; align-items: center; gap: 12px; font-size: 14px; }
.reddit-bar .status { flex: 1; }
.btn-reddit { background: #ff4500; color: white; border: none; padding: 6px 16px; border-radius: 4px; cursor: pointer; font-size: 13px; }
.btn-reddit:hover { background: #e03d00; }
.btn-disconnect { background: #757575; color: white; border: none; padding: 6px 16px; border-radius: 4px; cursor: pointer; font-size: 13px; }
.btn-disconnect:hover { background: #616161; }

.container { max-width: 900px; margin: 0 auto; padding: 24px; }

.search-box { background: white; border-radius: 8px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 20px; }
.search-box input[type="text"] { width: 100%; padding: 12px 16px; font-size: 16px; border: 2px solid #e0e0e0; border-radius: 6px; outline: none; }
.search-box input[type="text"]:focus { border-color: #ff4500; }

.controls { display: flex; gap: 12px; margin-top: 12px; flex-wrap: wrap; align-items: center; }
.controls select, .controls input[type="number"] { padding: 8px 12px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px; }
.controls label { font-size: 14px; display: flex; align-items: center; gap: 4px; }

.btn-search { background: #ff4500; color: white; border: none; padding: 10px 24px; border-radius: 6px; font-size: 15px; font-weight: 600; cursor: pointer; }
.btn-search:hover { background: #e03d00; }
.btn-search:disabled { background: #ccc; cursor: not-allowed; }

.presets { margin-bottom: 20px; }
.presets h3 { font-size: 14px; color: #666; margin-bottom: 8px; }
.preset-chips { display: flex; gap: 8px; flex-wrap: wrap; }
.preset-chip { background: white; border: 1px solid #ddd; border-radius: 20px; padding: 6px 14px; font-size: 13px; cursor: pointer; display: flex; align-items: center; gap: 6px; }
.preset-chip:hover { border-color: #ff4500; }
.preset-chip .remove { color: #999; font-weight: bold; }
.preset-chip .remove:hover { color: #ff4500; }
.btn-save-preset { background: none; border: 1px dashed #ccc; border-radius: 20px; padding: 6px 14px; font-size: 13px; cursor: pointer; color: #888; }
.btn-save-preset:hover { border-color: #ff4500; color: #ff4500; }

.status-bar { text-align: center; padding: 12px; font-size: 14px; color: #666; }
.spinner { display: inline-block; width: 16px; height: 16px; border: 2px solid #ddd; border-top-color: #ff4500; border-radius: 50%; animation: spin 0.8s linear infinite; vertical-align: middle; margin-right: 6px; }
@keyframes spin { to { transform: rotate(360deg); } }

.loading-overlay { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 60px 20px; }
.loading-circle { width: 48px; height: 48px; border: 4px solid #e0e0e0; border-top-color: #ff4500; border-radius: 50%; animation: spin 0.8s linear infinite; margin-bottom: 16px; }
.loading-text { font-size: 15px; color: #666; }

.result-card { background: white; border-radius: 8px; padding: 16px 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); margin-bottom: 12px; transition: box-shadow 0.15s; cursor: pointer; }
.result-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.15); }
.card-header { display: flex; align-items: flex-start; gap: 8px; margin-bottom: 6px; }
.card-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; text-transform: uppercase; flex-shrink: 0; margin-top: 2px; }
.card-badge.post { background: #e3f2fd; color: #1565c0; }
.card-badge.comment { background: #e8f5e9; color: #2e7d32; }
.card-title { font-size: 15px; font-weight: 600; color: #1a1a1b; line-height: 1.3; }
.card-title a { color: #1a1a1b; text-decoration: none; }
.card-title a:hover { color: #ff4500; }
.card-meta { font-size: 12px; color: #888; margin-bottom: 6px; display: flex; gap: 8px; flex-wrap: wrap; }
.card-meta span { display: flex; align-items: center; gap: 3px; }
.card-snippet { font-size: 13px; color: #555; line-height: 1.5; }
.results-summary { font-size: 13px; color: #888; margin-bottom: 12px; }

.gateway-error { background: #ffebee; border: 1px solid #ef9a9a; border-radius: 8px; padding: 16px; color: #c62828; margin-top: 12px; }
.gateway-error h4 { margin-bottom: 8px; }
</style>
</head>
<body>

<div class="header">
  <span class="logo">&#x1F50D;</span>
  <h1>Reddit Scanner</h1>
  <span class="powered"></span>
</div>

<div class="reddit-bar" id="redditBar">
  <span class="status" id="redditStatus">Checking Reddit session...</span>
</div>

<div class="container">
  <div class="presets" id="presetsSection" style="display:none">
    <h3>Saved Searches</h3>
    <div class="preset-chips" id="presetChips"></div>
  </div>

  <div class="search-box">
    <input type="text" id="query" placeholder="Search Reddit for..." autofocus>
    <div class="controls">
      <select id="time">
        <option value="hour">Past hour</option>
        <option value="day">Past 24h</option>
        <option value="week" selected>Past week</option>
        <option value="month">Past month</option>
        <option value="year">Past year</option>
        <option value="all">All time</option>
      </select>
      <select id="sort">
        <option value="relevance">Relevance</option>
        <option value="new">New</option>
        <option value="hot">Hot</option>
        <option value="top">Top</option>
        <option value="comments">Comments</option>
      </select>
      <label><input type="checkbox" id="searchPosts" checked onchange="updateSearchBtn()"> Search posts</label>
      <label><input type="checkbox" id="searchComments" onchange="updateSearchBtn()"> Search comments</label>
      <label style="font-size:13px">Limit scans <input type="number" id="limit" value="25" min="1" max="100" style="width:70px"></label>
      <button class="btn-search" id="searchBtn" onclick="doSearch()">Search</button>
      <button class="btn-save-preset" id="saveBtn" onclick="savePreset()" style="display:none">+ Save</button>
    </div>
  </div>

  <div id="statusBar" class="status-bar" style="display:none"></div>
  <div id="results"></div>
</div>

<script>
const $ = id => document.getElementById(id);

// ── Reddit session ──────────────────────────────────────────────────
function checkRedditStatus() {
  fetch('/api/reddit-status').then(r => r.json()).then(data => {
    const bar = $('redditBar');
    if (data.valid) {
      bar.innerHTML = '<span class="status">Connected as <b>' + escHtml(data.username) + '</b></span>' +
        '<button class="btn-disconnect" onclick="redditLogout()">Disconnect</button>';
    } else {
      bar.innerHTML = '<span class="status">Not connected to Reddit</span>' +
        '<button class="btn-reddit" onclick="redditLogin()">Connect Reddit</button>';
    }
  }).catch(() => {
    $('redditBar').innerHTML = '<span class="status">Not connected to Reddit</span>' +
      '<button class="btn-reddit" onclick="redditLogin()">Connect Reddit</button>';
  });
}

function redditLogin() {
  $('redditBar').innerHTML = '<span class="status"><span class="spinner"></span>Opening Reddit login...</span>';
  fetch('/api/reddit-login', {method: 'POST'}).then(r => r.json()).then(data => {
    if (data.text) {
      $('redditBar').innerHTML = '<span class="status"><span class="spinner"></span>Waiting for Reddit login... (browser opened)</span>';
      setTimeout(pollRedditStatus, 5000);
    } else if (data.error) {
      $('redditBar').innerHTML = '<span class="status">Login error: ' + escHtml(data.error) + '</span>' +
        '<button class="btn-reddit" onclick="redditLogin()">Retry</button>';
    }
  }).catch(err => {
    $('redditBar').innerHTML = '<span class="status">Error: ' + escHtml(err.message) + '</span>' +
      '<button class="btn-reddit" onclick="redditLogin()">Retry</button>';
  });
}

let pollStart = 0;
function pollRedditStatus() {
  if (!pollStart) pollStart = Date.now();
  if (Date.now() - pollStart > 5 * 60 * 1000) {
    pollStart = 0;
    $('redditBar').innerHTML = '<span class="status">Login timed out</span>' +
      '<button class="btn-reddit" onclick="redditLogin()">Retry</button>';
    return;
  }
  fetch('/api/reddit-status').then(r => r.json()).then(data => {
    if (data.valid) {
      pollStart = 0;
      checkRedditStatus();
    } else {
      setTimeout(pollRedditStatus, 3000);
    }
  }).catch(() => setTimeout(pollRedditStatus, 3000));
}

function redditLogout() {
  fetch('/api/reddit-logout', {method: 'POST'}).then(() => checkRedditStatus());
}

// ── Presets ──────────────────────────────────────────────────────────
function loadPresets() {
  fetch('/api/presets').then(r => r.json()).then(presets => {
    const section = $('presetsSection');
    const chips = $('presetChips');
    if (!presets.length) { section.style.display = 'none'; return; }
    section.style.display = 'block';
    chips.innerHTML = presets.map((p, i) =>
      '<span class="preset-chip" onclick="loadPreset(' + i + ')">' +
      escHtml(p.query) +
      ' <span class="remove" onclick="event.stopPropagation();removePreset(' + i + ')">&times;</span>' +
      '</span>'
    ).join('');
  });
}

function loadPreset(i) {
  fetch('/api/presets').then(r => r.json()).then(presets => {
    const p = presets[i]; if (!p) return;
    $('query').value = p.query;
    if (p.time) $('time').value = p.time;
    if (p.sort) $('sort').value = p.sort;
    if (p.limit) $('limit').value = p.limit;
    doSearch();
  });
}

function savePreset() {
  const q = $('query').value.trim(); if (!q) return;
  fetch('/api/presets', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({query: q, time: $('time').value, sort: $('sort').value, limit: parseInt($('limit').value)})
  }).then(() => loadPresets());
}

function removePreset(i) {
  fetch('/api/presets/' + i, {method: 'DELETE'}).then(() => loadPresets());
}

// ── Search ──────────────────────────────────────────────────────────
let searchController = null;

function renderCard(r) {
  const isPost = r.type === 'post';
  const badge = '<span class="card-badge ' + r.type + '">' + r.type + '</span>';
  const title = isPost ? escHtml(r.title || '') : 'Re: ' + escHtml(r.post_title || '');
  const meta = [
    '<span>' + escHtml(r.subreddit || '') + '</span>',
    '<span>' + (r.score || 0) + ' pts</span>',
    isPost && r.num_comments ? '<span>' + r.num_comments + ' comments</span>' : '',
    '<span>' + escHtml(r.time_ago || '') + '</span>'
  ].filter(Boolean).join('');
  const snippet = r.snippet ? '<div class="card-snippet">' + escHtml(r.snippet) + '</div>' : '';
  return '<div class="result-card" onclick="window.open(\'' + escHtml(r.url || '') + '\',\'_blank\')">' +
    '<div class="card-header">' + badge + '<div class="card-title"><a href="' + escHtml(r.url || '') + '" target="_blank" onclick="event.stopPropagation()">' + title + '</a></div></div>' +
    '<div class="card-meta">' + meta + '</div>' +
    snippet +
    '</div>';
}

function doSearch() {
  const q = $('query').value.trim(); if (!q) return;
  if (!$('searchPosts').checked && !$('searchComments').checked) return;
  const btn = $('searchBtn');

  if (searchController) searchController.abort();
  searchController = new AbortController();

  btn.disabled = true; btn.textContent = 'Searching...';
  $('saveBtn').style.display = 'none';
  $('results').innerHTML = '<div class="loading-overlay"><div class="loading-circle"></div><div class="loading-text">Searching Reddit... (AI filtering)</div></div>';

  const params = new URLSearchParams({
    q, time: $('time').value, sort: $('sort').value,
    limit: $('limit').value,
    posts: $('searchPosts').checked ? '1' : '0',
    comments: $('searchComments').checked ? '1' : '0',
    filter: '1'
  });

  fetch('/api/search?' + params, { signal: searchController.signal })
    .then(r => {
      if (!r.ok) return r.json().then(d => { throw new Error(d.error || 'Request failed'); });
      return r.json();
    })
    .then(data => {
      btn.disabled = false; btn.textContent = 'Search';
      searchController = null;
      $('saveBtn').style.display = '';

      if (!data.results || !data.results.length) {
        $('results').innerHTML = '<div class="results-summary">No results found.</div>';
        return;
      }

      const posts = data.results.filter(r => r.type === 'post').length;
      const comments = data.results.filter(r => r.type === 'comment').length;
      const parts = [];
      if (posts) parts.push(posts + ' post' + (posts !== 1 ? 's' : ''));
      if (comments) parts.push(comments + ' comment' + (comments !== 1 ? 's' : ''));
      const summary = '<div class="results-summary">Found ' + parts.join(' and ') + '</div>';

      $('results').innerHTML = summary + data.results.map(renderCard).join('');
    })
    .catch(err => {
      if (err.name === 'AbortError') return;
      btn.disabled = false; btn.textContent = 'Search';
      updateSearchBtn();
      searchController = null;
      $('results').innerHTML = '<div class="gateway-error"><h4>Error</h4><p>' + escHtml(err.message) + '</p>' +
        '</div>';
    });
}

function escHtml(s) {
  return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function updateSearchBtn() {
  $('searchBtn').disabled = !$('searchPosts').checked && !$('searchComments').checked;
}

$('query').addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });
updateSearchBtn();
loadPresets();
checkRedditStatus();
</script>
</body>
</html>
"""


# ── HTTP Handler ─────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.info("[HTTP] %s", fmt % args)

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html, status=200):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/":
            self._html(HTML_PAGE)
        elif path == "/api/search":
            self._handle_search(params)
        elif path == "/api/presets":
            self._json(load_presets())
        elif path == "/api/reddit-status":
            self._handle_reddit_status()
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/presets":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            if not isinstance(body, dict) or not body.get("query", "").strip():
                self._json({"error": "Missing or empty query"}, 400)
                return
            try:
                limit = int(body.get("limit", 25))
            except (ValueError, TypeError):
                limit = 25
            preset = {
                "query": str(body["query"]).strip()[:200],
                "time": str(body.get("time", "week"))[:10],
                "sort": str(body.get("sort", "relevance"))[:20],
                "limit": max(1, min(limit, 100)),
            }
            presets = load_presets()
            presets.append(preset)
            save_presets(presets)
            self._json({"ok": True})
        elif path == "/api/reddit-login":
            self._handle_reddit_login()
        elif path == "/api/reddit-logout":
            self._handle_reddit_logout()
        else:
            self.send_error(404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/presets/"):
            try:
                idx = int(path.split("/")[-1])
                presets = load_presets()
                if 0 <= idx < len(presets):
                    presets.pop(idx)
                    save_presets(presets)
                self._json({"ok": True})
            except (ValueError, IndexError):
                self._json({"error": "Invalid index"}, 400)
        else:
            self.send_error(404)

    # ── Search: run reddit_scan.py directly ────────────────────────

    def _handle_search(self, params):
        query = params.get("q", [""])[0].strip()
        if not query:
            self._json({"error": "No query provided"}, 400)
            return

        time_filter = params.get("time", ["week"])[0]
        sort = params.get("sort", ["relevance"])[0]
        limit = min(int(params.get("limit", [25])[0]), 100)
        search_posts = params.get("posts", ["1"])[0] == "1"
        search_comments = params.get("comments", ["0"])[0] == "1"
        cmd = [
            sys.executable, SCAN_SCRIPT, query,
            "--time", time_filter,
            "--sort", sort,
            "--limit", str(limit),
            "--json",
            "--filter",
        ]
        if search_posts and search_comments:
            cmd.append("--deep")
        elif search_comments:
            cmd.append("--comments-only")

        log.info("Running: %s", " ".join(cmd))

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300,
                encoding="utf-8", errors="replace",
            )
            log.info("Script exit code: %d", result.returncode)
            if result.stderr:
                log.info("Script stderr: %s", result.stderr.strip()[:500])

            if result.returncode != 0:
                log.error("Script failed: %s", result.stderr.strip()[:500])
                # Extract user-facing error from stderr (e.g. "[filter] ERROR: ...")
                # but don't leak file paths or stack traces
                stderr_lines = result.stderr.strip().splitlines()
                user_msg = "Search failed"
                for line in reversed(stderr_lines):
                    line = line.strip()
                    if line.startswith("[filter] ERROR:"):
                        user_msg = line.replace("[filter] ERROR:", "Filter error:").strip()
                        break
                    if line.startswith("[") and "ERROR" in line:
                        user_msg = line.split("ERROR:", 1)[-1].strip() if "ERROR:" in line else "Search failed"
                        break
                self._json({"error": user_msg}, 500)
                return

            results = json.loads(result.stdout) if result.stdout.strip() else []
            log.info("Got %d results", len(results))
            self._json({"results": results})

        except subprocess.TimeoutExpired:
            log.error("Search timed out after 300s")
            self._json({"error": "Search timed out"}, 504)
        except json.JSONDecodeError as e:
            log.error("Failed to parse script output: %s", e)
            self._json({"error": "Invalid response from search script"}, 500)
        except Exception as e:
            log.error("Search error: %s", e, exc_info=True)
            self._json({"error": "An unexpected error occurred"}, 500)

    # ── Reddit status ───────────────────────────────────────────────

    def _handle_reddit_status(self):
        try:
            result = subprocess.run(
                [sys.executable, LOGIN_SCRIPT, "--status"],
                capture_output=True, text=True, timeout=10,
                encoding="utf-8", errors="replace",
            )
            output = result.stdout.strip()
            if output.startswith("Logged in as "):
                username = output.replace("Logged in as ", "").strip()
                self._json({"valid": True, "username": username})
            else:
                self._json({"valid": False, "username": None})
        except Exception as e:
            log.error("Reddit status error: %s", e)
            self._json({"valid": False, "username": None})

    # ── Reddit login (background thread — opens browser) ─────────────

    def _handle_reddit_login(self):
        def _run_login():
            try:
                subprocess.run(
                    [sys.executable, LOGIN_SCRIPT],
                    capture_output=True, text=True, timeout=300,
                    encoding="utf-8", errors="replace",
                )
            except Exception as e:
                log.error("Reddit login error: %s", e)

        threading.Thread(target=_run_login, daemon=True).start()
        self._json({"text": "Login browser opened. Please log in to Reddit."})

    # ── Reddit logout ────────────────────────────────────────────────

    def _handle_reddit_logout(self):
        try:
            subprocess.run(
                [sys.executable, LOGIN_SCRIPT, "--logout"],
                capture_output=True, text=True, timeout=10,
                encoding="utf-8", errors="replace",
            )
            self._json({"ok": True})
        except Exception as e:
            log.error("Reddit logout error: %s", e)
            self._json({"error": str(e)})


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    server = ThreadedHTTPServer(("", PORT), Handler)
    log.info("Reddit Scanner running on http://localhost:%d", PORT)
    log.info("Scripts: %s", SCRIPTS_DIR)
    print(f"Reddit Scanner running on http://localhost:{PORT}")
    print(f"Scripts: {SCRIPTS_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
