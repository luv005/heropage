#!/usr/bin/env python3
"""
Render Quibey pages for hero.page URLs listed in a CSV and save to static_pages.
"""
import argparse
import csv
import os
import time
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from content_utils import fix_content

try:
    from playwright.sync_api import sync_playwright
except ImportError as exc:
    raise SystemExit(
        "Playwright is required. Install it with: pip install playwright && playwright install chromium"
    ) from exc

DEFAULT_CSV_PATH = os.environ.get(
    "CSV_PATH",
    "/Users/kitty/Downloads/hero.page-top-pages-subdomains-all--compar_2026-01-14_13-20-56.csv",
)
DEFAULT_OUTPUT_DIR = "static_pages"
DEFAULT_DOMAIN = os.environ.get("DOMAIN", "hero.page")
KNOWN_FILE_EXTENSIONS = {
    ".html",
    ".htm",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".css",
    ".js",
    ".json",
    ".xml",
    ".txt",
    ".pdf",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Render Quibey pages listed in a CSV into static_pages."
    )
    parser.add_argument("--csv", default=DEFAULT_CSV_PATH, help="CSV file path")
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for rendered pages",
    )
    parser.add_argument(
        "--domain",
        default=DEFAULT_DOMAIN,
        help="Canonical domain to write into rendered pages",
    )
    parser.add_argument(
        "--host-prefix",
        action="append",
        default=[],
        help="Map host to path prefix, e.g. docs.hero.page=/docs",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=0,
        help="Skip the first N URLs after de-duplication",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of URLs to process (0 means no limit)",
    )
    parser.add_argument(
        "--min-bytes",
        type=int,
        default=1500,
        help="Minimum rendered HTML size to treat as valid",
    )
    parser.add_argument(
        "--wait-until",
        default=os.environ.get("QUIBEY_WAIT_UNTIL", "domcontentloaded"),
        help="Playwright wait_until value (e.g. domcontentloaded, load, networkidle)",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=int(os.environ.get("QUIBEY_TIMEOUT_MS", "60000")),
        help="Playwright navigation timeout in milliseconds",
    )
    parser.add_argument(
        "--render-wait-ms",
        type=int,
        default=int(os.environ.get("QUIBEY_POST_WAIT_MS", "1500")),
        help="Extra wait after navigation to allow rendering",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.2,
        help="Delay between requests (seconds)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files",
    )
    return parser.parse_args()


def parse_host_prefixes(values):
    prefixes = {}
    for item in values:
        if "=" not in item:
            raise SystemExit(f"Invalid --host-prefix value: {item}")
        host, prefix = item.split("=", 1)
        host = host.strip()
        prefix = prefix.strip()
        if prefix and not prefix.startswith("/"):
            prefix = "/" + prefix
        prefixes[host] = prefix
    return prefixes


def normalize_path(raw_path):
    if not raw_path or raw_path == "/":
        return "/"
    parts = []
    for part in raw_path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/" + "/".join(parts)


def output_path_for(base_dir, path):
    if path in ("", "/"):
        return base_dir / "index.html"
    cleaned = path.lstrip("/").rstrip("/")
    suffix = Path(cleaned).suffix.lower()
    if suffix and suffix in KNOWN_FILE_EXTENSIONS:
        return base_dir / cleaned
    return base_dir / cleaned / "index.html"


def ensure_output_parent(output_path, base_dir):
    base_dir = base_dir.resolve()
    for ancestor in output_path.parents:
        if ancestor == base_dir:
            break
        if ancestor.exists() and ancestor.is_file():
            temp_path = ancestor.with_name(ancestor.name + "__file")
            ancestor.replace(temp_path)
            ancestor.mkdir(parents=True, exist_ok=True)
            (ancestor / "index.html").write_bytes(temp_path.read_bytes())
            temp_path.unlink()
            print(f"[WARN] Converted file to directory: {ancestor}")
    output_path.parent.mkdir(parents=True, exist_ok=True)


def resolve_chromium_executable(p):
    default_path = Path(p.chromium.executable_path)
    if default_path.exists():
        return default_path

    cache_root = Path.home() / "Library" / "Caches" / "ms-playwright"
    if cache_root.exists():
        for root in sorted(cache_root.glob("chromium-*")):
            for arch_dir in ("chrome-mac-arm64", "chrome-mac-x64"):
                candidate = (
                    root
                    / arch_dir
                    / "Google Chrome for Testing.app"
                    / "Contents"
                    / "MacOS"
                    / "Google Chrome for Testing"
                )
                if candidate.exists():
                    return candidate

    return None


def chromium_launch_args():
    crash_dir = Path(tempfile.gettempdir()) / "playwright-crashpad"
    crash_dir.mkdir(parents=True, exist_ok=True)
    return [
        "--disable-crash-reporter",
        "--no-crashpad",
        f"--crash-dumps-dir={crash_dir}",
    ]


def load_paths(csv_path, host_prefixes):
    paths = []
    skipped_hosts = {}
    seen = set()

    with open(csv_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            url = row.get("URL") or row.get("Url") or row.get("url")
            if not url:
                continue
            url = url.strip()
            parsed = urlparse(url)
            host = parsed.hostname or ""
            path = normalize_path(parsed.path or "/")

            if host and host != "hero.page":
                prefix = host_prefixes.get(host)
                if prefix is None:
                    skipped_hosts.setdefault(host, 0)
                    skipped_hosts[host] += 1
                    continue
                path = normalize_path(f"{prefix}/{path.lstrip('/')}")

            if path not in seen:
                seen.add(path)
                paths.append(path)

    return paths, skipped_hosts


def render_pages(
    paths,
    output_dir,
    domain,
    min_bytes,
    sleep_delay,
    force,
    wait_until,
    timeout_ms,
    render_wait_ms,
):
    output_dir.mkdir(parents=True, exist_ok=True)

    total = len(paths)
    rendered = 0
    skipped = 0
    failed = 0

    with sync_playwright() as p:
        chromium_exec = resolve_chromium_executable(p)
        if chromium_exec is None:
            raise SystemExit(
                "Chromium executable not found. Run: python -m playwright install chromium"
            )
        browser = p.chromium.launch(
            headless=True,
            executable_path=str(chromium_exec),
            args=chromium_launch_args(),
        )
        context = browser.new_context()
        page = context.new_page()

        for idx, path in enumerate(paths, 1):
            target_url = f"https://quibey.com{path}"
            output_path = output_path_for(output_dir, path)

            if output_path.exists() and not force:
                skipped += 1
                continue

            try:
                response = page.goto(
                    target_url,
                    wait_until=wait_until,
                    timeout=timeout_ms,
                )
            except Exception as exc:
                failed += 1
                print(f"[{idx}/{total}] ERROR {path}: {exc}")
                continue

            status = response.status if response else None
            content_type = response.headers.get("content-type", "") if response else ""
            if not response or "text/html" not in content_type:
                failed += 1
                print(
                    f"[{idx}/{total}] SKIP {path} -> status={status} content-type={content_type}"
                )
                continue

            page.wait_for_timeout(render_wait_ms)
            content = page.content()
            if len(content) < min_bytes:
                failed += 1
                print(f"[{idx}/{total}] SKIP {path} -> {len(content)} bytes")
                continue

            fixed = fix_content(content, path, domain)
            ensure_output_parent(output_path, output_dir)
            output_path.write_text(fixed, encoding="utf-8")
            rendered += 1
            print(f"[{idx}/{total}] OK {path} -> {output_path}")

            if sleep_delay:
                time.sleep(sleep_delay)

        browser.close()

    return rendered, skipped, failed


def main():
    args = parse_args()
    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise SystemExit(f"CSV file not found: {csv_path}")

    host_prefixes = parse_host_prefixes(args.host_prefix)
    paths, skipped_hosts = load_paths(csv_path, host_prefixes)

    if args.start:
        paths = paths[args.start :]
    if args.limit:
        paths = paths[: args.limit]

    if skipped_hosts:
        print("Skipped unsupported hosts:")
        for host, count in sorted(skipped_hosts.items()):
            print(f"  {host}: {count}")

    output_dir = Path(args.output_dir)
    rendered, skipped, failed = render_pages(
        paths,
        output_dir,
        args.domain,
        args.min_bytes,
        args.sleep,
        args.force,
        args.wait_until,
        args.timeout_ms,
        args.render_wait_ms,
    )

    print("-" * 60)
    print(f"Rendered: {rendered}")
    print(f"Skipped (existing): {skipped}")
    print(f"Failed: {failed}")


if __name__ == "__main__":
    main()
