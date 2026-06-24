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
