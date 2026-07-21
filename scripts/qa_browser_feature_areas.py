#!/usr/bin/env python3
"""Read-only browser QA for navigation, responsive layout, and search interactions.

Playwright is an optional QA dependency. This script never submits videos, mutates
subscriptions, sends chat messages, or invokes queue controls.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class BrowserCheck:
    area: str
    viewport: str
    status: str
    detail: str


PAGE_SPECS = (
    ("Dashboard", "/", "h1", "Transcribe videos without babysitting jobs"),
    ("Queue", "/queue", "h1", "Processing Queue"),
    ("Library", "/library", "h1", "Library"),
    ("Chat", "/chat", ".chat-page-shell", ""),
    ("Search", "/search", "h1", "Chat with Library"),
    ("Global Search", "/global-search", "h1", "Global Search"),
)

VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
    "mobile": {"width": 390, "height": 844},
}


def render_markdown(checks: list[BrowserCheck]) -> str:
    lines = [
        "| Browser area | Viewport | Result | Detail |",
        "|---|---|---:|---|",
    ]
    for check in checks:
        detail = check.detail.replace("|", "\\|")
        lines.append(
            f"| {check.area} | {check.viewport} | {check.status.upper()} | {detail} |"
        )
    passed = sum(check.status == "pass" for check in checks)
    lines.extend(["", f"Result: **{passed}/{len(checks)} passed**."])
    return "\n".join(lines) + "\n"


def _same_origin(url: str, base_url: str) -> bool:
    target = urlparse(url)
    base = urlparse(base_url)
    return (target.scheme, target.netloc) == (base.scheme, base.netloc)


def _page_check(
    page: Any,
    base_url: str,
    area: str,
    path: str,
    marker_selector: str,
    marker: str,
    viewport: str,
) -> BrowserCheck:
    page_errors: list[str] = []
    bad_responses: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    def record_response(response: Any) -> None:
        if _same_origin(response.url, base_url) and response.status >= 400:
            bad_responses.append(f"{response.status} {response.url}")

    page.on("response", record_response)
    try:
        response = page.goto(base_url.rstrip("/") + path, wait_until="domcontentloaded")
        page.wait_for_timeout(700)
        marker_text = page.locator(marker_selector).first.inner_text()
        overflow = page.evaluate(
            "document.documentElement.scrollWidth > window.innerWidth + 1"
        )
        problems: list[str] = []
        if response is None or response.status != 200:
            problems.append(f"navigation HTTP {getattr(response, 'status', 'none')}")
        if marker not in marker_text:
            problems.append(f"page marker {marker!r} missing from {marker_text!r}")
        if overflow:
            offenders = page.evaluate(
                """Array.from(document.querySelectorAll('body *'))
                    .map((el) => ({
                        tag: el.tagName.toLowerCase(),
                        id: el.id,
                        cls: typeof el.className === 'string' ? el.className : '',
                        right: Math.round(el.getBoundingClientRect().right),
                        width: Math.round(el.getBoundingClientRect().width)
                    }))
                    .filter((item) => item.right > window.innerWidth + 1)
                    .slice(0, 3)"""
            )
            problems.append(f"horizontal viewport overflow: {offenders}")
        if page_errors:
            problems.append("page error: " + page_errors[0][:180])
        if bad_responses:
            problems.append("same-origin response: " + bad_responses[0][:180])
        detail = "; ".join(problems) if problems else "HTTP 200; marker and viewport fit pass"
        return BrowserCheck(area, viewport, "fail" if problems else "pass", detail)
    except Exception as exc:  # noqa: BLE001 - QA reports failures instead of aborting
        return BrowserCheck(area, viewport, "fail", f"{exc.__class__.__name__}: {exc}")


def _interaction_check(area: str, viewport: str, action) -> BrowserCheck:  # noqa: ANN001
    try:
        detail = action()
        return BrowserCheck(area, viewport, "pass", detail)
    except Exception as exc:  # noqa: BLE001
        return BrowserCheck(area, viewport, "fail", f"{exc.__class__.__name__}: {exc}")


def run_browser_checks(base_url: str, api_key: str | None = None, *, headless: bool = True) -> list[BrowserCheck]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - depends on optional runtime
        raise RuntimeError(
            "Playwright is not installed in this interpreter; run with an existing "
            "Playwright environment or install the optional QA dependency"
        ) from exc

    checks: list[BrowserCheck] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        try:
            for viewport_name, viewport in VIEWPORTS.items():
                headers = {"X-API-Key": api_key} if api_key else None
                context = browser.new_context(viewport=viewport, extra_http_headers=headers)
                context.set_default_timeout(8_000)
                try:
                    for area, path, marker_selector, marker in PAGE_SPECS:
                        checks.append(
                            _page_check(
                                context.new_page(),
                                base_url,
                                area,
                                path,
                                marker_selector,
                                marker,
                                viewport_name,
                            )
                        )

                    page = context.new_page()

                    def library_tabs() -> str:
                        page.goto(base_url.rstrip("/") + "/library", wait_until="domcontentloaded")
                        page.locator('.tab-item[href="/library?tab=channels"]').click()
                        page.wait_for_url("**/library?tab=channels")
                        if page.locator(".channel-card-wrapper").count() < 1:
                            raise AssertionError("no channel cards rendered")
                        page.locator('.tab-item[href="/library?tab=videos"]').click()
                        page.wait_for_url("**/library?tab=videos")
                        if page.locator("#video-list-content").count() != 1:
                            raise AssertionError("video tab content missing")
                        return "Videos and Channels tabs navigate and render"

                    checks.append(_interaction_check("Library tabs", viewport_name, library_tabs))

                    if viewport_name == "mobile":
                        def mobile_nav() -> str:
                            page.goto(base_url.rstrip("/") + "/", wait_until="domcontentloaded")
                            page.locator(".nav-mobile-toggle").click()
                            if "is-open" not in (page.locator("#mobile-nav").get_attribute("class") or ""):
                                raise AssertionError("mobile navigation did not open")
                            return "Mobile navigation opens and exposes links"

                        checks.append(_interaction_check("Mobile navigation", viewport_name, mobile_nav))

                        def chat_sidebar() -> str:
                            page.goto(base_url.rstrip("/") + "/chat", wait_until="domcontentloaded")
                            page.locator(".chat-mobile-toggle").click()
                            if "is-open" not in (page.locator("#chat-sidebar").get_attribute("class") or ""):
                                raise AssertionError("chat sidebar did not open")
                            return "Mobile chat sidebar opens"

                        checks.append(_interaction_check("Chat sidebar", viewport_name, chat_sidebar))

                    def search() -> str:
                        page.goto(base_url.rstrip("/") + "/search", wait_until="domcontentloaded")
                        page.locator("#search-query").fill("AI agents")
                        with page.expect_response(lambda response: "/api/search" in response.url) as info:
                            page.locator("#search-query").press("Enter")
                        if info.value.status != 200:
                            raise AssertionError(f"search returned HTTP {info.value.status}")
                        page.wait_for_function(
                            "document.querySelector('#search-results').innerText.trim().length > 0"
                        )
                        return "HTMX search submission returned rendered results"

                    checks.append(_interaction_check("Search interaction", viewport_name, search))

                    def global_search() -> str:
                        page.goto(base_url.rstrip("/") + "/global-search", wait_until="domcontentloaded")
                        page.locator("select[name=source_type]").select_option("summary")
                        page.locator("#global-search-query").fill("AI agents")
                        with page.expect_response(lambda response: "/api/global-search" in response.url) as info:
                            page.locator("#global-search-query").press("Enter")
                        if info.value.status != 200:
                            raise AssertionError(f"global search returned HTTP {info.value.status}")
                        page.wait_for_function(
                            "document.querySelector('#global-search-results').innerText.trim().length > 0"
                        )
                        return "Global search filter and HTMX submission rendered results"

                    checks.append(
                        _interaction_check("Global Search interaction", viewport_name, global_search)
                    )
                finally:
                    context.close()
        finally:
            browser.close()
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    checks = run_browser_checks(args.base_url, args.api_key, headless=not args.headed)
    print(json.dumps([asdict(check) for check in checks], indent=2) if args.json else render_markdown(checks))
    return 1 if any(check.status == "fail" for check in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
