"""Reddit session management via Playwright browser automation.

Opens a real browser for manual Reddit login, captures cookies,
and stores them for later use. No API keys needed.
"""

from __future__ import annotations

import json
import logging
import os
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_FILE = os.path.join(SCRIPT_DIR, "..", "reddit_session.json")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

log = logging.getLogger("scanner")


# ── Session file I/O ─────────────────────────────────────────────────────

def load_session() -> dict | None:
    """Read saved session from disk. Returns dict or None."""
    path = os.path.normpath(SESSION_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("cookies"):
            return data
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return None


def save_session(cookies: list[dict], username: str) -> None:
    """Write cookies + metadata to reddit_session.json."""
    path = os.path.normpath(SESSION_FILE)
    data = {
        "cookies": cookies,
        "username": username,
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    log.info("Reddit session saved for %s (%d cookies)", username, len(cookies))


def delete_session() -> None:
    """Delete the saved session file."""
    path = os.path.normpath(SESSION_FILE)
    try:
        os.remove(path)
        log.info("Reddit session deleted")
    except FileNotFoundError:
        pass


# ── Session validation ───────────────────────────────────────────────────

def validate_session() -> dict:
    """Check if the saved Reddit session is still valid.

    Returns {"valid": bool, "username": str | None}.
    Trusts the saved session file — no network calls to Reddit.
    This avoids triggering Reddit's anti-bot detection.
    """
    session = load_session()
    if not session:
        return {"valid": False, "username": None}

    saved_user = session.get("username")
    if saved_user and session.get("cookies"):
        log.info("Trusting saved session for %s", saved_user)
        return {"valid": True, "username": saved_user}

    return {"valid": False, "username": None}


# ── Playwright login flow ────────────────────────────────────────────────

def run_login_browser() -> str:
    """Open a visible Chromium browser to reddit.com/login.

    Blocks until user logs in or 5 minute timeout.
    Returns the username on success, raises RuntimeError on failure.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright not installed. Run: pip install playwright && playwright install chromium"
        )

    print("Opening browser for Reddit login...")
    print("Please log in to your Reddit account. The browser will close automatically.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=USER_AGENT,
        )
        page = context.new_page()

        try:
            page.goto("https://www.reddit.com/login", timeout=30000)
        except Exception as e:
            browser.close()
            raise RuntimeError(f"Failed to open Reddit: {e}")

        deadline = time.time() + 300  # 5 minute timeout

        while time.time() < deadline:
            time.sleep(2)

            # Check if browser was closed by user
            try:
                if page.is_closed():
                    raise RuntimeError("Browser closed before login completed")
            except Exception:
                raise RuntimeError("Browser closed before login completed")

            # Detect login using two signals:
            # 1. URL changed away from /login (traditional redirect)
            # 2. reddit_session cookie appeared (SPA login without URL change)
            try:
                current_url = page.url
                cookies = context.cookies("https://www.reddit.com")
                cookie_names = {c["name"] for c in cookies}
                has_session_cookie = "reddit_session" in cookie_names

                on_login_page = "/login" in current_url or "/register" in current_url

                if on_login_page and not has_session_cookie:
                    continue  # Still logging in

                reason = "URL change" if not on_login_page else "reddit_session cookie"
                log.info("Login detected via %s (url=%s)", reason, current_url)

                # Verify with /api/me.json in a new tab
                verify_page = context.new_page()
                try:
                    verify_page.goto(
                        "https://www.reddit.com/api/me.json",
                        timeout=15000,
                    )
                    verify_page.wait_for_load_state("networkidle", timeout=10000)
                    body = verify_page.inner_text("body")
                finally:
                    verify_page.close()

                try:
                    me_data = json.loads(body)
                except json.JSONDecodeError:
                    log.warning("Could not parse /api/me.json, will retry...")
                    continue

                username = me_data.get("data", {}).get("name")
                if username:
                    all_cookies = context.cookies()
                    save_session(all_cookies, f"u/{username}")
                    browser.close()
                    return f"u/{username}"
                else:
                    log.info("Login signal but no username from /api/me, waiting...")

            except RuntimeError:
                raise
            except Exception as e:
                log.debug("Login poll error (will retry): %s", e)

        # Timeout
        try:
            browser.close()
        except Exception:
            pass
        raise RuntimeError("Login timed out (5 minutes). Try again.")
