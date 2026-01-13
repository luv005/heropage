#!/usr/bin/env python3
"""
Fast parallel download of hero.page from Wayback Machine
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
from queue import Queue

BASE_URL = "https://hero.page"
OUTPUT_DIR = Path("hero_page_site")
WAYBACK_CDX_API = "https://web.archive.org/cdx/search/cdx"
WAYBACK_RAW_URL = "https://web.archive.org/web/{timestamp}id_/{url}"

# Parallel settings
MAX_WORKERS = 10  # Concurrent downloads
MAX_RETRIES = 3
TIMEOUT = 30

# Progress tracking
lock = threading.Lock()
downloaded_count = 0
failed_count = 0
skipped_count = 0

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
            time.sleep(2 ** attempt)

    return []

def download_file(args):
    """Download a file from Wayback Machine"""
    global downloaded_count, failed_count, skipped_count

    url, timestamp, idx, total = args

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

    # Clean up path
    path = path.replace("%", "_").replace(":", "_").replace("?", "_")

    local_path = OUTPUT_DIR / path

    # Skip if already downloaded
    if local_path.exists() and local_path.stat().st_size > 0:
        with lock:
            skipped_count += 1
        return None

    # Create directory
    local_path.parent.mkdir(parents=True, exist_ok=True)

    ctx = get_ssl_context()

    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(wayback_url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
            })
            with urllib.request.urlopen(req, context=ctx, timeout=TIMEOUT) as response:
                content = response.read()
                with open(local_path, 'wb') as f:
                    f.write(content)
                with lock:
                    downloaded_count += 1
                return f"[{idx}/{total}] Downloaded: {path[:60]} ({len(content)} bytes)"
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(1)
            else:
                with lock:
                    failed_count += 1
                return f"[{idx}/{total}] Failed: {path[:60]} - {str(e)[:30]}"

    return None

def main():
    global downloaded_count, failed_count, skipped_count

    print("=" * 60)
    print("Fast Wayback Machine Downloader for hero.page")
    print(f"Using {MAX_WORKERS} parallel workers")
    print("=" * 60)

    # Get all snapshots
    snapshots = get_all_snapshots()
    print(f"Found {len(snapshots)} unique URLs")

    if not snapshots:
        print("No snapshots found!")
        return

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Prepare download tasks
    tasks = []
    for idx, row in enumerate(snapshots, 1):
        url = row[2]
        timestamp = row[1]
        tasks.append((url, timestamp, idx, len(snapshots)))

    print(f"\nDownloading {len(tasks)} files with {MAX_WORKERS} workers...")
    print("-" * 60)

    start_time = time.time()

    # Use ThreadPoolExecutor for parallel downloads
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(download_file, task): task for task in tasks}

        for future in as_completed(futures):
            result = future.result()
            if result:
                print(result)

            # Progress update every 100 files
            total_processed = downloaded_count + failed_count + skipped_count
            if total_processed % 100 == 0 and total_processed > 0:
                elapsed = time.time() - start_time
                rate = total_processed / elapsed
                remaining = (len(tasks) - total_processed) / rate if rate > 0 else 0
                print(f"--- Progress: {total_processed}/{len(tasks)} | "
                      f"Rate: {rate:.1f}/s | "
                      f"ETA: {remaining/60:.1f} min ---")

    elapsed = time.time() - start_time
    print("-" * 60)
    print(f"Done in {elapsed:.1f} seconds!")
    print(f"Downloaded: {downloaded_count} | Skipped: {skipped_count} | Failed: {failed_count}")
    print(f"Files saved to: {OUTPUT_DIR.absolute()}")

if __name__ == "__main__":
    main()
