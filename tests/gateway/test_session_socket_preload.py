"""The /api/ws handler is imported off the loop before READY, and a failed or hung import never holds READY."""
import asyncio
import sys
import threading
from types import SimpleNamespace

import pytest

from gateway import run_api


@pytest.fixture
def unloaded(monkeypatch):
    """``tui_gateway.ws`` absent from sys.modules; record which thread imports it."""
    import importlib
    monkeypatch.delitem(sys.modules, "tui_gateway.ws", raising=False)
    seen = {}
    real = importlib.import_module

    def spy(name, *args, **kwargs):
        if name == "tui_gateway.ws":
            seen["thread"] = threading.current_thread()
            return SimpleNamespace(handle_ws=None)
        return real(name, *args, **kwargs)
    monkeypatch.setattr(importlib, "import_module", spy)
    return seen


@pytest.mark.asyncio
async def test_preload_imports_off_the_event_loop(unloaded):
    await run_api.await_session_socket_preload(run_api.preload_session_socket())
    assert unloaded["thread"] is not threading.main_thread()


@pytest.mark.asyncio
async def test_failed_preload_never_fails_startup(caplog):
    async def boom():
        raise ImportError("broken handler")
    await run_api.await_session_socket_preload(asyncio.ensure_future(boom()))
    assert "loads on first attach" in caplog.text


@pytest.mark.asyncio
async def test_a_hung_preload_never_holds_ready(caplog):
    hang = asyncio.ensure_future(asyncio.Event().wait())
    await run_api.await_session_socket_preload(hang, timeout=0.05)
    assert "publishing READY" in caplog.text and not hang.cancelled()
    hang.cancel()


@pytest.mark.asyncio
async def test_an_attach_never_imports_the_handler_on_the_event_loop(unloaded):
    """An import still running past READY must not block the loop for the first attach."""
    await run_api.session_socket_handler()
    assert unloaded["thread"] is not threading.main_thread()
