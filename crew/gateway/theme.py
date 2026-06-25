"""Shared visual tokens for gateway-rendered pages.

The instance dashboard (``routing.render_index``) and the oauth2-proxy
sign-in/error pages (``signin``) both pull their palette from here so the login
flow and the dashboard read as one UI. Change a colour once, in one place.
"""

PALETTE = {
    "bg": "#0e1116",
    "panel": "#161b22",
    "border": "#2a313c",
    "fg": "#d6dde6",
    "muted": "#7d8694",
    "accent": "#58e6a8",
    "accent2": "#f5e7c8",
    "down": "#5a6573",
}

# Inner declarations for a `:root { ... }` block: color-scheme plus the custom
# properties above. Consumed by render_index and the sign-in templates.
ROOT_VARS = "color-scheme: dark light; " + " ".join(
    f"--{k}:{v};" for k, v in PALETTE.items())


import base64 as _base64


def _mark_svg(size_attr: str) -> str:
    """The crew brand mark: a tilde wave in a rounded tile, accent-green. Shared
    by the header logo and the favicon so they stay identical."""
    return (
        f'<svg {size_attr} viewBox="0 0 32 32" fill="none" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<rect x="1.5" y="1.5" width="29" height="29" rx="7" '
        f'fill="{PALETTE["panel"]}" stroke="{PALETTE["border"]}"/>'
        f'<path d="M7 19c2-4 4.5-4 6.5-1.6S18 20 21 16s4-4 4-4" '
        f'stroke="{PALETTE["accent"]}" stroke-width="2.6" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>'
    )


def logo_svg(size: int) -> str:
    """Inline brand mark at `size` px for use as a header/page logo."""
    return _mark_svg(f'width="{size}" height="{size}" class="logo"')


# Same mark, base64-encoded as an SVG data URI for `<link rel="icon">`. Inlined
# because the sign-in page renders pre-auth, where external requests would bounce.
FAVICON_HREF = "data:image/svg+xml;base64," + _base64.b64encode(
    _mark_svg('width="32" height="32"').encode()).decode()
