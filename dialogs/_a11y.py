"""Accessibility helpers for wxPython dialogs.

Centralises the conventions for screen-reader accessible naming so we
don't repeat the same ``SetName(...)`` patterns in every dialog.

The conventions:

- Every dialog itself gets a meaningful accessible name (usually the
  title), not the default ``"dialog"``.
- Every StaticBox gets a "Foo group" name (NVDA otherwise reads
  ``"groupBox"``).
- Every RadioButton / CheckBox / Slider / Choice / TextCtrl /
  ListBox / Gauge / Button gets a meaningful name. NVDA otherwise
  reads the type name (``"radioButton"``, ``"slider"``, etc.) which
  is useless to the user.
- StaticText controls get a name that includes their visible
  content. NVDA otherwise reads ``"staticText"`` and skips the
  actual text.

We don't replace the visible ``label`` (which sighted users rely on)
-- we layer an accessible name on top that screen readers see.

JAWS happens to fall back to the visible label even when SetName is
not called, so JAWS users often don't notice these bugs. NVDA
relies on the accessible name verbatim, so NVDA users see the
problem first. The fix here makes both screen readers announce the
right thing.
"""

from __future__ import annotations

import wx


# wx's default accessible names -- control types where the default
# name is useless to a screen-reader user. Used by regression tests
# to flag widgets that are missing SetName().
DEFAULT_NAMES = {
    "dialog",
    "staticText",
    "radioButton",
    "check",
    "slider",
    "choice",
    "text",
    "listBox",
    "button",
    "gauge",
    "groupBox",
    "panel",
    "frame",
}


def name_dialog(dialog: wx.Dialog, title: str) -> None:
    """Set the dialog's accessible name to its title.

    Without this, NVDA announces 'dialog' instead of 'Breath Smoothing'.
    """
    dialog.SetName(title)


def name_group(box: wx.StaticBox, label: str) -> None:
    """Set a StaticBox's accessible name. Without this, NVDA reads
    'groupBox'. ``label`` is the visible label of the StaticBox."""
    box.SetName(f"{label} group" if not label.endswith("group") else label)


def name_widget(widget: wx.Window, name: str) -> None:
    """Generic SetName wrapper. Skips silently if the widget was
    already destroyed."""
    if widget and not widget.IsBeingDeleted():
        widget.SetName(name)


def bind_escape_to_cancel(dialog: wx.Dialog) -> None:
    """Bind Escape on ``dialog`` to call ``EndModal(wx.ID_CANCEL)``.

    Without this, a keyboard-only user has to Tab to the Cancel button
    before dismissing a modal. The bind is on ``EVT_CHAR_HOOK`` (not
    ``EVT_KEY_DOWN``) so it fires regardless of which child control
    has focus inside the dialog — that's the wx-recommended way to
    handle dialog-level shortcuts.

    Idempotent: calling twice doesn't double-bind.

    See ``dialogs/update_dialog.py:54`` for the original pattern.
    """
    # wx's default behaviour already routes Escape to the dialog's
    # default Cancel button when wx.ID_CANCEL is registered, but
    # explicit binding also works for dialogs whose only Cancel-equivalent
    # is a plain wx.Button (e.g. "Close"). Belt and braces.
    if getattr(dialog, "_escape_bound_v1_3_6", False):
        return

    def _on_char(event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            dialog.EndModal(wx.ID_CANCEL)
        else:
            event.Skip()

    dialog.Bind(wx.EVT_CHAR_HOOK, _on_char)
    dialog._escape_bound_v1_3_6 = True  # type: ignore[attr-defined]


def describe_widget(widget: wx.Window) -> tuple[str, str]:
    """Return (class_name, accessible_name) for diagnostic output."""
    cls = type(widget).__name__
    name = widget.GetName()
    return cls, name
