"""Custom DRC rules (.kicad_dru).

kicad-cli pcb drc auto-loads <project>.kicad_dru, but with two silent
failure modes verified on KiCad 10.0.4: a UTF-8 BOM makes KiCad ignore the
whole file, and a syntax error is swallowed without any warning (no headless
syntax check exists). These tools write BOM-less, check paren balance, and
can prove the file is actually loaded by injecting a canary rule that must
produce violations in a DRC run.
"""

import shutil
import time
from pathlib import Path

from mcp.server.fastmcp.exceptions import ToolError

from kicad_mcp.app import EDIT, READONLY, mcp

_CANARY = '\n(rule "mcp_canary" (constraint clearance (min 1000mm)))\n'


def _dru_path(project_path: str) -> Path:
    p = Path(project_path)
    if p.suffix == ".kicad_pro":
        return p.with_suffix(".kicad_dru")
    if p.suffix == ".kicad_dru":
        return p
    raise ToolError(f"Expected a .kicad_pro or .kicad_dru path, got: {p}")


@mcp.tool(annotations=READONLY)
def get_custom_drc_rules(project_path: str) -> dict:
    """Read the project's custom DRC rules file (.kicad_dru), if any."""
    dru = _dru_path(project_path)
    if not dru.exists():
        return {"file": str(dru), "exists": False, "rules": None}
    return {
        "file": str(dru),
        "exists": True,
        "rules": dru.read_text(encoding="utf-8-sig"),
    }


@mcp.tool(annotations=EDIT)
def set_custom_drc_rules(
    project_path: str,
    rules: str,
    verify_with_board: str | None = None,
) -> dict:
    """Write the project's custom DRC rules (.kicad_dru). `rules` is the full
    file content in KiCad rule syntax, e.g.:

    (version 1)
    (rule "HV clearance" (condition "A.NetClass == 'HV'")
          (constraint clearance (min 1.5mm)))

    KiCad silently ignores files with syntax errors, so pass the project's
    board file as verify_with_board to PROVE the rules load: a temporary
    canary rule is appended and must produce violations in a DRC run."""
    dru = _dru_path(project_path)
    text = rules.strip() + "\n"
    if not text.startswith("(version"):
        raise ToolError('Rules must start with "(version 1)".')
    if text.count("(") != text.count(")"):
        raise ToolError(
            f"Unbalanced parentheses ({text.count('(')} open vs {text.count(')')} "
            "close). KiCad would silently ignore the whole file."
        )
    backup = None
    if dru.exists():
        backup = dru.with_name(f"{dru.name}.mcp-backup-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(dru, backup)
    # BOM-less UTF-8 is essential: a BOM makes KiCad skip the file silently.
    dru.write_bytes(text.encode("utf-8"))

    result = {"file": str(dru), "backup_file": str(backup) if backup else None}
    if verify_with_board:
        from kicad_mcp.tools.export import run_drc

        board = Path(verify_with_board)
        if not board.exists():
            raise ToolError(f"verify_with_board not found: {board}")
        dru.write_bytes((text + _CANARY).encode("utf-8"))
        try:
            report = run_drc(str(board), save_first=False)
            canary_hits = [
                v
                for v in report["violations"]
                if "mcp_canary" in (v.get("description") or "")
            ]
            result["verified_loaded"] = bool(canary_hits)
            if not canary_hits:
                result["warning"] = (
                    "The canary rule produced no violations - KiCad most likely "
                    "ignored the .kicad_dru file (syntax error?). Fix the rules."
                )
        finally:
            dru.write_bytes(text.encode("utf-8"))
    else:
        result["note"] = (
            "Not verified against a board. KiCad ignores broken rule files "
            "silently - pass verify_with_board to prove the rules load."
        )
    return result
