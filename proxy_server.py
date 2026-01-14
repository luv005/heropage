#!/usr/bin/env python3
"""
Proxy server that fetches hero.page content from Wayback Machine
and serves it locally for SEO purposes.
"""
import http.server
import socketserver
import urllib.request
import urllib.parse
import ssl
import re
import os
import hashlib
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import threading

PORT = int(os.environ.get("PORT", 8000))
CACHE_DIR = Path("cache")
WAYBACK_TIMESTAMP = "20250519"  # Use a specific timestamp for consistency
ORIGINAL_DOMAIN = "hero.page"
LOCAL_DOMAIN = os.environ.get("DOMAIN", "localhost:8000")  # Set DOMAIN env var in production

# Create cache directory
CACHE_DIR.mkdir(exist_ok=True)

def get_ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

def get_cache_path(path):
    """Generate cache file path for a URL path"""
    safe_name = hashlib.md5(path.encode()).hexdigest()
    return CACHE_DIR / f"{safe_name}.html"

def fetch_from_quibey(path):
    """Fetch a page from quibey.com (mirror site)"""
    quibey_url = f"https://quibey.com{path}"
    ctx = get_ssl_context()

    try:
        req = urllib.request.Request(quibey_url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, context=ctx, timeout=30) as response:
            content = response.read().decode('utf-8', errors='ignore')
            if len(content) > 5000:  # Has actual content
                print(f"[QUIBEY] {path} -> {response.status}, {len(content)} bytes")
                return content, response.status
            return None, 404
    except urllib.error.HTTPError as e:
        return None, e.code
    except Exception as e:
        return None, 500


def fetch_from_wayback(path):
    """Fetch a page from Wayback Machine (fallback)"""
    wayback_url = f"https://web.archive.org/web/{WAYBACK_TIMESTAMP}id_/https://{ORIGINAL_DOMAIN}{path}"
    ctx = get_ssl_context()

    try:
        req = urllib.request.Request(wayback_url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
        })
        with urllib.request.urlopen(req, context=ctx, timeout=45) as response:
            content = response.read().decode('utf-8', errors='ignore')
            print(f"[WAYBACK] {path} -> {response.status}, {len(content)} bytes")
            return content, response.status
    except urllib.error.HTTPError as e:
        print(f"[HTTP ERROR] {path}: {e.code}")
        return None, e.code
    except Exception as e:
        print(f"[ERROR] {path}: {e}")
        return None, 500


def fetch_content(path):
    """Try quibey.com first, then fall back to Wayback Machine"""
    # Try quibey.com first (faster, has rendered content)
    content, status = fetch_from_quibey(path)
    if content and status == 200:
        return content, status

    # Fall back to Wayback Machine
    return fetch_from_wayback(path)

def fix_content(content, path):
    """Fix links and references to work locally"""
    # Remove Wayback Machine wrapper
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
    # Remove external links to quibey.com (keep the text, remove the link)
    content = re.sub(
        r'<a[^>]*href="https?://quibey\.com[^"]*"[^>]*>(.*?)</a>',
        r'\1',
        content,
        flags=re.DOTALL
    )
    # Also remove any remaining quibey.com URLs in href/src attributes
    content = re.sub(
        r'https://quibey\.com/',
        '/',
        content
    )
    content = re.sub(
        r'https://quibey\.com',
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
    # Fix protocol-relative URLs
    content = re.sub(
        r'//hero\.page/',
        '/',
        content
    )
    content = re.sub(
        r'//quibey\.com/',
        '/',
        content
    )

    # Replace all Quibey references with Hero (case insensitive)
    content = re.sub(r'[Qq]uibey', 'Hero', content)

    # Remove existing canonical tags and add new one for hero.page
    content = re.sub(r'<link[^>]*rel="canonical"[^>]*/>', '', content)
    content = re.sub(r'<link[^>]*rel="canonical"[^>]*>', '', content)
    if '<head>' in content:
        canonical = f'<link rel="canonical" href="https://{LOCAL_DOMAIN}{path}" />'
        content = content.replace('<head>', f'<head>\n{canonical}', 1)

    # Remove React JavaScript to make links work as plain HTML
    # Remove main.js script which handles client-side routing
    content = re.sub(r'<script[^>]*src="[^"]*main\.[^"]*\.js"[^>]*></script>', '', content)
    content = re.sub(r'<script[^>]*src="[^"]*chunk\.[^"]*\.js"[^>]*></script>', '', content)

    # Also remove inline scripts that might interfere
    content = re.sub(r'<script>window\.__REACT.*?</script>', '', content, flags=re.DOTALL)

    # Fix pointer-events: none that blocks clicking
    content = content.replace('pointer-events: none', 'pointer-events: auto')
    content = content.replace('pointer-events:none', 'pointer-events:auto')

    # Add CSS override to ensure all links are clickable
    if '</head>' in content:
        css_fix = '''<style>
a, a *, [href] { pointer-events: auto !important; cursor: pointer !important; }
</style>'''
        content = content.replace('</head>', f'{css_fix}</head>')

    # If page is an SPA shell (empty root div), add a fallback message with metadata
    if '<div class="main-window" id="root"></div>' in content or '<div id="root"></div>' in content:
        # Extract title and description from meta tags
        title_match = re.search(r'<title>([^<]+)</title>', content)
        desc_match = re.search(r'<meta name="description" content="([^"]+)"', content)

        title = title_match.group(1) if title_match else 'Hero Page'
        description = desc_match.group(1) if desc_match else ''

        fallback_content = f'''
<div style="max-width: 800px; margin: 50px auto; padding: 20px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
    <h1 style="color: #333;">{title}</h1>
    <p style="color: #666; font-size: 18px;">{description}</p>
    <hr style="margin: 30px 0; border: none; border-top: 1px solid #eee;">
    <p style="color: #999;">This page's full content was not archived. <a href="/" style="color: #e82f64;">Return to homepage</a></p>
</div>
'''
        content = content.replace('<div class="main-window" id="root"></div>', f'<div class="main-window" id="root">{fallback_content}</div>')
        content = content.replace('<div id="root"></div>', f'<div id="root">{fallback_content}</div>')

    return content

class WaybackProxyHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split('?')[0]  # Remove query string

        # Serve SEO files (sitemap.xml, robots.txt)
        if path in ['/sitemap.xml', '/robots.txt']:
            seo_file = Path(path.lstrip('/'))
            if seo_file.exists():
                content = seo_file.read_text(encoding='utf-8')
                content_type = 'application/xml' if path == '/sitemap.xml' else 'text/plain'
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', len(content.encode('utf-8')))
                self.end_headers()
                self.wfile.write(content.encode('utf-8'))
                return

        # Serve static assets directly if they exist locally
        local_file = Path("static_pages") / path.lstrip('/')
        if local_file.exists() and local_file.is_file():
            self.serve_local_file(local_file)
            return

        # Check for directory index
        if local_file.is_dir():
            index_file = local_file / "index.html"
            if index_file.exists():
                local_file = index_file

        # Check cache first
        cache_path = get_cache_path(path)
        if cache_path.exists():
            print(f"[CACHE] {path}")
            content = cache_path.read_text(encoding='utf-8')
            self.send_html_response(200, content)
            return

        # Fetch from quibey.com first, then Wayback Machine
        print(f"[FETCH] {path}")
        content, status = fetch_content(path)

        if content and status == 200:
            # Fix content for local serving
            content = fix_content(content, path)

            # Cache all content (even small SPA shells have SEO value)
            cache_path.write_text(content, encoding='utf-8')

            self.send_html_response(200, content)
        elif status == 200 and not content:
            # Empty response from Wayback
            print(f"[EMPTY] {path}")
            self.send_html_response(404, f"""
<!DOCTYPE html>
<html>
<head><title>Content Unavailable</title></head>
<body>
<h1>Content Unavailable</h1>
<p>The archived content for {path} could not be retrieved.</p>
<p><a href="/">Go to homepage</a></p>
</body>
</html>""")
        else:
            # Try to serve a simple 404 page
            print(f"[404] {path} - status: {status}")
            self.send_html_response(404, f"""
<!DOCTYPE html>
<html>
<head><title>Page Not Found</title></head>
<body>
<h1>404 - Page Not Found</h1>
<p>The page {path} could not be found.</p>
<p><a href="/">Go to homepage</a></p>
</body>
</html>
""")

    def serve_local_file(self, filepath):
        """Serve a local file"""
        try:
            content = filepath.read_bytes()
            # Determine content type
            ext = filepath.suffix.lower()
            content_types = {
                '.html': 'text/html',
                '.css': 'text/css',
                '.js': 'application/javascript',
                '.json': 'application/json',
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.gif': 'image/gif',
                '.svg': 'image/svg+xml',
                '.ico': 'image/x-icon',
                '.webp': 'image/webp',
            }
            content_type = content_types.get(ext, 'application/octet-stream')

            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        except BrokenPipeError:
            pass  # Client disconnected
        except Exception as e:
            self.send_error(500, str(e))

    def send_html_response(self, status, content):
        """Send an HTML response"""
        try:
            content_bytes = content.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', len(content_bytes))
            # SEO-friendly headers
            self.send_header('X-Robots-Tag', 'index, follow')
            self.end_headers()
            self.wfile.write(content_bytes)
        except BrokenPipeError:
            pass  # Client disconnected, ignore

    def log_message(self, format, *args):
        """Custom log format"""
        print(f"[{self.log_date_time_string()}] {args[0]}")


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Handle requests in separate threads for better concurrency"""
    daemon_threads = True


def run_server():
    """Run the proxy server"""
    server_address = ('', PORT)
    httpd = ThreadedHTTPServer(server_address, WaybackProxyHandler)

    print("=" * 60)
    print(f"Wayback Proxy Server for hero.page")
    print("=" * 60)
    print(f"Server running at http://localhost:{PORT}")
    print(f"Proxying content from Wayback Machine")
    print(f"Cache directory: {CACHE_DIR.absolute()}")
    print()
    print("For production, change LOCAL_DOMAIN to your actual domain")
    print("Press Ctrl+C to stop")
    print("=" * 60)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        httpd.shutdown()

if __name__ == "__main__":
    run_server()
