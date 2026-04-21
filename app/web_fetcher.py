"""HTTP fetching helpers for dealer website enrichment."""

from __future__ import annotations

from dataclasses import dataclass

import requests
import urllib3


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

NO_PROXY = {
    "http": "",
    "https": "",
}

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


@dataclass(frozen=True)
class FetchResult:
    """Represents a fetched page."""

    url: str
    status_code: int
    final_url: str
    html: str

    @property
    def ok(self) -> bool:
        """Return True when the fetch produced a usable HTML page."""

        return 200 <= self.status_code < 400 and self.parseable

    @property
    def parseable(self) -> bool:
        """Return True when the response looks like a real page, not a bot block."""

        return bool(self.html) and not self.blocked

    @property
    def blocked(self) -> bool:
        """Return True when the response matches common anti-bot block pages."""

        return self.blocked_reason is not None

    @property
    def blocked_reason(self) -> str | None:
        """Return the matched anti-bot or maintenance marker when present."""

        lowered = self.html.lower()
        blocked_markers = [
            "access denied",
            "attention required! | cloudflare",
            "just a moment...",
            "enable javascript and cookies to continue",
            "site currently not available",
            "page unavailable",
            "sorry, we're under maintenance",
            "access error | autonation",
            "captcha-delivery.com",
            "please enable js and disable any ad blocker",
            "cf-wrapper",
            "errors.edgesuite.net",
        ]
        for marker in blocked_markers:
            if marker in lowered:
                return marker
        return None


class WebFetcher:
    """Fetch public web pages with a consistent session setup."""

    def __init__(self, timeout_seconds: int) -> None:
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update(DEFAULT_HEADERS)

    def fetch(self, url: str) -> FetchResult | None:
        """Fetch a URL and return its contents when possible."""

        try:
            response = self.session.get(
                url,
                allow_redirects=True,
                timeout=self.timeout_seconds,
                proxies=NO_PROXY,
            )
            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                return None
            return FetchResult(
                url=url,
                status_code=response.status_code,
                final_url=str(response.url),
                html=response.text,
            )
        except requests.RequestException:
            return None

    def resolve(self, url: str) -> tuple[int | None, str]:
        """Resolve a URL to its final destination even when content fetching fails."""

        try:
            session = requests.Session()
            session.trust_env = False
            response = session.get(
                url,
                headers=DEFAULT_HEADERS,
                allow_redirects=True,
                timeout=max(self.timeout_seconds, 20),
                stream=True,
                verify=False,
                proxies=NO_PROXY,
            )
            return response.status_code, str(response.url)
        except requests.RequestException:
            return None, url
