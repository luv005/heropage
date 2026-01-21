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
import os
import hashlib
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import threading
from content_utils import fix_content

# Playwright for rendering JavaScript
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("[WARNING] Playwright not available - pages will not render JavaScript")

PORT = int(os.environ.get("PORT", 8000))
CACHE_DIR = Path("cache")
WAYBACK_TIMESTAMP = "20240419175536"  # Full timestamp with rendered content
ORIGINAL_DOMAIN = "hero.page"
LOCAL_DOMAIN = os.environ.get("DOMAIN", "localhost:8000")  # Set DOMAIN env var in production
STATIC_ONLY = os.environ.get("STATIC_ONLY", "0").lower() in ("1", "true", "yes")
ALLOW_REMOTE_FETCH = not STATIC_ONLY and os.environ.get("ALLOW_REMOTE_FETCH", "1").lower() in (
    "1",
    "true",
    "yes",
)
QUIBEY_WAIT_UNTIL = os.environ.get("QUIBEY_WAIT_UNTIL", "domcontentloaded")
QUIBEY_TIMEOUT_MS = int(os.environ.get("QUIBEY_TIMEOUT_MS", "60000"))
QUIBEY_POST_WAIT_MS = int(os.environ.get("QUIBEY_POST_WAIT_MS", "1500"))
QUIBEY_STYLE_WAIT_MS = int(os.environ.get("QUIBEY_STYLE_WAIT_MS", "5000"))

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
    """Fetch a page from quibey.com using Playwright to render JavaScript"""
    quibey_url = f"https://quibey.com{path}"

    if not PLAYWRIGHT_AVAILABLE:
        print(f"[QUIBEY] Playwright not available, skipping {path}")
        return None, 500

    try:
        print(f"[QUIBEY] Rendering {path} with Playwright...")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            response = page.goto(
                quibey_url,
                wait_until=QUIBEY_WAIT_UNTIL,
                timeout=QUIBEY_TIMEOUT_MS,
            )

            # Check if response is HTML
            content_type = response.headers.get("content-type", "") if response else ""
            if "text/html" not in content_type:
                print(f"[QUIBEY] {path} -> not HTML ({content_type}), skipping")
                browser.close()
                return None, 404

            # Wait for styled-components/emotion styles to render (best effort)
            if QUIBEY_STYLE_WAIT_MS > 0:
                try:
                    page.wait_for_function(
                        """() => {
                            const hasStyled = Array.from(document.querySelectorAll('style[data-styled]'))
                                .some(style => style.textContent && style.textContent.trim().length > 0);
                            const hasEmotion = Array.from(document.querySelectorAll('style[data-emotion]'))
                                .some(style => style.textContent && style.textContent.trim().length > 0);
                            return hasStyled || hasEmotion;
                        }""",
                        timeout=QUIBEY_STYLE_WAIT_MS,
                    )
                except Exception:
                    pass
            page.wait_for_timeout(QUIBEY_POST_WAIT_MS)
            try:
                page.evaluate(
                    """() => {
                        const rules = [];
                        for (const sheet of Array.from(document.styleSheets || [])) {
                            const owner = sheet.ownerNode;
                            if (!owner) continue;
                            const isStyled = owner.hasAttribute && (
                                owner.hasAttribute('data-styled') || owner.hasAttribute('data-emotion')
                            );
                            if (!isStyled) continue;
                            try {
                                for (const rule of Array.from(sheet.cssRules || [])) {
                                    if (rule && rule.cssText) {
                                        rules.push(rule.cssText);
                                    }
                                }
                            } catch (err) {
                                // Ignore cross-origin stylesheets.
                            }
                        }
                        if (!rules.length) return;
                        let tag = document.getElementById('inline-styles-from-cssom');
                        if (!tag) {
                            tag = document.createElement('style');
                            tag.id = 'inline-styles-from-cssom';
                            document.head.appendChild(tag);
                        }
                        tag.textContent = rules.join('\\n');
                    }"""
                )
            except Exception:
                pass
            content = page.content()
            browser.close()

            # Verify it's HTML content
            if len(content) > 1000 and (content.strip().startswith("<!") or content.strip().startswith("<html")):
                print(f"[QUIBEY] {path} -> 200, {len(content)} bytes (rendered)")
                return content, 200
            return None, 404
    except Exception as e:
        print(f"[QUIBEY ERROR] {path}: {e}")
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
    """Try quibey.com first (with Playwright), then fall back to Wayback Machine"""
    # Try quibey.com first (renders JavaScript for full content)
    content, status = fetch_from_quibey(path)
    if content and status == 200:
        return content, status

    # Fall back to Wayback Machine
    return fetch_from_wayback(path)

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
        local_file = Path("static_pages") / path.lstrip("/")
        if local_file.is_dir():
            index_file = local_file / "index.html"
            if index_file.exists():
                local_file = index_file
        if local_file.exists() and local_file.is_file():
            self.serve_local_file(local_file)
            return

        # Check cache first
        cache_path = get_cache_path(path)
        if cache_path.exists():
            print(f"[CACHE] {path}")
            content = cache_path.read_text(encoding='utf-8')
            self.send_html_response(200, content)
            return

        if not ALLOW_REMOTE_FETCH:
            self.send_html_response(404, f"""
<!DOCTYPE html>
<html>
<head><title>Content Unavailable</title></head>
<body>
<h1>Content Unavailable</h1>
<p>The page {path} is not available in static-only mode.</p>
<p><a href="/">Go to homepage</a></p>
</body>
</html>""")
            return

        # Fetch from quibey.com first, then Wayback Machine
        print(f"[FETCH] {path}")
        content, status = fetch_content(path)

        if content and status == 200:
            # Fix content for local serving
            content = fix_content(content, path, LOCAL_DOMAIN)

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
    print(f"Remote fetch: {'enabled' if ALLOW_REMOTE_FETCH else 'disabled (static-only)'}")
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
