"""A dedicated thread + event loop for Playwright work.

Playwright starts the browser driver as a subprocess, which on Windows needs a
ProactorEventLoop. uvicorn (with reload/workers) and some test clients run the
app on a SelectorEventLoop, where subprocess creation raises
NotImplementedError. Running every browser coroutine on this thread's own
Proactor loop makes that independent of how the server was started. It also
keeps tools.browser's per-platform asyncio locks on a single loop.
"""

from __future__ import annotations

import asyncio
import sys
import threading
from typing import Any, Awaitable, Callable

_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_lock = threading.Lock()


def _new_loop() -> asyncio.AbstractEventLoop:
    if sys.platform == "win32":
        return asyncio.ProactorEventLoop()
    return asyncio.new_event_loop()


def get_loop() -> asyncio.AbstractEventLoop:
    global _loop, _thread
    with _lock:
        if _loop is None or _loop.is_closed() or _thread is None or not _thread.is_alive():
            loop = _new_loop()
            ready = threading.Event()

            def runner() -> None:
                asyncio.set_event_loop(loop)
                ready.set()
                loop.run_forever()

            t = threading.Thread(target=runner, name="job-mcp-browser", daemon=True)
            t.start()
            ready.wait(5)
            _loop, _thread = loop, t
        return _loop


async def run(factory: Callable[[], Awaitable[Any]]) -> Any:
    """Run ``factory()`` on the browser loop and await its result from the caller's loop.

    Cancelling the awaiting task cancels the coroutine on the browser loop too.
    """
    fut = asyncio.run_coroutine_threadsafe(_call(factory), get_loop())
    try:
        return await asyncio.wrap_future(fut)
    except asyncio.CancelledError:
        fut.cancel()
        raise


async def _call(factory: Callable[[], Awaitable[Any]]) -> Any:
    return await factory()


def loop_kind() -> str:
    return type(get_loop()).__name__


async def launch_check(timeout: float = 60.0) -> dict:
    """Launch headless Chromium to about:blank on the browser loop (diagnostics)."""
    async def check() -> dict:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.goto("about:blank")
                return {"ok": True, "browser_version": browser.version, "url": page.url,
                        "loop": type(asyncio.get_running_loop()).__name__}
            finally:
                await browser.close()

    try:
        return await asyncio.wait_for(run(check), timeout=timeout)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:500], "loop": loop_kind()}
