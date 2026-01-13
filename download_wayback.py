#!/usr/bin/env python3
"""
Download hero.page from Wayback Machine with proper rate limiting
"""
import os
import json
import time
import urllib.request
import urllib.parse
import ssl
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL = "https://hero.page"
OUTPUT_DIR = Path("hero_page_site")
WAYBACK_CDX_API = "https://web.archive.org/cdx/search/cdx"
WAYBACK_RAW_URL = "https://web.archive.org/web/{timestamp}id_/{url}"

# Rate limiting
REQUEST_DELAY = 0.5  # seconds between requests
MAX_RETRIES = 3

def get_all_snapshots():
    """Get all unique URLs from Wayback Machine CDX API"""
    print("Fetching URL list from Wayback Machine CDX API...")

    params = {
        "url": "hero.page/*",
        "output": "json",
        "collapse": "urlkey",
        "filter": "statuscode:200",
        "limit": "10000"
    }

    url = f"{WAYBACK_CDX_API}?{urllib.parse.urlencode(params)}"

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, context=ctx, timeout=60) as response:
                data = json.loads(response.read().decode())
                # Skip header row
                return data[1:] if len(data) > 1 else []
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            time.sleep(2 ** attempt)

    return []

def get_latest_snapshot_for_url(url):
    """Get the most recent snapshot timestamp for a specific URL"""
    params = {
        "url": url,
        "output": "json",
        "limit": "1",
        "filter": "statuscode:200"
    }

    api_url = f"{WAYBACK_CDX_API}?{urllib.parse.urlencode(params)}"

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, context=ctx, timeout=30) as response:
            data = json.loads(response.read().decode())
            if len(data) > 1:
                return data[1][1]  # timestamp
    except:
        pass
    return None

def download_file(url, timestamp, output_dir):
    """Download a file from Wayback Machine"""
    # Create the wayback URL for raw content
    wayback_url = WAYBACK_RAW_URL.format(timestamp=timestamp, url=url)

    # Determine local file path
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        path = "index.html"
    elif not os.path.splitext(path)[1]:
        path = path.rstrip("/") + "/index.html"

    local_path = output_dir / path

    # Skip if already downloaded
    if local_path.exists():
        return f"Skipped (exists): {path}"

    # Create directory
    local_path.parent.mkdir(parents=True, exist_ok=True)

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(wayback_url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
            })
            with urllib.request.urlopen(req, context=ctx, timeout=60) as response:
                content = response.read()
                with open(local_path, 'wb') as f:
                    f.write(content)
                return f"Downloaded: {path} ({len(content)} bytes)"
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
            else:
                return f"Failed: {path} - {e}"

    return f"Failed: {path}"

def main():
    print("=" * 60)
    print("Wayback Machine Downloader for hero.page")
    print("=" * 60)

    # Get all snapshots
    snapshots = get_all_snapshots()
    print(f"Found {len(snapshots)} unique URLs")

    if not snapshots:
        print("No snapshots found!")
        return

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Process URLs - using most recent timestamp for each
    urls_to_download = []
    for row in snapshots:
        # row format: [urlkey, timestamp, original, mimetype, statuscode, digest, length]
        url = row[2]
        timestamp = row[1]
        urls_to_download.append((url, timestamp))

    print(f"\nDownloading {len(urls_to_download)} files...")
    print("-" * 60)

    downloaded = 0
    failed = 0
    skipped = 0

    for i, (url, timestamp) in enumerate(urls_to_download):
        result = download_file(url, timestamp, OUTPUT_DIR)

        if "Downloaded" in result:
            downloaded += 1
            print(f"[{i+1}/{len(urls_to_download)}] {result}")
        elif "Skipped" in result:
            skipped += 1
        else:
            failed += 1
            print(f"[{i+1}/{len(urls_to_download)}] {result}")

        # Rate limiting
        time.sleep(REQUEST_DELAY)

    print("-" * 60)
    print(f"Done! Downloaded: {downloaded}, Skipped: {skipped}, Failed: {failed}")
    print(f"Files saved to: {OUTPUT_DIR.absolute()}")

if __name__ == "__main__":
    main()
