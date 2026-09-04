"""Shared pytest fixtures for SpeechCraft tests.

The big challenge with testing wxPython code: a ``wx.App`` instance
must exist before any ``wx.Dialog`` or ``wx.Frame`` can be
constructed, and there must be exactly one per process. Creating
a new App per test is brittle on Windows (the underlying C++
objects fight over a singleton) and slow.

The fixture below gives every test a session-scoped ``wx_app``
fixture that lazily creates exactly one ``wx.App`` for the whole
test session. The app is destroyed when the session ends.

If wx is not installed (Linux smoke CI, contributor without
wxPython yet), the fixture is ``None`` and wx-gated tests should
``pytest.skip`` rather than crash.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture(scope="session")
def wx_app() -> Any:
    """Lazily create a single ``wx.App`` for the whole test session.

    Returns ``None`` if wxPython is not installed. Tests that need
    a real wx instance must gate on this fixture's identity:
    ``if wx_app is None: pytest.skip(...)``.

    The app is destroyed at session teardown so CI runners do not
    leak a window into the next job.
    """
    try:
        import wx
    except ImportError:
        return None

    # wx.GetApp() returns the existing app if one is already alive
    # (a previous test fixture, a previous session), so we reuse it.
    app = wx.GetApp()
    if app is None:
        app = wx.App(redirect=False, clearSigInt=False)
    yield app

    # Do NOT call app.Destroy() -- doing so in the middle of a session
    # causes subsequent wx.Dialog() constructions to raise "No app
    # object has been created". The OS reclaims the C++ object when
    # the process exits, which is fine for CI.
