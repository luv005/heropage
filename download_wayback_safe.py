#!/usr/bin/env python3
"""
Safe/slow download of hero.page from Wayback Machine with proper rate limiting
"""
import os
import json
import time
import urllib.request
import urllib.parse
import ssl
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL = "https://hero.page"
OUTPUT_DIR = Path("hero_page_site")
WAYBACK_CDX_API = "https://web.archive.org/cdx/search/cdx"
WAYBACK_RAW_URL = "https://web.archive.org/web/{timestamp}id_/{url}"

# Conservative settings to avoid rate limiting
MAX_WORKERS = 3
MAX_RETRIES = 3
TIMEOUT = 45
REQUEST_DELAY = 0.3  # Delay between requests per worker

# Progress tracking
lock = threading.Lock()
stats = {"downloaded": 0, "failed": 0, "skipped": 0}

def get_ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

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
    ctx = get_ssl_context()

    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, context=ctx, timeout=60) as response:
                data = json.loads(response.read().decode())
                return data[1:] if len(data) > 1 else []
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            time.sleep(5)

    return []

def download_file(args):
    """Download a file from Wayback Machine"""
    url, timestamp, idx, total = args

    # Rate limiting
    time.sleep(REQUEST_DELAY)

    # Create the wayback URL for raw content
    wayback_url = WAYBACK_RAW_URL.format(timestamp=timestamp, url=url)

    # Determine local file path
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.strip("/")

    # Handle query strings
    if parsed.query:
        path = path + "_" + parsed.query.replace("=", "_").replace("&", "_")[:50]

    if not path:
        path = "index.html"
    elif not os.path.splitext(path)[1]:
        path = path.rstrip("/") + "/index.html"

    # Clean up path - remove problematic characters
    for char in ['%', ':', '?', '*', '"', '<', '>', '|', '\\']:
        path = path.replace(char, "_")

    local_path = OUTPUT_DIR / path

    # Skip if already downloaded
    if local_path.exists() and local_path.stat().st_size > 0:
        with lock:
            stats["skipped"] += 1
        return None

    # Create directory
    local_path.parent.mkdir(parents=True, exist_ok=True)

    ctx = get_ssl_context()

    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(wayback_url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            })
            with urllib.request.urlopen(req, context=ctx, timeout=TIMEOUT) as response:
                content = response.read()
                with open(local_path, 'wb') as f:
                    f.write(content)
                with lock:
                    stats["downloaded"] += 1
                return f"[{idx}/{total}] OK: {path[:55]} ({len(content)}b)"
        except urllib.error.HTTPError as e:
            if e.code == 429:  # Too Many Requests
                wait_time = 30 * (attempt + 1)
                print(f"Rate limited, waiting {wait_time}s...")
                time.sleep(wait_time)
            elif attempt < MAX_RETRIES - 1:
                time.sleep(3 * (attempt + 1))
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(3 * (attempt + 1))
            else:
                with lock:
                    stats["failed"] += 1
                error_msg = str(e)[:25]
                return f"[{idx}/{total}] FAIL: {path[:45]} - {error_msg}"

    with lock:
        stats["failed"] += 1
    return None

def main():
    print("=" * 60)
    print("Safe Wayback Machine Downloader for hero.page")
    print(f"Using {MAX_WORKERS} workers with {REQUEST_DELAY}s delay")
    print("=" * 60)

    # Get all snapshots
    snapshots = get_all_snapshots()
    print(f"Found {len(snapshots)} unique URLs")

    if not snapshots:
        print("No snapshots found!")
        return

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Check how many already exist
    existing = len(list(OUTPUT_DIR.rglob("*")))
    print(f"Already have {existing} files")

    # Prepare download tasks
    tasks = []
    for idx, row in enumerate(snapshots, 1):
        url = row[2]
        timestamp = row[1]
        tasks.append((url, timestamp, idx, len(snapshots)))

    print(f"\nDownloading {len(tasks)} files...")
    print("-" * 60)

    start_time = time.time()

    # Use ThreadPoolExecutor for parallel downloads
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(download_file, task): task for task in tasks}

        for future in as_completed(futures):
            result = future.result()
            if result and ("OK:" in result or "FAIL:" in result):
                print(result)

            # Progress update
            total_processed = stats["downloaded"] + stats["failed"] + stats["skipped"]
            if total_processed % 200 == 0 and total_processed > 0:
                elapsed = time.time() - start_time
                rate = total_processed / elapsed
                remaining = (len(tasks) - total_processed) / rate if rate > 0 else 0
                print(f"=== {total_processed}/{len(tasks)} | "
                      f"{rate:.1f}/s | ETA: {remaining/60:.0f}m | "
                      f"OK:{stats['downloaded']} Skip:{stats['skipped']} Fail:{stats['failed']} ===")

    elapsed = time.time() - start_time
    print("-" * 60)
    print(f"Done in {elapsed/60:.1f} minutes!")
    print(f"Downloaded: {stats['downloaded']} | Skipped: {stats['skipped']} | Failed: {stats['failed']}")
    print(f"Files saved to: {OUTPUT_DIR.absolute()}")

if __name__ == "__main__":
    main()
