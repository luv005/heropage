#!/usr/bin/env python3
"""
Download rendered versions of ALL pages linked from the site
"""
import os
import re
import time
import urllib.request
import ssl
from pathlib import Path
from collections import deque

OUTPUT_DIR = Path("hero_page_site")
WAYBACK_RAW_URL = "https://web.archive.org/web/20250519id_/https://hero.page{path}"

downloaded = set()
failed = set()
queue = deque()

def get_ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

def extract_links(content):
    """Extract all internal links from HTML content"""
    links = set()
    # Find href="/..." links
    for match in re.findall(r'href="(/[^"]*)"', content):
        # Clean up the path
        path = match.split('?')[0].split('#')[0]
        if path and not path.startswith('//') and not any(x in path for x in ['.js', '.css', '.png', '.jpg', '.ico', '.json', '.xml', '.txt']):
            links.add(path)
    return links

def fix_links(content):
    """Fix links to work locally"""
    content = re.sub(r'https://web\.archive\.org/web/\d+id_/https://hero\.page', '', content)
    content = re.sub(r'https://web\.archive\.org/web/\d+/https://hero\.page', '', content)
    content = re.sub(r'https://hero\.page/', '/', content)
    content = re.sub(r'https://hero\.page', '', content)
    return content

def download_page(path):
    """Download a rendered page from Wayback Machine"""
    if path in downloaded or path in failed:
        return None

    url = WAYBACK_RAW_URL.format(path=path)

    # Determine local file path
    if path == "/" or path == "":
        local_path = OUTPUT_DIR / "index.html"
    else:
        clean_path = path.strip("/")
        if clean_path:
            local_path = OUTPUT_DIR / clean_path / "index.html"
        else:
            return None

    ctx = get_ssl_context()

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        })
        with urllib.request.urlopen(req, context=ctx, timeout=30) as response:
            content = response.read().decode('utf-8', errors='ignore')

            # Only save if it has actual content (not just SPA shell)
            if len(content) > 5000:
                # Fix links
                content = fix_links(content)

                # Create directory if needed
                local_path.parent.mkdir(parents=True, exist_ok=True)

                with open(local_path, 'w', encoding='utf-8') as f:
                    f.write(content)

                downloaded.add(path)
                print(f"[{len(downloaded)}] OK: {path[:60]} ({len(content)} bytes)")

                # Extract new links to crawl
                return extract_links(content)
            else:
                failed.add(path)
                return None
    except Exception as e:
        failed.add(path)
        return None

def main():
    print("=" * 60)
    print("Downloading ALL rendered pages from Wayback Machine")
    print("=" * 60)

    # Start with main pages
    start_pages = [
        "/",
        "/discover",
        "/blog",
        "/ai-prompts",
        "/pfp/anime-pfp",
        "/pfp/matching-pfp-for-couples",
    ]

    for page in start_pages:
        queue.append(page)

    max_pages = 500  # Limit to avoid too long download

    while queue and len(downloaded) < max_pages:
        path = queue.popleft()

        if path in downloaded or path in failed:
            continue

        new_links = download_page(path)

        if new_links:
            for link in new_links:
                if link not in downloaded and link not in failed and link not in queue:
                    queue.append(link)

        time.sleep(0.5)  # Rate limiting

    print("-" * 60)
    print(f"Downloaded: {len(downloaded)}, Failed: {len(failed)}")
    print("Refresh http://localhost:8000")

if __name__ == "__main__":
    main()
