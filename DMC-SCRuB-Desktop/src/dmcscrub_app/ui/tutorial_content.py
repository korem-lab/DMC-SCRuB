"""Load the user-facing C-SCRuB tutorial from package resources."""

from __future__ import annotations

from importlib.resources import files

TUTORIAL_TOOLBAR_TEXT = "\u2753  Tutorial"
TUTORIAL_TAB_TEXT = "Tutorial"
TUTORIAL_STATUS_TEXT = "Tutorial \u00b7 C-SCRuB Guide"

TUTORIAL_MARKDOWN = (
    files("dmcscrub_app.resources")
    .joinpath("tutorial.md")
    .read_text(encoding="utf-8")
    .strip()
)
