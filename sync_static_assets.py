#!/usr/bin/env python3
"""
Download referenced /static assets for pages in static_pages.
"""
import argparse
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_OUTPUT_DIR = "static_pages"
DEFAULT_BASE_URL = "https://quibey.com"

DEFAULT_STATIC_FILES = {
    "/android-chrome-192x192.png",
    "/android-chrome-512x512.png",
    "/favicon.ico",
    "/favicon.jpg",
    "/favicon-16x16.png",
    "/favicon-32x32.png",
    "/apple-touch-icon.png",
    "/manifest.json",
    "/logo192.png",
    "/logo512.png",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download /static assets referenced by HTML/CSS under static_pages."
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory where assets will be stored",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="Base URL for /static assets",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.1,
        help="Delay between downloads (seconds)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing assets",
    )
    return parser.parse_args()


def normalize_asset_path(raw_path):
    if not raw_path:
        return None
    if raw_path.startswith("//"):
        return None
    if raw_path.startswith("http://") or raw_path.startswith("https://"):
        return None
    parsed = urllib.parse.urlsplit(raw_path)
    path = parsed.path or ""
    if not path.startswith("/"):
        return None
    return path


def should_download(path):
    if path in DEFAULT_STATIC_FILES:
        return True
    return path.startswith("/static/")


def extract_from_html(content):
    assets = set()
    for match in re.findall(r'(?:href|src)=["\']([^"\']+)["\']', content):
        path = normalize_asset_path(match)
        if path and should_download(path):
            assets.add(path)
    return assets


def extract_from_css(content):
    assets = set()
    for match in re.findall(r"url\\(([^)]+)\\)", content):
        value = match.strip().strip("'\"")
        path = normalize_asset_path(value)
        if path and should_download(path):
            assets.add(path)
    return assets


def collect_assets(output_dir):
    assets = set(DEFAULT_STATIC_FILES)

    for html_file in output_dir.rglob("*.html"):
        try:
            content = html_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        assets.update(extract_from_html(content))

    css_dir = output_dir / "static" / "css"
    if css_dir.exists():
        for css_file in css_dir.rglob("*.css"):
            try:
                content = css_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            assets.update(extract_from_css(content))

    return sorted(assets)


def download_asset(base_url, output_dir, path, force=False):
    url = base_url.rstrip("/") + path
    target = output_dir / path.lstrip("/")
    if target.exists() and target.stat().st_size > 0 and not force:
        return "skip"

    target.parent.mkdir(parents=True, exist_ok=True)

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as response:
        content = response.read()
        target.write_bytes(content)

    return "ok"


def main():
    args = parse_args()
    output_dir = Path(args.output_dir)
    if not output_dir.exists():
        raise SystemExit(f"Output directory not found: {output_dir}")

    assets = collect_assets(output_dir)
    if not assets:
        print("No assets found.")
        return

    print(f"Found {len(assets)} assets to check/download.")
    downloaded = 0
    skipped = 0
    failed = 0

    for idx, path in enumerate(assets, 1):
        try:
            result = download_asset(args.base_url, output_dir, path, force=args.force)
        except Exception as exc:
            failed += 1
            print(f"[{idx}/{len(assets)}] FAIL {path}: {exc}")
            continue

        if result == "ok":
            downloaded += 1
            print(f"[{idx}/{len(assets)}] OK {path}")
        else:
            skipped += 1

        if args.sleep:
            time.sleep(args.sleep)

    print("-" * 60)
    print(f"Downloaded: {downloaded}")
    print(f"Skipped: {skipped}")
    print(f"Failed: {failed}")


if __name__ == "__main__":
    main()
