import re


def fix_content(content, path, domain):
    """Fix links and references to work locally."""
    if not path.startswith("/"):
        path = "/" + path

    # Remove Wayback Machine wrapper
    content = re.sub(
        r"https://web\.archive\.org/web/\d+id_/https://hero\.page",
        "",
        content,
    )
    content = re.sub(
        r"https://web\.archive\.org/web/\d+/https://hero\.page",
        "",
        content,
    )

    # Rewrite absolute Quibey/Hero links to local paths.
    content = re.sub(r"https?://quibey\.com/", "/", content)
    content = re.sub(r"https?://quibey\.com(?=[\"'])", "/", content)
    content = re.sub(r"https?://hero\.page/", "/", content)
    content = re.sub(r"https?://hero\.page(?=[\"'])", "/", content)
    content = re.sub(r"//hero\.page/", "/", content)
    content = re.sub(r"//hero\.page(?=[\"'])", "/", content)
    content = re.sub(r"//quibey\.com/", "/", content)
    content = re.sub(r"//quibey\.com(?=[\"'])", "/", content)

    # Fix CDN hosts for assets (avoid broken Hero/hero.page CDN references).
    content = re.sub(
        r"https?://cdn-2\.hero\.com",
        "https://cdn-2.quibey.com",
        content,
        flags=re.IGNORECASE,
    )
    content = re.sub(
        r"https?://cdn\.hero\.page",
        "https://cdn-2.quibey.com",
        content,
        flags=re.IGNORECASE,
    )
    content = re.sub(
        r"//cdn-2\.hero\.com",
        "//cdn-2.quibey.com",
        content,
        flags=re.IGNORECASE,
    )
    content = re.sub(
        r"//cdn\.hero\.page",
        "//cdn-2.quibey.com",
        content,
        flags=re.IGNORECASE,
    )

    # Remove existing canonical tags and add new one for hero.page.
    content = re.sub(
        r"<link[^>]*rel=[\"']canonical[\"'][^>]*?/?>",
        "",
        content,
        flags=re.IGNORECASE,
    )
    canonical = f'<link rel="canonical" href="https://{domain}{path}" />'
    if re.search(r"<head[^>]*>", content):
        content = re.sub(
            r"<head[^>]*>",
            lambda match: f"{match.group(0)}\n{canonical}",
            content,
            count=1,
        )

    # Remove React JavaScript to make links work as plain HTML.
    content = re.sub(
        r'<script[^>]*src="[^"]*main\.[^"]*\.js"[^>]*></script>',
        "",
        content,
    )
    content = re.sub(
        r'<script[^>]*src="[^"]*chunk\.[^"]*\.js"[^>]*></script>',
        "",
        content,
    )

    # Also remove inline scripts that might interfere.
    content = re.sub(
        r"<script>window\.__REACT.*?</script>",
        "",
        content,
        flags=re.DOTALL,
    )

    # Fix pointer-events: none that blocks clicking.
    content = content.replace("pointer-events: none", "pointer-events: auto")
    content = content.replace("pointer-events:none", "pointer-events:auto")

    # Add CSS override to ensure all links are clickable.
    if "</head>" in content:
        css_fix = """<style>
a, a *, [href] { pointer-events: auto !important; cursor: pointer !important; }
</style>"""
        content = content.replace("</head>", f"{css_fix}</head>")

    # If page is an SPA shell (empty root div), add a fallback message with metadata.
    if (
        '<div class="main-window" id="root"></div>' in content
        or '<div id="root"></div>' in content
    ):
        # Extract title and description from meta tags.
        title_match = re.search(r"<title>([^<]+)</title>", content)
        desc_match = re.search(
            r'<meta name="description" content="([^"]+)"',
            content,
        )

        title = title_match.group(1) if title_match else "Hero Page"
        description = desc_match.group(1) if desc_match else ""

        fallback_content = f"""
<div style="max-width: 800px; margin: 50px auto; padding: 20px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
    <h1 style="color: #333;">{title}</h1>
    <p style="color: #666; font-size: 18px;">{description}</p>
    <hr style="margin: 30px 0; border: none; border-top: 1px solid #eee;">
    <p style="color: #999;">This page's full content was not archived. <a href="/" style="color: #e82f64;">Return to homepage</a></p>
</div>
"""
        content = content.replace(
            '<div class="main-window" id="root"></div>',
            f'<div class="main-window" id="root">{fallback_content}</div>',
        )
        content = content.replace(
            '<div id="root"></div>',
            f'<div id="root">{fallback_content}</div>',
        )

    return content
