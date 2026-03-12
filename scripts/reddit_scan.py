#!/usr/bin/env python3
"""Scan Reddit for posts and comments about a topic.
No API key required — uses Reddit .json API, PullPush, and Arctic Shift.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# Fix Windows console encoding (cp1252 can't handle Reddit's Unicode)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
ARCTIC_API = "https://arctic-shift.photon-reddit.com/api"
PULLPUSH_API = "https://api.pullpush.io/reddit"
REDDIT_API = "https://www.reddit.com"
LINK_BASE = "https://www.reddit.com"

STOP_WORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above",
    "below", "between", "out", "off", "over", "under", "again",
    "further", "then", "once", "here", "there", "when", "where", "why",
    "how", "all", "each", "every", "both", "few", "more", "most",
    "other", "some", "such", "no", "nor", "not", "only", "own", "same",
    "so", "than", "too", "very", "just", "because", "but", "and", "or",
    "if", "while", "about", "up", "it", "its", "i", "me", "my", "he",
    "she", "they", "them", "we", "you", "your", "this", "that", "what",
    "which", "who", "whom",
}


def eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


class RedditFetchError(Exception):
    """Raised when a Reddit API request fails."""


def fetch_json(url: str, timeout: int = 30, retries: int = 3) -> dict:
    """Fetch a JSON endpoint with retries on 429."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                wait = 2 * (attempt + 1)
                eprint(f"Rate limited, retrying in {wait}s...")
                time.sleep(wait)
                continue
            raise RedditFetchError(f"HTTP error {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            raise RedditFetchError(f"Network error: {e.reason}")


def time_ago(utc_timestamp: float) -> str:
    """Convert a UTC timestamp to a human-readable relative time."""
    now = datetime.now(timezone.utc)
    dt = datetime.fromtimestamp(utc_timestamp, tz=timezone.utc)
    diff = now - dt
    seconds = int(diff.total_seconds())
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 30:
        return f"{days}d ago"
    months = days // 30
    if months < 12:
        return f"{months}mo ago"
    years = days // 365
    return f"{years}y ago"


def truncate(text: str, max_len: int = 200) -> str:
    """Truncate text to max_len chars, adding ellipsis if needed."""
    text = text.replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "..."


def _normalize_subreddit(raw: str) -> str:
    """Ensure subreddit string has 'r/' prefix, e.g. 'python' -> 'r/python'."""
    if not raw:
        return ""
    return raw if raw.startswith("r/") else f"r/{raw}"


def _make_post_dict(
    title: str, subreddit: str, score: int, num_comments: int,
    created_utc: float, url: str, snippet: str,
) -> dict:
    """Build a standardized post result dict."""
    return {
        "type": "post",
        "title": title,
        "subreddit": _normalize_subreddit(subreddit),
        "score": score,
        "num_comments": num_comments,
        "created_utc": created_utc,
        "time_ago": time_ago(created_utc),
        "url": url,
        "snippet": truncate(snippet),
    }


def _make_comment_dict(
    subreddit: str, score: int, created_utc: float,
    url: str, post_title: str, snippet: str,
) -> dict:
    """Build a standardized comment result dict."""
    return {
        "type": "comment",
        "subreddit": _normalize_subreddit(subreddit),
        "score": score,
        "created_utc": created_utc,
        "time_ago": time_ago(created_utc),
        "url": url,
        "post_title": post_title,
        "snippet": truncate(snippet),
    }


def _build_keyword_patterns(query: str) -> list[re.Pattern]:
    """Build regex patterns from query that match word stems.

    For each keyword, matches the word itself plus common suffixes
    like s, es, ed, ing, er, 's, etc. Uses word boundaries so
    "cat" matches "cats" and "cat's" but not "caterpillar".
    """
    keywords = [
        kw.strip().lower()
        for kw in query.split()
        if kw.strip() and kw.strip().lower() not in STOP_WORDS
    ]
    patterns = []
    for kw in keywords:
        pattern = re.compile(
            r"\b" + re.escape(kw) + r"(?:'?s|es|ed|ing|er|ers|ly)?\b",
            re.IGNORECASE,
        )
        patterns.append(pattern)
    return patterns


# ─── Arctic Shift API (comment search via link_id) ────────────────────

def _arctic_search_comments(
    query: str, time_filter: str, limit: int, min_score: int,
    posts: list[dict] | None = None,
    before: int | None = None,
) -> list[dict]:
    """Search comments via Arctic Shift by fetching comments from relevant posts.

    Strategy: find posts via Reddit search (1 request), then fetch all comments
    for those posts via Arctic Shift link_id queries (fast, no 422 errors),
    and filter by keyword match.

    If `posts` is provided, skip the Reddit search and use those posts directly.
    """
    all_results = []
    patterns = _build_keyword_patterns(query)
    if not patterns:
        return []

    if posts is None:
        # Step 1: Find relevant posts (PullPush primary, Reddit fallback)
        num_posts = max(10, limit // 5)  # Scale with limit, minimum 10
        try:
            posts = _pullpush_search_posts(query, time_filter, "relevance", num_posts, 0, before=before)
        except RedditFetchError:
            posts = []
        if not posts:
            eprint("[comments] PullPush returned 0 posts, trying Reddit...")
            try:
                posts = _reddit_search_posts(query, time_filter, "relevance", num_posts, 0, before=before)
            except RedditFetchError:
                return []

    if not posts:
        return []

    # Extract Reddit post IDs (t3_xxxxx format) from URLs
    post_ids = []
    post_titles = {}
    for p in posts:
        url = p.get("url", "")
        # Extract post ID from permalink: /r/sub/comments/ID/...
        parts = url.split("/comments/")
        if len(parts) >= 2:
            post_id = "t3_" + parts[1].split("/")[0]
            post_ids.append(post_id)
            post_titles[post_id] = p.get("title", "")

    def _fetch_post_comments(post_id):
        """Fetch comments for a single post via Arctic Shift link_id."""
        params = {"link_id": post_id, "limit": 25, "sort": "desc"}
        try:
            url = f"{ARCTIC_API}/comments/search?{urllib.parse.urlencode(params)}"
            return post_id, fetch_json(url, timeout=5, retries=0).get("data", [])
        except RedditFetchError:
            return post_id, []

    # Step 2: Fetch comments for all posts in parallel (~3-5s)
    seen_ids = set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(_fetch_post_comments, pid)
            for pid in post_ids
        ]
        for future in concurrent.futures.as_completed(futures):
            post_id, comments = future.result()
            for c in comments:
                comment_id = c.get("id", "")
                if comment_id in seen_ids:
                    continue
                seen_ids.add(comment_id)

                body = c.get("body", "")
                score = c.get("score", 0)
                if score < min_score:
                    continue
                if not all(pat.search(body) for pat in patterns):
                    continue
                permalink = c.get("permalink", "")
                all_results.append(_make_comment_dict(
                    subreddit=c.get("subreddit", ""),
                    score=score,
                    created_utc=c.get("created_utc", 0),
                    url=f"{LINK_BASE}{permalink}" if permalink else "",
                    post_title=post_titles.get(post_id, ""),
                    snippet=body,
                ))

    all_results.sort(key=lambda x: x["score"], reverse=True)
    return all_results[:limit]


# ─── PullPush API (primary — no auth, no 429) ─────────────────────────

def _time_filter_to_epoch(time_filter: str) -> int | None:
    """Convert a time filter string to an epoch timestamp for 'after' param."""
    now = int(time.time())
    mapping = {
        "hour": 3600,
        "day": 86400,
        "week": 7 * 86400,
        "month": 30 * 86400,
        "year": 365 * 86400,
    }
    delta = mapping.get(time_filter)
    return now - delta if delta else None


def _pullpush_search_posts(
    query: str, time_filter: str, sort: str, limit: int, min_score: int,
    before: int | None = None,
) -> list[dict]:
    """Search posts via PullPush API (Pushshift successor). No auth needed."""
    all_results = []
    seen_ids = set()
    per_page = min(limit, 100)  # PullPush max is 100

    # Map sort to PullPush params
    sort_type = "score" if sort == "top" else "created_utc"
    sort_dir = "desc"

    # Convert time filter to epoch
    after_epoch = _time_filter_to_epoch(time_filter)

    params = {"q": query, "size": per_page, "sort": sort_dir, "sort_type": sort_type}
    if after_epoch:
        params["after"] = after_epoch
    if before is not None:
        params["before"] = before
    if min_score > 0:
        params["score"] = f">{min_score}"

    pages_fetched = 0
    max_pages = (limit + per_page - 1) // per_page  # ceil division

    while len(all_results) < limit and pages_fetched < max_pages:
        url = f"{PULLPUSH_API}/search/submission/?{urllib.parse.urlencode(params)}"
        eprint(f"[PullPush] Post search: {url}")

        try:
            data = fetch_json(url, timeout=15, retries=1)
        except RedditFetchError as e:
            eprint(f"[PullPush] ERROR: {e}")
            raise

        items = data.get("data", [])
        eprint(f"[PullPush] Got {len(items)} items (page {pages_fetched + 1})")

        if not items:
            break

        for p in items:
            post_id = p.get("id", "")
            if post_id in seen_ids:
                continue
            seen_ids.add(post_id)

            score = p.get("score", 0)
            if score < min_score:
                continue

            permalink = p.get("permalink", "")
            if not permalink:
                sub = p.get("subreddit", "")
                permalink = f"/r/{sub}/comments/{post_id}/" if sub else ""

            all_results.append(_make_post_dict(
                title=p.get("title", ""),
                subreddit=p.get("subreddit", ""),
                score=score,
                num_comments=p.get("num_comments", 0),
                created_utc=p.get("created_utc", 0),
                url=f"{LINK_BASE}{permalink}",
                snippet=p.get("selftext", ""),
            ))

        if len(items) < per_page:
            break
        last_ts = items[-1].get("created_utc", 0)
        if last_ts:
            params["before"] = last_ts
        else:
            break
        pages_fetched += 1
        time.sleep(0.3)

    eprint(f"[PullPush] Total: {len(all_results)} posts")
    return all_results[:limit]


def _pullpush_search_comments(
    query: str, time_filter: str, limit: int, min_score: int,
    before: int | None = None,
) -> list[dict]:
    """Search comments directly via PullPush API."""
    per_page = min(limit, 100)
    after_epoch = _time_filter_to_epoch(time_filter)

    params = {"q": query, "size": per_page, "sort": "desc", "sort_type": "score"}
    if after_epoch:
        params["after"] = after_epoch
    if before is not None:
        params["before"] = before
    if min_score > 0:
        params["score"] = f">{min_score}"

    all_results = []
    seen_ids = set()
    pages_fetched = 0
    max_pages = (limit + per_page - 1) // per_page

    while len(all_results) < limit and pages_fetched < max_pages:
        url = f"{PULLPUSH_API}/search/comment/?{urllib.parse.urlencode(params)}"
        eprint(f"[PullPush] Comment search: {url}")

        try:
            data = fetch_json(url, timeout=15, retries=1)
        except RedditFetchError as e:
            eprint(f"[PullPush] Comment search ERROR: {e}")
            raise

        items = data.get("data", [])
        eprint(f"[PullPush] Got {len(items)} comments (page {pages_fetched + 1})")

        if not items:
            break

        for c in items:
            comment_id = c.get("id", "")
            if comment_id in seen_ids:
                continue
            seen_ids.add(comment_id)

            score = c.get("score", 0)
            if score < min_score:
                continue

            permalink = c.get("permalink", "")
            post_title = ""
            if permalink:
                parts = permalink.strip("/").split("/")
                if len(parts) >= 5:
                    post_title = parts[4].replace("_", " ")

            all_results.append(_make_comment_dict(
                subreddit=c.get("subreddit", ""),
                score=score,
                created_utc=c.get("created_utc", 0),
                url=f"{LINK_BASE}{permalink}" if permalink else "",
                post_title=post_title,
                snippet=c.get("body", ""),
            ))

        if len(items) < per_page:
            break
        last_ts = items[-1].get("created_utc", 0)
        if last_ts:
            params["before"] = int(last_ts)
        else:
            break
        pages_fetched += 1
        time.sleep(0.3)

    eprint(f"[PullPush] Total: {len(all_results)} comments")
    all_results.sort(key=lambda x: x["score"], reverse=True)
    return all_results[:limit]


# ─── Reddit API (fallback) ─────────────────────────────────────────────

def _reddit_search_posts(
    query: str, time_filter: str, sort: str, limit: int, min_score: int,
    before: int | None = None,
) -> list[dict]:
    """Search posts via Reddit's public JSON API."""
    all_results = []
    after = None
    seen_ids = set()
    per_page = min(limit, 100)

    while len(all_results) < limit:
        params = {"q": query, "sort": sort, "t": time_filter, "limit": per_page}
        if after:
            params["after"] = after
        url = f"{REDDIT_API}/search.json?{urllib.parse.urlencode(params)}"

        data = fetch_json(url)
        children = data.get("data", {}).get("children", [])

        new_count = 0
        for child in children:
            if child.get("kind") != "t3":
                continue
            p = child["data"]
            if before is not None and p.get("created_utc", 0) >= before:
                continue
            score = p.get("score", 0)
            if score < min_score:
                continue
            post_url = f"{LINK_BASE}{p.get('permalink', '')}"
            if post_url in seen_ids:
                continue
            seen_ids.add(post_url)
            all_results.append(_make_post_dict(
                title=p.get("title", ""),
                subreddit=p.get("subreddit_name_prefixed", ""),
                score=score,
                num_comments=p.get("num_comments", 0),
                created_utc=p.get("created_utc", 0),
                url=post_url,
                snippet=p.get("selftext", ""),
            ))
            new_count += 1

        after = data.get("data", {}).get("after")
        if not after or new_count == 0:
            break
        time.sleep(0.5)

    all_results.sort(key=lambda x: x["score"], reverse=True)
    return all_results[:limit]


# ─── Public API (with automatic fallback) ──────────────────────────────

def search_posts(
    query: str,
    time_filter: str,
    sort: str,
    limit: int,
    min_score: int,
    before: int | None = None,
) -> list[dict]:
    """Search Reddit for posts. Uses Reddit .json API (primary), PullPush as fallback."""
    try:
        results = _reddit_search_posts(query, time_filter, sort, limit, min_score, before=before)
        if results:
            return results
        eprint("[search_posts] Reddit returned 0 results, trying PullPush fallback...")
    except RedditFetchError as e:
        eprint(f"[search_posts] Reddit failed ({e}), trying PullPush fallback...")
    return _pullpush_search_posts(query, time_filter, sort, limit, min_score, before=before)


def search_comments(
    query: str,
    time_filter: str,
    limit: int,
    min_score: int,
    before: int | None = None,
) -> list[dict]:
    """Search Reddit comments. PullPush direct search (primary), Arctic Shift (fallback)."""
    try:
        results = _pullpush_search_comments(query, time_filter, limit, min_score, before=before)
        if results:
            return results
        eprint("[search_comments] PullPush returned 0 comments, trying Arctic Shift fallback...")
    except RedditFetchError as e:
        eprint(f"[search_comments] PullPush failed ({e}), trying Arctic Shift fallback...")
    return _arctic_search_comments(query, time_filter, limit, min_score, before=before)


def _fetch_by_mode(
    query: str, time_filter: str, sort: str, limit: int, min_score: int,
    mode: str, before: int | None = None,
) -> list[dict]:
    """Dispatch search by mode. Used by both search_and_filter() and main()."""
    if mode == "comments":
        return search_comments(query, time_filter, limit, min_score, before=before)
    elif mode == "deep":
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            pf = pool.submit(search_posts, query, time_filter, sort, limit, min_score, before=before)
            cf = pool.submit(search_comments, query, time_filter, limit, min_score, before=before)
            results = pf.result()
            results.extend(cf.result())
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]
    else:
        return search_posts(query, time_filter, sort, limit, min_score, before=before)


def format_text(results: list[dict]) -> str:
    """Format results as human-readable text."""
    if not results:
        return "No results found."

    lines = []
    for i, r in enumerate(results, 1):
        if r["type"] == "post":
            lines.append(f"[{i}] {r['title']}")
            lines.append(
                f"    {r['subreddit']} \u00b7 {r['score']} pts \u00b7 "
                f"{r['num_comments']} comments \u00b7 {r['time_ago']}"
            )
            lines.append(f"    {r['url']}")
            if r["snippet"]:
                lines.append(f'    "{r["snippet"]}"')
        else:
            lines.append(f"[{i}] Comment on: {r['post_title']}")
            lines.append(
                f"    {r['subreddit']} \u00b7 {r['score']} pts \u00b7 {r['time_ago']}"
            )
            lines.append(f"    {r['url']}")
            if r["snippet"]:
                lines.append(f'    "{r["snippet"]}"')
        lines.append("")

    return "\n".join(lines)


# ── LLM relevance filter ────────────────────────────────────────────────


FILTER_BATCH_SIZE = 50
FILTER_MODEL = os.environ.get("OPENROUTER_MODEL", "moonshotai/kimi-k2.5")


def _get_openrouter_key() -> str | None:
    """Resolve OpenRouter API key from env var or OpenClaw config."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key

    auth_file = os.path.join(
        os.path.expanduser("~"),
        ".openclaw", "agents", "main", "agent", "auth-profiles.json",
    )
    try:
        with open(auth_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        for profile in data.get("profiles", {}).values():
            if profile.get("provider") == "openrouter" and profile.get("key"):
                return profile["key"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass

    return None


def _call_openrouter(api_key: str, messages: list[dict], timeout: int = 30,
                     max_retries: int = 2) -> str:
    """Call OpenRouter chat completions API.  Returns response text.

    Retries when a reasoning model exhausts max_tokens on thinking
    (finish_reason=length with empty content).
    """
    for attempt in range(max_retries):
        payload = json.dumps({
            "model": FILTER_MODEL,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 5000,
            "reasoning": {"effort": "low"},
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"OpenRouter HTTP {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"OpenRouter network error: {e.reason}")
        except json.JSONDecodeError:
            raise RuntimeError("OpenRouter returned invalid JSON")

        try:
            content = data["choices"][0]["message"]["content"] or ""
            finish = data["choices"][0].get("finish_reason", "")
        except (KeyError, IndexError, TypeError):
            raise RuntimeError(f"Unexpected OpenRouter response: {json.dumps(data)[:200]}")

        # Reasoning model used all tokens on thinking — empty content
        if not content.strip() and finish == "length" and attempt < max_retries - 1:
            eprint(f"[filter] LLM returned empty (finish_reason=length), retrying ({attempt + 1}/{max_retries})...")
            continue

        return content

    # Should not reach here, but just in case
    return content


def _build_filter_prompt(query: str, results: list[dict]) -> str:
    """Build compact prompt listing results for relevance classification."""
    lines = [f'Search intent: "{query}"\n\nResults:']
    for i, r in enumerate(results):
        if r["type"] == "post":
            title = r.get("title", "")
            snippet = r.get("snippet", "")[:150]
            sub = r.get("subreddit", "")
            lines.append(f'[{i}] POST: "{title}"')
            lines.append(f"    {sub} | \"{snippet}\"" if snippet else f"    {sub}")
        else:
            post_title = r.get("post_title", "")
            snippet = r.get("snippet", "")[:150]
            sub = r.get("subreddit", "")
            lines.append(f'[{i}] COMMENT on "{post_title}"')
            lines.append(f"    {sub} | \"{snippet}\"" if snippet else f"    {sub}")
    return "\n".join(lines)


_FILTER_SYSTEM = (
    "You are a relevance classifier. Given a search intent and a list of "
    "Reddit results, determine which results are genuinely relevant to the "
    "intent.\n\n"
    "A result is RELEVANT if it discusses the topic the user is searching "
    "for — not merely containing the same words in an unrelated context.\n\n"
    "Respond with ONLY a JSON array of 0-based indices of RELEVANT results. "
    "Example: [0, 2, 5]\nIf none are relevant: []"
)


class FilterError(Exception):
    """Raised when the LLM relevance filter fails."""


def filter_results_llm(query: str, results: list[dict]) -> list[dict]:
    """Filter results via LLM relevance check.  Raises FilterError on failure."""
    if not results:
        return results

    api_key = _get_openrouter_key()
    if not api_key:
        raise FilterError("No OpenRouter API key found. Set OPENROUTER_API_KEY or configure OpenClaw.")

    eprint(f"[filter] Checking {len(results)} results with {FILTER_MODEL}...")
    relevant: set[int] = set()

    for start in range(0, len(results), FILTER_BATCH_SIZE):
        batch = results[start : start + FILTER_BATCH_SIZE]
        user_prompt = _build_filter_prompt(query, batch)

        try:
            text = _call_openrouter(api_key, [
                {"role": "system", "content": _FILTER_SYSTEM},
                {"role": "user", "content": user_prompt},
            ])
        except RuntimeError as exc:
            raise FilterError(f"LLM call failed: {exc}")

        if not text.strip():
            raise FilterError("LLM returned empty response after retries")

        # Extract JSON array from response (handles markdown, extra text, etc.)
        match = re.search(r"\[[\d,\s]*\]", text)
        if not match:
            raise FilterError(f"LLM returned invalid response (no JSON array): {text[:200]}")

        try:
            indices = json.loads(match.group())
        except json.JSONDecodeError:
            raise FilterError(f"LLM returned malformed JSON: {match.group()[:200]}")

        for idx in indices:
            if isinstance(idx, int) and 0 <= idx < len(batch):
                relevant.add(start + idx)

    filtered = [r for i, r in enumerate(results) if i in relevant]
    removed = len(results) - len(filtered)
    if removed:
        eprint(f"[filter] Removed {removed} irrelevant results ({len(filtered)} remaining)")
    return filtered


# ── Iterative search + filter loop ────────────────────────────────────────


def search_and_filter(
    query: str,
    time_filter: str,
    sort: str,
    limit: int,
    min_score: int,
    mode: str,  # "posts", "comments", or "deep"
) -> list[dict]:
    """Iteratively fetch and filter until we have `limit` relevant results
    or hit the time wall.  Raises FilterError / RedditFetchError on failure."""

    time_wall = max(60, 180 * (limit / 25))  # 180s base per 25 items, min 60s
    start = time.time()
    kept: list[dict] = []
    seen_urls: set[str] = set()
    fetch_limit = limit  # how many to request each round
    round_num = 0
    before_ts: int | None = None  # pagination cursor: oldest timestamp from previous round
    MAX_ROUNDS = 10  # safety cap

    while len(kept) < limit and round_num < MAX_ROUNDS:
        remaining = time_wall - (time.time() - start)
        if remaining <= 5:  # need at least 5s for a useful round
            eprint(f"[filter] Time wall reached ({time_wall - remaining:.0f}s). Stopping with {len(kept)} results.")
            break

        round_num += 1

        # ── Fetch ──
        eprint(f"[filter] Round {round_num}: fetching {fetch_limit} {mode}...")
        try:
            raw = _fetch_by_mode(query, time_filter, sort, fetch_limit, min_score, mode, before=before_ts)
        except RedditFetchError as e:
            if kept:
                eprint(f"[filter] Search failed in round {round_num} ({e}), returning {len(kept)} results so far.")
                break
            raise

        # ── Dedup against already-kept results ──
        new = []
        for r in raw:
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                new.append(r)

        # ── Update pagination cursor: oldest timestamp from this batch ──
        if raw:
            oldest = min(r.get("created_utc", 0) for r in raw)
            if oldest > 0:
                before_ts = int(oldest)

        if not new:
            eprint(f"[filter] No new results from API. Stopping with {len(kept)} results.")
            break

        # ── Filter via LLM ──
        filtered = filter_results_llm(query, new)
        kept.extend(filtered)

        elapsed = time.time() - start
        if len(kept) >= limit:
            eprint(f"[filter] Round {round_num}: got {len(filtered)}/{len(new)} relevant — done ({elapsed:.0f}s)")
            break

        eprint(
            f"[filter] Round {round_num}: got {len(filtered)}/{len(new)} relevant, "
            f"total {len(kept)}/{limit} (need {limit - len(kept)} more, {time_wall - elapsed:.0f}s remaining)"
        )

        # ── Calculate next fetch size based on hit rate ──
        if filtered:
            hit_rate = len(filtered) / len(new)
            fetch_limit = int((limit - len(kept)) / hit_rate * 1.5)
            fetch_limit = max(fetch_limit, 10)   # at least 10
            fetch_limit = min(fetch_limit, 100)   # cap at API max
        else:
            # Nothing passed — double the fetch and hope for better results
            fetch_limit = min(fetch_limit * 2, 100)

    return kept[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan Reddit for posts/comments about a topic."
    )
    parser.add_argument("query", help="Search keywords")
    parser.add_argument(
        "--time",
        "-t",
        default="week",
        choices=["hour", "day", "week", "month", "year", "all"],
        help="Time filter (default: week)",
    )
    parser.add_argument(
        "--sort",
        default="relevance",
        choices=["relevance", "new", "hot", "top", "comments"],
        help="Sort order (default: relevance)",
    )
    parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=25,
        help="Max results, 1-500 (default: 25)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output as JSON array",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=0,
        help="Minimum score to include (default: 0)",
    )
    parser.add_argument(
        "--deep",
        action="store_true",
        help="Also search for comments (uses PullPush direct search)",
    )
    parser.add_argument(
        "--comments-only",
        action="store_true",
        help="Search comments only, no posts",
    )
    parser.add_argument(
        "--output", "-o",
        help="Write JSON results to this file instead of stdout",
    )
    parser.add_argument(
        "--filter",
        action="store_true",
        help="Use LLM to filter irrelevant results (requires OpenRouter API key)",
    )

    args = parser.parse_args()
    args.limit = max(1, min(args.limit, 500))

    mode = "deep" if args.deep else "comments" if args.comments_only else "posts"

    if args.filter:
        try:
            results = search_and_filter(
                args.query, args.time, args.sort, args.limit, args.min_score, mode,
            )
        except (RedditFetchError, FilterError) as e:
            eprint(f"ERROR: {e}")
            return 1
    else:
        try:
            results = _fetch_by_mode(
                args.query, args.time, args.sort, args.limit, args.min_score, mode,
            )
        except RedditFetchError as e:
            eprint(str(e))
            return 1

    # Output
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False)
        print(f"Results written to {args.output}")
    elif args.json_output:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print(format_text(results))

    # Summary to stderr
    post_count = sum(1 for r in results if r["type"] == "post")
    comment_count = sum(1 for r in results if r["type"] == "comment")
    parts = []
    if post_count:
        parts.append(f"{post_count} post{'s' if post_count != 1 else ''}")
    if comment_count:
        parts.append(f"{comment_count} comment{'s' if comment_count != 1 else ''}")
    if parts:
        eprint(f"Found {' and '.join(parts)}.")
    else:
        eprint("No results found.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
