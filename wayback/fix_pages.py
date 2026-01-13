#!/usr/bin/env python3
"""
Download rendered versions of pages and fix links to work locally
"""
import os
import re
import time
import urllib.request
import ssl
from pathlib import Path

OUTPUT_DIR = Path("hero_page_site")
WAYBACK_RAW_URL = "https://web.archive.org/web/20250519133509id_/https://hero.page{path}"

# Key pages to download rendered versions
KEY_PAGES = [
    "/",
    "/discover",
    "/sign-in",
    "/create-account",
    "/blog",
    "/templates",
    "/ai-prompts",
    "/pfp/anime-pfp",
    "/pfp/matching-pfp",
]

# Also get pages from sidebar
SIDEBAR_PAGES = [
    "/salva/resources-to-develop-ai",
    "/awakentothedream/awaken-to-the-dream-resources",
    "/vxnvh/halloween-anime",
    "/eli2007/lu--1",
    "/jslbrndtt/beautyobsessed",
]

ALL_PAGES = KEY_PAGES + SIDEBAR_PAGES

def get_ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

def download_rendered_page(path):
    """Download a rendered page from Wayback Machine"""
    url = WAYBACK_RAW_URL.format(path=path)

    # Determine local file path
    if path == "/" or path == "":
        local_path = OUTPUT_DIR / "index.html"
    else:
        clean_path = path.strip("/")
        local_path = OUTPUT_DIR / clean_path / "index.html"

    print(f"Downloading: {path} -> {local_path}")

    ctx = get_ssl_context()

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        })
        with urllib.request.urlopen(req, context=ctx, timeout=60) as response:
            content = response.read().decode('utf-8', errors='ignore')

            # Fix links to work locally
            content = fix_links(content)

            # Create directory if needed
            local_path.parent.mkdir(parents=True, exist_ok=True)

            with open(local_path, 'w', encoding='utf-8') as f:
                f.write(content)

            print(f"  OK: {len(content)} bytes")
            return True
    except Exception as e:
        print(f"  FAILED: {e}")
        return False

def fix_links(content):
    """Fix links to work locally"""
    # Remove Wayback Machine wrapper URLs
    content = re.sub(
        r'https://web\.archive\.org/web/\d+id_/https://hero\.page',
        '',
        content
    )
    content = re.sub(
        r'https://web\.archive\.org/web/\d+/https://hero\.page',
        '',
        content
    )
    # Fix direct hero.page links
    content = re.sub(
        r'https://hero\.page/',
        '/',
        content
    )
    content = re.sub(
        r'https://hero\.page',
        '',
        content
    )
    return content

def fix_existing_pages():
    """Fix links in all existing HTML files"""
    print("\nFixing links in existing pages...")
    count = 0
    for html_file in OUTPUT_DIR.rglob("*.html"):
        try:
            with open(html_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            fixed = fix_links(content)

            if fixed != content:
                with open(html_file, 'w', encoding='utf-8') as f:
                    f.write(fixed)
                count += 1
        except Exception as e:
            pass

    print(f"Fixed {count} files")

def main():
    print("=" * 50)
    print("Downloading rendered pages from Wayback Machine")
    print("=" * 50)

    success = 0
    failed = 0

    for path in ALL_PAGES:
        if download_rendered_page(path):
            success += 1
        else:
            failed += 1
        time.sleep(1)  # Rate limiting

    print(f"\nDownloaded: {success}, Failed: {failed}")

    # Fix links in all existing pages
    fix_existing_pages()

    print("\nDone! Refresh http://localhost:8000")

if __name__ == "__main__":
    main()
