#!/usr/bin/env python3
"""
Script to navigate to eminiplayer.net archive page using session cookies.

Usage:
    python archive_session.py --cookie-file cookies.txt
    python archive_session.py -c cookies.json
    python archive_session.py -c cookies.txt --list-keys
    python archive_session.py -c cookies.txt --list-zones
    python archive_session.py -c cookies.txt --list-keys --start-date 01/01/2024 --end-date 12/31/2024
    python archive_session.py -c cookies.txt --list-zones --download
    python archive_session.py -c cookies.txt --list-zones --download /path/to/dir
    python archive_session.py -c cookies.txt --list-zones --download /path/to/dir --extract
"""

import argparse
import http.cookiejar
import json
import os
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup


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


def extract_key_urls(html_content: str, base_url: str) -> list[dict]:
    """Extract all URLs from anchor tags that contain 'Key' in their text.

    Args:
        html_content: The HTML content to parse
        base_url: The base URL for resolving relative links

    Returns:
        List of dicts with 'url' and 'text' keys
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    key_links = []

    for anchor in soup.find_all('a', href=True):
        text = anchor.get_text(strip=True)
        if 'Key' in text:
            href = anchor['href']
            # Resolve relative URLs
            full_url = urljoin(base_url, href)
            key_links.append({
                'url': full_url,
                'text': text
            })

    return key_links


def extract_zone_urls(html_content: str, base_url: str) -> list[dict]:
    """Extract all URLs from anchor tags that contain 'Zones' in their text.

    Args:
        html_content: The HTML content to parse
        base_url: The base URL for resolving relative links

    Returns:
        List of dicts with 'url' and 'text' keys
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    zone_links = []

    for anchor in soup.find_all('a', href=True):
        text = anchor.get_text(strip=True)
        if 'Zones File' in text:
            href = anchor['href']
            # Resolve relative URLs
            full_url = urljoin(base_url, href)
            zone_links.append({
                'url': full_url,
                'text': text
            })

    return zone_links


def parse_date_from_text(text: str) -> datetime | None:
    """Extract a date in MM/DD/YYYY format from text.

    Args:
        text: Text that may contain a date

    Returns:
        datetime object if a date is found, None otherwise
    """
    # Match MM/DD/YYYY format
    match = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', text)
    if match:
        try:
            month, day, year = match.groups()
            return datetime(int(year), int(month), int(day))
        except ValueError:
            return None
    return None


def filter_keys_by_date(
    key_urls: list[dict],
    start_date: datetime | None = None,
    end_date: datetime | None = None
) -> list[dict]:
    """Filter key URLs by date range.

    Args:
        key_urls: List of dicts with 'url' and 'text' keys
        start_date: Include only URLs with dates >= this date
        end_date: Include only URLs with dates <= this date

    Returns:
        Filtered list of key URLs
    """
    if start_date is None and end_date is None:
        return key_urls

    filtered = []
    for item in key_urls:
        item_date = parse_date_from_text(item['text'])
        if item_date is None:
            # If we can't parse a date, skip this item when filtering
            continue

        if start_date and item_date < start_date:
            continue
        if end_date and item_date > end_date:
            continue

        filtered.append(item)

    return filtered


def fetch_zones_from_keys(keys_urls: list[dict], cookies: dict, verbose: bool = False) -> list[dict]:
    """Navigate to each Keys URL and extract Zones links.

    Args:
        keys_urls: List of dicts with 'url' and 'text' keys from extract_key_urls
        cookies: Session cookies for authentication
        verbose: Whether to print verbose output

    Returns:
        List of dicts with 'key_url', 'key_text', 'zone_url', and 'zone_text' keys
    """
    all_zones = []

    for key_item in keys_urls:
        key_url = key_item['url']
        key_text = key_item['text']

        if verbose:
            print(f"\nFetching Keys page: {key_text}")
            print(f"  URL: {key_url}")

        try:
            response = fetch_archive_page(key_url, cookies)
            if response.status_code != 200:
                print(f"  Warning: Got status {response.status_code} for {key_url}")
                continue

            zone_links = extract_zone_urls(response.text, key_url)

            for zone in zone_links:
                all_zones.append({
                    'key_url': key_url,
                    'key_text': key_text,
                    'zone_url': zone['url'],
                    'zone_text': zone['text']
                })

            if verbose:
                print(f"  Found {len(zone_links)} Zones link(s)")

        except requests.RequestException as e:
            print(f"  Error fetching {key_url}: {e}")
            continue

    return all_zones


def download_zone_files(
    zones: list[dict],
    cookies: dict,
    download_dir: Path,
    verbose: bool = False
) -> list[Path]:
    """Download zone files from URLs to the specified directory.

    Args:
        zones: List of dicts with 'zone_url' and 'zone_text' keys
        cookies: Session cookies for authentication
        download_dir: Directory to save downloaded files
        verbose: Whether to print verbose output

    Returns:
        List of Paths to successfully downloaded files
    """
    downloaded_files = []

    # Create download directory if it doesn't exist
    download_dir.mkdir(parents=True, exist_ok=True)

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/zip,application/octet-stream,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
    }

    session = requests.Session()
    session.cookies.update(cookies)

    for zone in zones:
        zone_url = zone['zone_url']
        zone_text = zone.get('zone_text', '')

        # Extract filename from URL or generate one
        parsed_url = urlparse(zone_url)
        filename = os.path.basename(parsed_url.path)
        if not filename or not filename.endswith('.zip'):
            # Try to create a meaningful filename from the zone text
            safe_text = re.sub(r'[^\w\-_]', '_', zone_text)[:50]
            filename = f"{safe_text}.zip" if safe_text else "zone_file.zip"

        filepath = download_dir / filename

        # Handle duplicate filenames
        counter = 1
        original_filepath = filepath
        while filepath.exists():
            stem = original_filepath.stem
            filepath = download_dir / f"{stem}_{counter}.zip"
            counter += 1

        if verbose:
            print(f"\nDownloading: {zone_text}")
            print(f"  URL: {zone_url}")
            print(f"  To: {filepath}")

        try:
            response = session.get(zone_url, headers=headers, timeout=60, stream=True)
            response.raise_for_status()

            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            downloaded_files.append(filepath)
            if verbose:
                print(f"  Downloaded: {filepath.stat().st_size} bytes")

        except requests.RequestException as e:
            print(f"  Error downloading {zone_url}: {e}")
            continue

    return downloaded_files


def extract_zip_files(
    zip_files: list[Path],
    extract_dir: Path,
    verbose: bool = False
) -> list[Path]:
    """Extract zip files to the specified directory.

    Args:
        zip_files: List of Paths to zip files
        extract_dir: Directory to extract files to
        verbose: Whether to print verbose output

    Returns:
        List of Paths to extracted directories/files
    """
    extracted = []

    for zip_path in zip_files:
        if not zip_path.exists():
            print(f"  Warning: File not found: {zip_path}")
            continue

        if verbose:
            print(f"\nExtracting: {zip_path}")

        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                # Extract directly to the extract directory
                extract_dir.mkdir(parents=True, exist_ok=True)

                zf.extractall(extract_dir)
                extracted.append(extract_dir)

                if verbose:
                    file_count = len(zf.namelist())
                    print(f"  Extracted {file_count} file(s) to: {extract_dir}")

        except zipfile.BadZipFile:
            print(f"  Error: Invalid zip file: {zip_path}")
            continue
        except Exception as e:
            print(f"  Error extracting {zip_path}: {e}")
            continue

    return extracted


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
    parser.add_argument(
        '--list-keys',
        action='store_true',
        help='List all URLs from anchor tags containing "Key" in their text'
    )
    parser.add_argument(
        '--list-zones',
        action='store_true',
        help='Navigate to each "Keys" URL and list links containing "Zones" in their text'
    )
    parser.add_argument(
        '--start-date',
        type=str,
        default=None,
        help='Filter results to dates >= this date (format: MM/DD/YYYY)'
    )
    parser.add_argument(
        '--end-date',
        type=str,
        default=None,
        help='Filter results to dates <= this date (format: MM/DD/YYYY)'
    )
    parser.add_argument(
        '--download',
        type=str,
        nargs='?',
        const='.',
        default=None,
        help='Download zone files to the specified directory (default: current directory if flag is used without a path)'
    )
    parser.add_argument(
        '--extract',
        action='store_true',
        help='Extract downloaded zip files (requires --download)'
    )

    args = parser.parse_args()

    # Parse date arguments
    start_date = None
    end_date = None
    if args.start_date:
        start_date = parse_date_from_text(args.start_date)
        if start_date is None:
            print(f"Error: Invalid start date format: {args.start_date}. Use MM/DD/YYYY", file=sys.stderr)
            sys.exit(1)
    if args.end_date:
        end_date = parse_date_from_text(args.end_date)
        if end_date is None:
            print(f"Error: Invalid end date format: {args.end_date}. Use MM/DD/YYYY", file=sys.stderr)
            sys.exit(1)

    # Validate --extract requires --download
    if args.extract and args.download is None:
        print("Error: --extract requires --download to be specified", file=sys.stderr)
        sys.exit(1)

    # Validate --download requires --list-zones
    if args.download is not None and not args.list_zones:
        print("Error: --download requires --list-zones to be specified", file=sys.stderr)
        sys.exit(1)

    # Convert download path to Path object
    download_dir = Path(args.download) if args.download else None

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

    # Handle --list-keys option
    if args.list_keys:
        key_urls = extract_key_urls(response.text, args.url)
        total_found = len(key_urls)

        # Apply date filtering if specified
        if start_date or end_date:
            key_urls = filter_keys_by_date(key_urls, start_date, end_date)
            date_range_msg = ""
            if start_date and end_date:
                date_range_msg = f" (filtered: {args.start_date} to {args.end_date})"
            elif start_date:
                date_range_msg = f" (filtered: from {args.start_date})"
            elif end_date:
                date_range_msg = f" (filtered: to {args.end_date})"
            print(f"\n--- URLs with 'Key' in anchor text ({len(key_urls)} of {total_found} match date filter){date_range_msg} ---")
        elif key_urls:
            print(f"\n--- URLs with 'Key' in anchor text ({len(key_urls)} found) ---")

        if key_urls:
            for item in key_urls:
                print(f"  {item['text']}")
                print(f"    -> {item['url']}")
        else:
            print("\nNo URLs found with 'Key' in anchor text.")
        return

    # Handle --list-zones option
    if args.list_zones:
        # First, extract all Keys URLs from the archive page
        key_urls = extract_key_urls(response.text, args.url)
        total_keys = len(key_urls)
        if not key_urls:
            print("\nNo 'Keys' URLs found on the archive page.")
            return

        # Apply date filtering if specified
        if start_date or end_date:
            key_urls = filter_keys_by_date(key_urls, start_date, end_date)
            date_range_msg = ""
            if start_date and end_date:
                date_range_msg = f" (filtered: {args.start_date} to {args.end_date})"
            elif start_date:
                date_range_msg = f" (filtered: from {args.start_date})"
            elif end_date:
                date_range_msg = f" (filtered: to {args.end_date})"
            print(f"\nFound {len(key_urls)} of {total_keys} 'Keys' URL(s) in date range{date_range_msg}. Fetching Zones links...")
        else:
            print(f"\nFound {len(key_urls)} 'Keys' URL(s). Fetching Zones links...")

        if not key_urls:
            print("No 'Keys' URLs match the specified date range.")
            return

        # Navigate to each Keys URL and extract Zones links
        zones = fetch_zones_from_keys(key_urls, cookies, verbose=args.verbose)

        if zones:
            print(f"\n--- URLs with 'Zones' in anchor text ({len(zones)} found) ---")
            current_key = None
            for zone in zones:
                # Group by Key URL for better readability
                if zone['key_text'] != current_key:
                    current_key = zone['key_text']
                    print(f"\n  From: {zone['key_text']}")
                print(f"    {zone['zone_text']}")
                print(f"      -> {zone['zone_url']}")

            # Handle download if specified
            if download_dir:
                print(f"\n--- Downloading {len(zones)} zone file(s) to: {download_dir} ---")
                downloaded_files = download_zone_files(
                    zones, cookies, download_dir, verbose=args.verbose
                )
                print(f"\nSuccessfully downloaded {len(downloaded_files)} of {len(zones)} file(s)")

                # Handle extract if specified
                if args.extract and downloaded_files:
                    print(f"\n--- Extracting {len(downloaded_files)} zip file(s) ---")
                    extracted = extract_zip_files(
                        downloaded_files, download_dir, verbose=args.verbose
                    )
                    print(f"\nSuccessfully extracted {len(extracted)} of {len(downloaded_files)} file(s)")
        else:
            print("\nNo URLs found with 'Zones' in anchor text.")
        return

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
