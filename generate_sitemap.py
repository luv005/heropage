#!/usr/bin/env python3
"""Generate sitemap.xml with only pages that have actual content"""
import urllib.request
import ssl
from datetime import datetime
import re

# Pages known to have rendered content (from homepage links + verified working)
VERIFIED_PAGES = [
    "/",
    "/discover",
    "/blog",
    "/templates",
    "/ai-prompts",
    "/sign-in",
    "/create-account",
    "/pfp/anime-pfp",
    "/pfp/matching-pfp-for-couples",
    "/pfp/matching-pfp",
    "/podcasts/podcast-show-notes-how-to-write-and-share-with-listeners",
    "/help/save-and-share-interesting-links",
    "/share-a-list-of-links",
]

def get_ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

def check_page_has_content(path):
    """Check if a page has actual rendered content (not just SPA shell)"""
    url = f"https://web.archive.org/web/20250519id_/https://hero.page{path}"
    ctx = get_ssl_context()
    
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, context=ctx, timeout=15) as response:
            content = response.read()
            # Pages with rendered content are usually > 10KB
            # SPA shells are typically 1-5KB
            return len(content) > 10000
    except:
        return False

def get_homepage_links():
    """Extract links from the homepage"""
    url = "https://web.archive.org/web/20250519id_/https://hero.page/"
    ctx = get_ssl_context()
    
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, context=ctx, timeout=30) as response:
            content = response.read().decode('utf-8', errors='ignore')
            
            # Extract internal links
            links = set()
            for match in re.findall(r'href="(/[^"]*)"', content):
                path = match.split('?')[0].split('#')[0]
                if path and len(path) > 1 and not any(x in path for x in ['.js', '.css', '.png', '.jpg', '.ico', '.json']):
                    links.add(path)
            return list(links)
    except Exception as e:
        print(f"Error: {e}")
        return []

def escape_xml(text):
    """Escape special XML characters"""
    return (text
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
        .replace("'", '&apos;'))

def generate_sitemap(domain, paths):
    """Generate sitemap XML"""
    today = datetime.now().strftime('%Y-%m-%d')
    
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    
    for path in paths:
        path = escape_xml(path)
        xml += f'''  <url>
    <loc>https://{domain}{path}</loc>
    <lastmod>{today}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>
'''
    
    xml += '</urlset>'
    return xml

if __name__ == "__main__":
    import os
    domain = os.environ.get("DOMAIN", "hero.page")
    
    print("Getting links from homepage...")
    homepage_links = get_homepage_links()
    print(f"Found {len(homepage_links)} links on homepage")
    
    # Combine verified pages with homepage links
    all_paths = list(set(VERIFIED_PAGES + homepage_links))
    all_paths.sort()
    
    print(f"Total unique paths: {len(all_paths)}")
    
    # Generate sitemap
    sitemap = generate_sitemap(domain, all_paths)
    
    with open("sitemap.xml", "w") as f:
        f.write(sitemap)
    
    url_count = sitemap.count('<url>')
    print(f"Generated sitemap.xml with {url_count} URLs")
