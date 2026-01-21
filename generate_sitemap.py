#!/usr/bin/env python3
"""Generate sitemap.xml from CSV links and local static pages."""
import csv
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

STATIC_DIR = Path(os.environ.get("STATIC_DIR", "static_pages"))
CSV_PATH = os.environ.get("CSV_PATH", "")
DOMAIN = os.environ.get("DOMAIN", "hero.page")
SITEMAP_HOSTS = [
    host.strip()
    for host in os.environ.get("SITEMAP_HOSTS", "hero.page").split(",")
    if host.strip()
]
INLINE_STYLE_RE = re.compile(
    r'<style[^>]*id="inline-styles-from-cssom"[^>]*>(.*?)</style>',
    re.DOTALL,
)


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


def load_csv_paths(csv_path, allowed_hosts):
    paths = set()
    skipped_hosts = {}

    if not csv_path:
        return paths, skipped_hosts

    csv_file = Path(csv_path)
    if not csv_file.exists():
        return paths, skipped_hosts

    with open(csv_file, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            url = row.get("URL") or row.get("Url") or row.get("url")
            if not url:
                continue
            parsed = urlparse(url.strip())
            host = parsed.hostname or ""
            if allowed_hosts and host not in allowed_hosts:
                skipped_hosts[host] = skipped_hosts.get(host, 0) + 1
                continue
            path = normalize_path(parsed.path or "/")
            paths.add(path)

    return paths, skipped_hosts


def path_from_html_file(static_dir, html_file):
    try:
        rel = html_file.relative_to(static_dir)
    except ValueError:
        return None
    if rel.parts and rel.parts[0] == "static":
        return None
    if rel.name == "index.html":
        if rel.parent == Path("."):
            path = "/"
        else:
            path = "/" + "/".join(rel.parent.parts)
    else:
        path = "/" + "/".join(rel.parts)
    return normalize_path(path)


def has_inline_css(html_file):
    try:
        content = html_file.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    match = INLINE_STYLE_RE.search(content)
    if not match:
        return False
    inline_css = match.group(1).strip()
    return bool(inline_css and "{" in inline_css)


def load_static_paths(static_dir):
    paths = set()
    valid_paths = set()
    if not static_dir.exists():
        return paths, valid_paths

    for html_file in static_dir.rglob("*.html"):
        path = path_from_html_file(static_dir, html_file)
        if not path:
            continue
        paths.add(path)
        if has_inline_css(html_file):
            valid_paths.add(path)

    return paths, valid_paths


def escape_xml(text):
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def generate_sitemap(domain, paths):
    today = datetime.now().strftime("%Y-%m-%d")

    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'

    for path in paths:
        path = escape_xml(path)
        xml += (
            "  <url>\n"
            f"    <loc>https://{domain}{path}</loc>\n"
            f"    <lastmod>{today}</lastmod>\n"
            "    <changefreq>monthly</changefreq>\n"
            "    <priority>0.8</priority>\n"
            "  </url>\n"
        )

    xml += "</urlset>"
    return xml


if __name__ == "__main__":
    csv_paths, skipped_hosts = load_csv_paths(CSV_PATH, SITEMAP_HOSTS)
    static_paths, valid_paths = load_static_paths(STATIC_DIR)
    included_csv = csv_paths.intersection(valid_paths)
    all_paths = sorted(valid_paths)

    if skipped_hosts:
        skipped_summary = ", ".join(
            f"{host}:{count}" for host, count in sorted(skipped_hosts.items())
        )
        print(f"Skipped hosts from CSV: {skipped_summary}")

    print(f"CSV paths: {len(csv_paths)}")
    print(f"Static paths: {len(static_paths)}")
    print(f"CSV paths with inline CSS: {len(included_csv)}")
    print(f"Static paths with inline CSS: {len(valid_paths)}")
    print(f"Total unique paths: {len(all_paths)}")

    sitemap = generate_sitemap(DOMAIN, all_paths)
    with open("sitemap.xml", "w", encoding="utf-8") as handle:
        handle.write(sitemap)

    url_count = sitemap.count("<url>")
    print(f"Generated sitemap.xml with {url_count} URLs")
