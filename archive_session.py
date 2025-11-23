#!/usr/bin/env python3
"""
Script to navigate to eminiplayer.net archive page using session cookies.

Usage:
    python archive_session.py --cookie-file cookies.txt
    python archive_session.py -c cookies.json
"""

import argparse
import http.cookiejar
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests


def load_netscape_cookies(cookie_file: Path) -> http.cookiejar.MozillaCookieJar:
    """Load cookies from a Netscape/Mozilla format cookie file."""
    cookie_jar = http.cookiejar.MozillaCookieJar(str(cookie_file))
    cookie_jar.load(ignore_discard=True, ignore_expires=True)
    return cookie_jar


def load_json_cookies(cookie_file: Path) -> dict:
    """Load cookies from a JSON format cookie file.

    Supports formats:
    - Simple dict: {"cookie_name": "cookie_value", ...}
    - Browser export format: [{"name": "...", "value": "...", "domain": "..."}, ...]
    """
    with open(cookie_file, 'r') as f:
        data = json.load(f)

    cookies = {}
    if isinstance(data, list):
        # Browser export format (e.g., from EditThisCookie extension)
        for cookie in data:
            if 'name' in cookie and 'value' in cookie:
                cookies[cookie['name']] = cookie['value']
    elif isinstance(data, dict):
        # Simple key-value format
        cookies = data

    return cookies


def load_cookies(cookie_file: Path) -> dict:
    """Load cookies from file, auto-detecting format."""
    suffix = cookie_file.suffix.lower()

    if suffix == '.json':
        return load_json_cookies(cookie_file)
    elif suffix in ('.txt', '.cookies'):
        # Try Netscape format
        try:
            jar = load_netscape_cookies(cookie_file)
            return {cookie.name: cookie.value for cookie in jar}
        except Exception as e:
            # Fallback: try simple key=value format
            cookies = {}
            with open(cookie_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        cookies[key.strip()] = value.strip()
            return cookies
    else:
        # Try JSON first, then Netscape
        try:
            return load_json_cookies(cookie_file)
        except (json.JSONDecodeError, UnicodeDecodeError):
            jar = load_netscape_cookies(cookie_file)
            return {cookie.name: cookie.value for cookie in jar}


def fetch_archive_page(url: str, cookies: dict, timeout: int = 30) -> requests.Response:
    """Fetch the archive page with the provided cookies."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }

    session = requests.Session()
    session.cookies.update(cookies)

    response = session.get(url, headers=headers, timeout=timeout)
    return response


def main():
    parser = argparse.ArgumentParser(
        description='Navigate to eminiplayer.net archive page using session cookies.'
    )
    parser.add_argument(
        '-c', '--cookie-file',
        type=Path,
        required=True,
        help='Path to the cookie file (supports .json, .txt, or Netscape format)'
    )
    parser.add_argument(
        '-o', '--output',
        type=Path,
        default=None,
        help='Optional output file to save the page content'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose output'
    )
    parser.add_argument(
        '--url',
        type=str,
        default='https://www.eminiplayer.net/archive.aspx',
        help='URL to navigate to (default: https://www.eminiplayer.net/archive.aspx)'
    )

    args = parser.parse_args()

    # Validate cookie file exists
    if not args.cookie_file.exists():
        print(f"Error: Cookie file not found: {args.cookie_file}", file=sys.stderr)
        sys.exit(1)

    # Load cookies
    if args.verbose:
        print(f"Loading cookies from: {args.cookie_file}")

    try:
        cookies = load_cookies(args.cookie_file)
    except Exception as e:
        print(f"Error loading cookies: {e}", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        print(f"Loaded {len(cookies)} cookies")
        for name in cookies:
            print(f"  - {name}")

    # Fetch the page
    if args.verbose:
        print(f"\nFetching: {args.url}")

    try:
        response = fetch_archive_page(args.url, cookies)
    except requests.RequestException as e:
        print(f"Error fetching page: {e}", file=sys.stderr)
        sys.exit(1)

    # Report results
    print(f"Status Code: {response.status_code}")
    print(f"Content-Type: {response.headers.get('Content-Type', 'unknown')}")
    print(f"Content Length: {len(response.content)} bytes")

    if args.verbose:
        print("\nResponse Headers:")
        for key, value in response.headers.items():
            print(f"  {key}: {value}")

    # Save or display content
    if args.output:
        with open(args.output, 'wb') as f:
            f.write(response.content)
        print(f"\nContent saved to: {args.output}")
    else:
        print("\n--- Page Content (first 2000 chars) ---")
        print(response.text[:2000])
        if len(response.text) > 2000:
            print(f"\n... (truncated, {len(response.text) - 2000} more chars)")


if __name__ == '__main__':
    main()
