"""Sandboxed HTML iframe rendering.

Injects a fully sandboxed ``<iframe>`` with ``srcdoc`` onto a Playwright
page.  A CSP ``<meta>`` tag inside the document restricts resource loading
to explicitly allowed domains.  The sandbox attribute blocks scripts, forms,
navigation, and same-origin access.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

    from joinly.types import UIHtmlContent

_IFRAME_STYLE = (
    "position:fixed;inset:0;width:100vw;height:100vh;"
    "border:none;background:transparent;pointer-events:none;"
    "z-index:99999"
)


def _build_srcdoc(content: UIHtmlContent) -> str:
    """Build an iframe srcdoc with an embedded CSP meta tag."""
    directives = ["default-src 'none'", "style-src 'unsafe-inline'"]
    if content.csp and content.csp.resource_domains:
        domains = " ".join(content.csp.resource_domains)
        directives.append(f"img-src {domains}")
    csp = "; ".join(directives)
    return (
        "<!doctype html><html><head>"
        f'<meta http-equiv="Content-Security-Policy" content="{csp}">'
        f'</head><body style="margin:0">{content.html or ""}</body></html>'
    )


async def set_iframe(page: Page, content: UIHtmlContent, *, iframe_id: str) -> None:
    """Create or update a sandboxed iframe on *page*."""
    srcdoc = _build_srcdoc(content)
    await page.evaluate(
        """([id, srcdoc, style]) => {
            let f = document.getElementById(id);
            if (!f) {
                f = document.createElement('iframe');
                f.id = id;
                f.sandbox = '';
                f.style.cssText = style;
                document.body.appendChild(f);
            }
            f.srcdoc = srcdoc;
        }""",
        [iframe_id, srcdoc, _IFRAME_STYLE],
    )


async def clear_iframe(page: Page, *, iframe_id: str) -> None:
    """Remove a sandboxed iframe from *page*."""
    await page.evaluate(
        """(id) => {
            const f = document.getElementById(id);
            if (f) f.remove();
        }""",
        iframe_id,
    )
