"""
Preset Manager for SpeechCraft Studio.

Loads and saves custom user presets from a JSON file in the user's
app data directory. Provides a unified API for managing EQ, compressor,
and breath smoothing presets — both built-in (read-only) and custom (user).
"""
import json
import os
import wx

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
def _get_presets_path():
    """Return the path to the custom presets JSON file."""
    try:
        app_data = wx.StandardPaths.Get().GetUserDataDir()
    except Exception:
        # Fallback for non-GUI contexts
        app_data = os.path.expanduser("~/AppData/Roaming/SpeechCraftStudio")
    parent = os.path.dirname(app_data)
    os.makedirs(parent, exist_ok=True)
    return os.path.join(parent, "speechcraft_presets.json")


# ---------------------------------------------------------------------------
# Load / Save
# ---------------------------------------------------------------------------
def load_custom_presets():
    """Load custom presets from the JSON file. Returns (eq_custom, comp_custom, breath_custom)."""
    path = _get_presets_path()
    if not os.path.exists(path):
        return {}, {}, {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return (
            data.get("eq_custom", {}),
            data.get("compressor_custom", {}),
            data.get("breath_custom", {}),
        )
    except (json.JSONDecodeError, OSError) as e:
        wx.MessageBox(
            f"Could not load custom presets:\n{e}\n\nUsing defaults.",
            "Preset Load Error",
            wx.ICON_WARNING,
        )
        return {}, {}, {}


def save_custom_presets(eq_custom, comp_custom, breath_custom):
    """Save all custom presets to the JSON file."""
    path = _get_presets_path()

    # Load any existing data so we don't wipe unrelated keys
    existing = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass

    existing["eq_custom"] = eq_custom
    existing["compressor_custom"] = comp_custom
    existing["breath_custom"] = breath_custom

    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
    except OSError as e:
        wx.MessageBox(
            f"Could not save custom presets:\n{e}",
            "Preset Save Error",
            wx.ICON_ERROR,
        )
        return False
    return True


# ---------------------------------------------------------------------------
# EQ helpers
# ---------------------------------------------------------------------------
def add_custom_eq_preset(name, bands, description=""):
    """Save a custom EQ preset. Overwrites if name already exists."""
    eq, comp, breath = load_custom_presets()
    eq[name] = {"bands": bands, "description": description}
    return save_custom_presets(eq, comp, breath)


def delete_custom_eq_preset(name):
    eq, comp, breath = load_custom_presets()
    eq.pop(name, None)
    return save_custom_presets(eq, comp, breath)


def rename_custom_eq_preset(old_name, new_name):
    eq, comp, breath = load_custom_presets()
    if old_name in eq:
        eq[new_name] = eq.pop(old_name)
        return save_custom_presets(eq, comp, breath)
    return False


# ---------------------------------------------------------------------------
# Compressor helpers
# ---------------------------------------------------------------------------
def add_custom_compressor_preset(name, params, description=""):
    """Save a custom compressor preset. params: threshold_db, ratio, attack_ms, release_ms, makeup_db."""
    eq, comp, breath = load_custom_presets()
    comp[name] = {"description": description, **params}
    return save_custom_presets(eq, comp, breath)


def delete_custom_compressor_preset(name):
    eq, comp, breath = load_custom_presets()
    comp.pop(name, None)
    return save_custom_presets(eq, comp, breath)


def rename_custom_compressor_preset(old_name, new_name):
    eq, comp, breath = load_custom_presets()
    if old_name in comp:
        comp[new_name] = comp.pop(old_name)
        return save_custom_presets(eq, comp, breath)
    return False


# ---------------------------------------------------------------------------
# Breath smoothing helpers
# ---------------------------------------------------------------------------
def add_custom_breath_preset(name, params, description=""):
    """Save a custom breath smoothing preset. params: reduction_db, cutoff_hz, fade_ms, rms_thresh, dry_wet."""
    eq, comp, breath = load_custom_presets()
    breath[name] = {"description": description, **params}
    return save_custom_presets(eq, comp, breath)


def delete_custom_breath_preset(name):
    eq, comp, breath = load_custom_presets()
    breath.pop(name, None)
    return save_custom_presets(eq, comp, breath)


# ---------------------------------------------------------------------------
# Import / Export (file-based sharing)
# ---------------------------------------------------------------------------
def export_presets_to_file(filepath, eq_presets=None, comp_presets=None, breath_presets=None):
    """Export selected preset categories to a JSON file for sharing."""
    data = {}
    if eq_presets:
        data["eq_presets"] = eq_presets
    if comp_presets:
        data["compressor_presets"] = comp_presets
    if breath_presets:
        data["breath_presets"] = breath_presets
    data["_export_version"] = "1.0"
    data["_app"] = "SpeechCraft Studio"

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except OSError as e:
        wx.MessageBox(f"Could not export presets:\n{e}", "Export Error", wx.ICON_ERROR)
        return False


def import_presets_from_file(filepath):
    """Import presets from a JSON file. Returns (eq, comp, breath) dicts merged, or None on error."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        eq = data.get("eq_presets", {})
        comp = data.get("compressor_presets", {})
        breath = data.get("breath_presets", {})

        # Merge into existing custom presets
        eq_custom, comp_custom, breath_custom = load_custom_presets()
        eq_custom.update(eq)
        comp_custom.update(comp)
        breath_custom.update(breath)
        save_custom_presets(eq_custom, comp_custom, breath_custom)
        return eq, comp, breath
    except (json.JSONDecodeError, OSError) as e:
        wx.MessageBox(
            f"Could not import presets:\n{e}",
            "Import Error",
            wx.ICON_ERROR,
        )
        return None
