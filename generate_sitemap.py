#!/usr/bin/env python3
"""Generate sitemap.xml from Wayback Machine CDX API"""
import urllib.request
import ssl
from datetime import datetime

def get_ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

def get_archived_urls():
    """Fetch all archived URLs from Wayback CDX API"""
    cdx_url = "https://web.archive.org/cdx/search/cdx?url=hero.page/*&output=json&fl=original&filter=statuscode:200&collapse=urlkey"
    
    ctx = get_ssl_context()
    req = urllib.request.Request(cdx_url, headers={"User-Agent": "Mozilla/5.0"})
    
    with urllib.request.urlopen(req, context=ctx, timeout=60) as response:
        import json
        data = json.loads(response.read().decode('utf-8'))
        # Skip header row
        urls = [row[0] for row in data[1:] if row[0].startswith('https://hero.page/')]
        return urls

def generate_sitemap(domain, urls):
    """Generate sitemap XML"""
    today = datetime.now().strftime('%Y-%m-%d')
    
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    
    for url in urls:
        # Convert hero.page URL to local path
        path = url.replace('https://hero.page', '')
        if not path:
            path = '/'
        
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
    
    print(f"Fetching archived URLs for hero.page...")
    urls = get_archived_urls()
    print(f"Found {len(urls)} URLs")
    
    sitemap = generate_sitemap(domain, urls[:1000])  # Limit to 1000 for now
    
    with open("sitemap.xml", "w") as f:
        f.write(sitemap)
    
    print(f"Generated sitemap.xml with {min(len(urls), 1000)} URLs")
