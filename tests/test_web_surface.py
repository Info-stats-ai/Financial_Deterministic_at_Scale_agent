from urllib.parse import quote

from interface_ai.surface.protocol import SurfaceAction, SurfaceActionKind
from interface_ai.surface.web_playwright import PlaywrightWebSurface


async def test_observe_act_and_fingerprint() -> None:
    html = """
    <html><head><title>Surface Test</title></head>
    <body>
      <label for="member">Member ID</label>
      <input id="member" aria-label="Member ID">
      <button onclick="document.querySelector('h1').textContent='Done'">Search</button>
      <h1>Ready</h1>
    </body></html>
    """
    surface = PlaywrightWebSurface(headless=True, viewport=(800, 600))
    await surface.start(start_url=f"data:text/html,{quote(html)}")
    try:
        before = await surface.observe()
        member_node = next(
            node
            for node in before.semantic_tree
            if node["name"] == "Member ID" and node["tag"] == "input"
        )
        box = member_node["box"]
        typed = await surface.act(
            SurfaceAction(
                kind=SurfaceActionKind.TYPE,
                x=box["x"] + box["width"] / 2,
                y=box["y"] + box["height"] / 2,
                text="MEM-1001",
            )
        )
        assert typed.success
        assert typed.target_fingerprint
        assert typed.target_fingerprint.label == "Member ID"

        button_node = next(node for node in before.semantic_tree if node["name"] == "Search")
        button_box = button_node["box"]
        clicked = await surface.act(
            SurfaceAction(
                kind=SurfaceActionKind.CLICK,
                x=button_box["x"] + button_box["width"] / 2,
                y=button_box["y"] + button_box["height"] / 2,
            )
        )
        after = await surface.observe()

        assert clicked.success
        assert any(node["text"] == "Done" for node in after.semantic_tree)
        assert after.state_fingerprint != before.state_fingerprint
    finally:
        await surface.close()


async def test_browser_process_is_reused_across_contexts() -> None:
    surface = PlaywrightWebSurface(headless=True, viewport=(800, 600))
    await surface.start(start_url="data:text/html,<p>one</p>")
    first_browser = surface.browser
    await surface.close(shutdown_browser=False)
    assert surface.page is None
    assert surface.browser is first_browser
    await surface.start(start_url="data:text/html,<p>two</p>")
    try:
        assert surface.browser is first_browser
        assert "two" in await surface._require_page().inner_text("p")
    finally:
        await surface.close()
