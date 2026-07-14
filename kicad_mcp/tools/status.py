"""Connection status and KiCad lifecycle tools."""

import subprocess
from pathlib import Path

from mcp.server.fastmcp.exceptions import ToolError

from kicad_mcp import config
from kicad_mcp.app import mcp
from kicad_mcp.backends import cli, ipc

_cli_version: str | None = None


@mcp.tool()
def kicad_status() -> dict:
    """Report KiCad availability: running processes, API server state, IPC
    connection, versions and the currently open board. Call this first when
    live-board tools fail."""
    result: dict = {
        "kicad_root": str(config.KICAD_ROOT),
        "kicad_processes": ipc._kicad_processes(),
        "api_enabled_in_settings": ipc._api_enabled_in_settings(),
        "ipc_connected": False,
    }
    global _cli_version
    if _cli_version is None:
        try:
            _cli_version = cli.run_cli(["version"]).strip()
        except ToolError as exc:
            _cli_version = f"error: {exc}"
    result["kicad_cli_version"] = _cli_version

    kicad = ipc.try_connect()
    if kicad is not None:
        result["ipc_connected"] = True
        result["kicad_version"] = str(kicad.get_version())
        result["api_version"] = str(kicad.get_api_version())
        try:
            board = kicad.get_board()
            result["open_board"] = board.name
            path = ipc.open_board_path()
            result["open_board_path"] = str(path) if path else None
        except Exception:
            result["open_board"] = None
    else:
        result["diagnosis"] = ipc.diagnose_connection_failure()
    return result


@mcp.tool()
def launch_kicad(file_path: str | None = None, wait_for_api: bool = True) -> dict:
    """Launch a KiCad editor. With a .kicad_pcb path opens the PCB editor,
    with .kicad_sch the schematic editor, with .kicad_pro (or nothing) the
    project manager. Waits until the IPC API accepts connections when
    wait_for_api is true (PCB editor only in KiCad 10)."""
    if ipc._api_enabled_in_settings() is False:
        raise ToolError(
            "The KiCad API server is disabled in kicad_common.json. Enable it in "
            "KiCad: Preferences > Plugins > 'Enable KiCad API' before launching."
        )
    exe = config.KICAD_EXE
    args: list[str] = []
    if file_path:
        p = Path(file_path)
        if not p.exists():
            raise ToolError(f"File not found: {p}")
        suffix = p.suffix.lower()
        if suffix == ".kicad_pcb":
            exe = config.PCBNEW_EXE
        elif suffix == ".kicad_sch":
            exe = config.EESCHEMA_EXE
        elif suffix != ".kicad_pro":
            raise ToolError(
                f"Unsupported file type '{suffix}'. Use .kicad_pcb, .kicad_sch or .kicad_pro."
            )
        args = [str(p)]
    subprocess.Popen([str(exe), *args])

    result = {"launched": exe.name, "file": file_path, "ipc_connected": False}
    board_file = args[0] if exe is config.PCBNEW_EXE else None
    if wait_for_api and board_file:
        # Wait specifically for the instance that has THIS board open, so a
        # concurrently running KiCad cannot be mistaken for the launched one.
        kicad = ipc.connect_to_board(board_file, config.LAUNCH_WAIT_SECONDS)
        if kicad is not None:
            result["ipc_connected"] = True
            result["connected_board"] = kicad.get_board().name
        else:
            result["note"] = (
                "KiCad was launched but no IPC instance with this board showed "
                f"up within {config.LAUNCH_WAIT_SECONDS}s. Check Preferences > "
                "Plugins > 'Enable KiCad API'."
            )
    elif wait_for_api:
        result["note"] = (
            "In KiCad 10 only the PCB editor serves the IPC API, so there is "
            "nothing to wait for when opening a schematic or project."
        )
    return result
