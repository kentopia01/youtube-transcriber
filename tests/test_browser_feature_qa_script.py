from scripts.qa_browser_feature_areas import BrowserCheck, PAGE_SPECS, VIEWPORTS, _same_origin, render_markdown


def test_browser_matrix_covers_every_operator_navigation_area_at_two_viewports():
    assert {area for area, _path, _selector, _marker in PAGE_SPECS} == {
        "Dashboard",
        "Queue",
        "Library",
        "Chat",
        "Search",
        "Global Search",
    }
    assert VIEWPORTS == {
        "desktop": {"width": 1440, "height": 900},
        "mobile": {"width": 390, "height": 844},
    }


def test_same_origin_and_markdown_rendering_contracts():
    assert _same_origin("http://127.0.0.1:8000/api/search", "http://127.0.0.1:8000")
    assert not _same_origin("https://cdn.example.test/x.js", "http://127.0.0.1:8000")

    rendered = render_markdown(
        [BrowserCheck("Search", "desktop", "pass", "results | rendered")]
    )
    assert "1/1 passed" in rendered
    assert "results \\| rendered" in rendered
