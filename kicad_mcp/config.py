"""Paths and environment configuration for the KiCad MCP server."""

import os
from pathlib import Path

KICAD_ROOT = Path(os.environ.get("KICAD_ROOT", r"C:\Program Files\KiCad\10.0"))
KICAD_BIN = KICAD_ROOT / "bin"
KICAD_CLI = Path(os.environ.get("KICAD_CLI", str(KICAD_BIN / "kicad-cli.exe")))
KICAD_EXE = KICAD_BIN / "kicad.exe"
PCBNEW_EXE = KICAD_BIN / "pcbnew.exe"
EESCHEMA_EXE = KICAD_BIN / "eeschema.exe"

KICAD_SETTINGS_DIR = Path(os.environ.get("APPDATA", "")) / "kicad" / "10.0"
KICAD_COMMON_JSON = KICAD_SETTINGS_DIR / "kicad_common.json"

# Schematic file editing is opt-in: it rewrites .kicad_sch files directly
# (no official KiCad API for this in v10) and carries corruption risk.
SCH_EDIT_ENABLED = os.environ.get("KICAD_MCP_ENABLE_SCH_EDIT", "").strip().lower() in (
    "1",
    "true",
    "yes",
)

# How long to wait for the IPC socket after launching a KiCad editor.
LAUNCH_WAIT_SECONDS = float(os.environ.get("KICAD_MCP_LAUNCH_WAIT", "45"))
