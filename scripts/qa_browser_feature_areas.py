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
    ("Reader home", "/", "h1", "Read what you saved"),
    ("Operations dashboard", "/ops", "h1", "Transcribe videos without babysitting jobs"),
    ("Queue", "/ops/queue", "h1", "Processing Queue"),
    ("Library", "/read", "h1", "Library"),
    ("Chat", "/chat", ".chat-page-shell", ""),
    ("Research", "/search", "h1", "Search or ask"),
    ("Highlights notebook", "/read/highlights", "h1", "Highlights and notes"),
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
        unnamed_controls = page.evaluate(
            """Array.from(document.querySelectorAll('button,input:not([type=hidden]),select,textarea'))
                .filter((el) => {
                    const style = getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    if (!el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true}) || style.display === 'none' || style.visibility === 'hidden' || !rect.width || !rect.height) return false;
                    const labelled = el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') ||
                        el.getAttribute('title') || el.innerText?.trim() || el.value ||
                        Array.from(el.labels || []).some((label) => label.innerText.trim());
                    return !labelled;
                })
                .slice(0, 3)
                .map((el) => el.id || el.className || el.tagName.toLowerCase())"""
        )
        if unnamed_controls:
            problems.append(f"unnamed interactive controls: {unnamed_controls}")
        if viewport == "mobile":
            undersized_controls = page.evaluate(
                """Array.from(document.querySelectorAll('button,.btn,.input-field,select,textarea'))
                    .filter((el) => {
                        const style = getComputedStyle(el); const rect = el.getBoundingClientRect();
                        return el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true}) && style.display !== 'none' && style.visibility !== 'hidden' && rect.width && rect.height &&
                            (rect.width < 44 || rect.height < 44);
                    })
                    .slice(0, 3)
                    .map((el) => ({id: el.id, cls: el.className, width: Math.round(el.getBoundingClientRect().width), height: Math.round(el.getBoundingClientRect().height)}))"""
            )
            if undersized_controls:
                problems.append(f"mobile targets below 44px: {undersized_controls}")
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
                        page.goto(base_url.rstrip("/") + "/read", wait_until="domcontentloaded")
                        page.locator('.tab-item[href="/read?tab=channels"]').click()
                        page.wait_for_url("**/read?tab=channels")
                        if page.locator(".channel-card-wrapper").count() < 1:
                            raise AssertionError("no channel cards rendered")
                        page.locator('.tab-item[href="/read?tab=videos"]').click()
                        page.wait_for_url("**/read?tab=videos")
                        if page.locator("#video-list-content").count() != 1:
                            raise AssertionError("video tab content missing")
                        return "Videos and Channels tabs navigate and render"

                    checks.append(_interaction_check("Library tabs", viewport_name, library_tabs))

                    def toggle_transport() -> str:
                        page.route(
                            "**/api/videos/*/chat-toggle",
                            lambda route: route.fulfill(
                                status=200,
                                content_type="application/json",
                                body='{"chat_enabled":true}',
                            ),
                        )
                        try:
                            page.goto(base_url.rstrip("/") + "/read?tab=videos", wait_until="domcontentloaded")
                            toggle = page.locator('input[hx-patch^="/api/videos/"]').first
                            toggle_label = toggle.locator("xpath=ancestor::label[1]")
                            with page.expect_request(lambda request: "/chat-toggle" in request.url) as info:
                                toggle_label.click()
                            request = info.value
                            if "application/json" not in request.headers.get("content-type", ""):
                                raise AssertionError("chat toggle did not use JSON transport")
                            if not isinstance(request.post_data_json, dict) or not isinstance(request.post_data_json.get("enabled"), bool):
                                raise AssertionError("chat toggle JSON payload is invalid")
                            return "Local HTMX replacement encoded toggle state as JSON (request intercepted)"
                        finally:
                            page.unroute("**/api/videos/*/chat-toggle")

                    checks.append(_interaction_check("Toggle transport contract", viewport_name, toggle_transport))

                    def reader_document() -> str:
                        page.goto(
                            base_url.rstrip("/") + "/read?tab=videos",
                            wait_until="domcontentloaded",
                        )
                        href = page.locator('.video-card[href^="/read/"]').first.get_attribute("href")
                        if not href:
                            raise AssertionError("no Reader document link discovered")
                        page.goto(base_url.rstrip("/") + href, wait_until="domcontentloaded")
                        summary = page.locator("#reader-summary-title")
                        transcript = page.locator("#reader-transcript-details")
                        if summary.count() == 1:
                            if not summary.is_visible():
                                raise AssertionError("Reader summary is not the default visible content")
                            transcript.locator(":scope > summary").click()
                            if not transcript.evaluate("element => element.open"):
                                raise AssertionError("Full transcript disclosure did not open")
                        if page.locator(".reader-block").count() < 1:
                            raise AssertionError("Reader rendered no transcript blocks")
                        page.wait_for_function(
                            "document.querySelector('#reader-annotation-list').innerText.trim().length > 0"
                        )
                        if page.locator("#reader-selection-tools").count() != 1:
                            raise AssertionError("Reader annotation controls missing")
                        tools_toggle = page.locator("[data-open-tools]")
                        if tools_toggle.is_visible():
                            tools_toggle.click()
                        search = page.locator("#reader-search")
                        source_text = page.locator(".reader-copy").first.inner_text().strip()
                        query = next(
                            (word.strip(".,!?;:\"'") for word in source_text.split() if len(word) >= 5),
                            "",
                        )
                        if not query:
                            raise AssertionError("Reader block has no searchable word")
                        search.fill(query)
                        if page.locator(".reader-copy mark").count() < 1:
                            raise AssertionError("Reader in-document search found no matches")
                        page.locator('[data-reader-theme="sepia"]').click()
                        page.reload(wait_until="domcontentloaded")
                        if page.locator("#reader-document").get_attribute("data-reader-theme") != "sepia":
                            raise AssertionError("Reader appearance setting did not persist")
                        return "Summary-first view, transcript disclosure, annotations, search, and persisted appearance pass"

                    checks.append(
                        _interaction_check(
                            "Reader document interaction",
                            viewport_name,
                            reader_document,
                        )
                    )

                    def current_transcript_scope() -> str:
                        page.goto(base_url.rstrip("/") + "/read?tab=videos", wait_until="domcontentloaded")
                        href = page.locator('.video-card[href^="/read/"]').first.get_attribute("href")
                        if not href:
                            raise AssertionError("no Reader document link discovered")
                        video_id = href.rstrip("/").split("/")[-1]
                        page.goto(base_url.rstrip("/") + f"/search?video_id={video_id}", wait_until="domcontentloaded")
                        selected = page.locator("#research-scope").input_value()
                        if selected != "video":
                            raise AssertionError(f"expected current-video scope, got {selected!r}")
                        page.goto(base_url.rstrip("/") + f"/chat?video_id={video_id}", wait_until="domcontentloaded")
                        if page.locator('#chat-retrieval-scope option[value="video"]').count() != 1:
                            raise AssertionError("Ask surface lost current transcript scope")
                        return "Current transcript scope is explicit in Search and Ask"

                    checks.append(_interaction_check("Current transcript research", viewport_name, current_transcript_scope))

                    def operations_job_detail() -> str:
                        page.goto(base_url.rstrip("/") + "/ops", wait_until="domcontentloaded")
                        href = page.locator('a[href^="/ops/jobs/"]').first.get_attribute("href")
                        if not href:
                            raise AssertionError("no Operations job link discovered")
                        page.goto(base_url.rstrip("/") + href, wait_until="domcontentloaded")
                        if "Job Details" not in page.locator("h1").inner_text():
                            raise AssertionError("job detail did not render")
                        return "Job detail rendered without mutation controls being invoked"

                    checks.append(_interaction_check("Operations job detail", viewport_name, operations_job_detail))

                    if viewport_name == "mobile":
                        def mobile_nav() -> str:
                            page.goto(base_url.rstrip("/") + "/", wait_until="domcontentloaded")
                            toggle = page.locator(".nav-mobile-toggle")
                            target_id = toggle.get_attribute("aria-controls")
                            if not target_id:
                                raise AssertionError("mobile navigation toggle has no aria-controls")
                            toggle.click()
                            if "is-open" not in (
                                page.locator(f"#{target_id}").get_attribute("class") or ""
                            ):
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
                        with page.expect_response(lambda response: "/api/global-search" in response.url) as info:
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
                        page.wait_for_url("**/search")
                        page.locator("select[name=source_type]").select_option("summary")
                        page.locator("#search-query").fill("AI agents")
                        with page.expect_response(lambda response: "/api/global-search" in response.url) as info:
                            page.locator("#search-query").press("Enter")
                        if info.value.status != 200:
                            raise AssertionError(f"global search returned HTTP {info.value.status}")
                        page.wait_for_function(
                            "document.querySelector('#search-results').innerText.trim().length > 0"
                        )
                        return "Legacy Global Search redirected into scoped Research and rendered results"

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
