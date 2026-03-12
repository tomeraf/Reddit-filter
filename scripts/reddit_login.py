#!/usr/bin/env python3
"""Standalone CLI for Reddit login/session management.

Usage:
  python reddit_login.py          # Open browser for login
  python reddit_login.py --status # Check if logged in
  python reddit_login.py --logout # Delete saved session
"""

from __future__ import annotations

import sys
import os

# Add script directory to path so we can import reddit_auth
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reddit_auth import validate_session, delete_session, run_login_browser


def main() -> int:
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()

        if arg == "--status":
            result = validate_session()
            if result["valid"]:
                print(f"Logged in as {result['username']}")
            else:
                print("Not logged in")
            return 0

        if arg == "--logout":
            delete_session()
            print("Logged out")
            return 0

        if arg in ("--help", "-h"):
            print(__doc__.strip())
            return 0

        print(f"Unknown option: {arg}")
        print("Usage: python reddit_login.py [--status | --logout]")
        return 1

    # Default: open browser for login
    try:
        username = run_login_browser()
        print(f"Logged in as {username}")
        return 0
    except RuntimeError as e:
        print(f"Login failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
