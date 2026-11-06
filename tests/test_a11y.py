"""Accessibility: axe finds no violations on the explorer or the help page, in either survey."""
import pytest
from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import Page

PAGES = [("/", "#loading"), ("/#src=cps", "#loading"), ("/help.html", None)]


@pytest.mark.parametrize("path,loading", PAGES)
def test_no_accessibility_violations(page: Page, static_server: str, path: str, loading):
    page.goto(static_server + path)
    if loading:
        page.wait_for_selector(loading, state="hidden", timeout=90_000)
    results = Axe().run(page)
    found = [f"{v['id']}: {len(v['nodes'])} × {v['nodes'][0]['target']}" for v in results.response["violations"]]
    assert found == []
