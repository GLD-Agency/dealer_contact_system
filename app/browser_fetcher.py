"""Browser-backed fetching for blocked dealer sites."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BrowserFetchResult:
    """Result of rendering a page in a real browser."""

    url: str
    final_url: str
    html: str
    status: str
    blocked_reason: str | None = None


class BrowserFetcher:
    """Fetch pages with Playwright so JS/cookie-protected sites have a second path."""

    def __init__(self, timeout_seconds: int) -> None:
        self.timeout_ms = timeout_seconds * 1000

    def fetch(self, url: str) -> BrowserFetchResult:
        """Render one URL in a headless browser."""

        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed. Run `pip install -r requirements.txt` "
                "and `playwright install chromium` before using browser retries."
            ) from exc

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                    page.wait_for_timeout(1500)
                    html = page.content()
                    final_url = page.url
                    blocked_reason = self._blocked_reason(html)
                    status = "blocked" if blocked_reason else "success"
                    return BrowserFetchResult(
                        url=url,
                        final_url=final_url,
                        html=html,
                        status=status,
                        blocked_reason=blocked_reason,
                    )
                except PlaywrightTimeoutError:
                    return BrowserFetchResult(
                        url=url,
                        final_url=url,
                        html="",
                        status="unavailable",
                        blocked_reason="browser_timeout",
                    )
                except PlaywrightError as exc:
                    return BrowserFetchResult(
                        url=url,
                        final_url=url,
                        html="",
                        status="unavailable",
                        blocked_reason=self._normalize_browser_error(str(exc)),
                    )
                finally:
                    browser.close()
        except PermissionError:
            return BrowserFetchResult(
                url=url,
                final_url=url,
                html="",
                status="unavailable",
                blocked_reason="browser_runtime_unavailable",
            )

    def _blocked_reason(self, html: str) -> str | None:
        """Return a best-effort blocked marker from rendered HTML."""

        lowered = html.lower()
        markers = [
            "access denied",
            "attention required! | cloudflare",
            "just a moment...",
            "enable javascript and cookies to continue",
            "captcha",
            "cf-browser-verification",
        ]
        for marker in markers:
            if marker in lowered:
                return marker
        return None

    def _normalize_browser_error(self, message: str) -> str:
        """Normalize a browser navigation/runtime error into a compact status reason."""

        lowered = message.lower()
        if "err_connection_refused" in lowered:
            return "browser_connection_refused"
        if "err_name_not_resolved" in lowered:
            return "browser_dns_error"
        if "net::err_" in lowered:
            return "browser_network_error"
        return "browser_navigation_error"
