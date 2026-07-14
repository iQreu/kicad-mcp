"""Connection management for the KiCad IPC API (kipy).

KiCad 10 serves the IPC API only from a running GUI editor (pcbnew / the
project manager) and only when Preferences > Plugins > "Enable KiCad API"
is checked (api.enable_server in kicad_common.json).
"""

import json
import logging
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from kipy import KiCad
from kipy.board import Board
from mcp.server.fastmcp.exceptions import ToolError

from kicad_mcp import config

log = logging.getLogger(__name__)

_kicad: KiCad | None = None


def _api_enabled_in_settings() -> bool | None:
    """Read api.enable_server from kicad_common.json; None if unreadable."""
    try:
        data = json.loads(config.KICAD_COMMON_JSON.read_text(encoding="utf-8-sig"))
        return bool(data.get("api", {}).get("enable_server", False))
    except (OSError, ValueError):
        return None


def _kicad_processes() -> list[str]:
    """Names of running KiCad GUI processes (kicad/pcbnew/eeschema)."""
    found = []
    try:
        out = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout.lower()
        for name in ("kicad.exe", "pcbnew.exe", "eeschema.exe"):
            if f'"{name}"' in out:
                found.append(name)
    except (OSError, subprocess.SubprocessError):
        pass
    return found


def diagnose_connection_failure() -> str:
    """Human/model-actionable explanation of why the IPC connection failed."""
    procs = _kicad_processes()
    enabled = _api_enabled_in_settings()
    if not procs:
        return (
            "No KiCad process is running. Start KiCad with a board open "
            "(the launch_kicad tool can do this), then retry."
        )
    if enabled is False:
        return (
            f"KiCad is running ({', '.join(procs)}) but the API server is disabled. "
            "Enable it in KiCad: Preferences > Plugins > 'Enable KiCad API', then "
            "restart KiCad and retry."
        )
    return (
        f"KiCad is running ({', '.join(procs)}) and the API looks enabled, but the "
        "connection failed. Likely causes: KiCad was started before the API setting "
        "was enabled (restart it), a modal dialog is blocking the UI thread (close "
        "it), or multiple KiCad instances are running (the socket name then includes "
        "a PID; set KICAD_API_SOCKET)."
    )


def _candidate_sockets() -> list[str]:
    """Socket URLs of running KiCad instances (newest first). KiCad puts them
    in <temp>/kicad/api.sock, with a PID suffix for extra instances."""
    sock_dir = Path(tempfile.gettempdir()) / "kicad"
    if not sock_dir.is_dir():
        return []
    socks = sorted(
        sock_dir.glob("api.sock*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return [f"ipc://{s}" for s in socks]


def connect(timeout_ms: int = 3000) -> KiCad:
    """Return a live KiCad connection, reusing the cached one when healthy.

    Tries the default socket (or KICAD_API_SOCKET) first, then any other
    api.sock* files left by concurrently running KiCad instances.
    """
    global _kicad
    if _kicad is not None:
        try:
            _kicad.ping()
            return _kicad
        except Exception:
            log.info("cached KiCad connection stale, reconnecting")
            _kicad = None
    last_exc: Exception | None = None
    attempts: list[str | None] = [None, *_candidate_sockets()]
    for socket_path in attempts:
        try:
            k = KiCad(socket_path=socket_path, timeout_ms=timeout_ms)
            k.ping()
        except Exception as exc:
            last_exc = exc
            continue
        if socket_path:
            log.info("connected via fallback socket %s", socket_path)
        _kicad = k
        return k
    raise ToolError(
        f"Cannot connect to the KiCad IPC API "
        f"({type(last_exc).__name__ if last_exc else 'no socket'}: {last_exc}). "
        + diagnose_connection_failure()
    ) from last_exc


def try_connect(timeout_ms: int = 1500) -> KiCad | None:
    """Like connect() but returns None instead of raising."""
    try:
        return connect(timeout_ms=timeout_ms)
    except ToolError:
        return None


def connect_to_board(filename: str, timeout_s: float) -> KiCad | None:
    """Poll all reachable KiCad instances until one has the given board file
    open, then make it the cached connection. Guards against grabbing a
    different instance's board when several KiCads are running."""
    global _kicad
    want = Path(filename).name.lower()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for socket_path in [None, *_candidate_sockets()]:
            try:
                k = KiCad(socket_path=socket_path, timeout_ms=1500)
                if Path(k.get_board().name).name.lower() == want:
                    _kicad = k
                    return k
            except Exception:
                continue
        time.sleep(1.5)
    return None


def get_board() -> Board:
    """The board open in the connected PCB editor."""
    kicad = connect()
    try:
        return kicad.get_board()
    except Exception as exc:
        raise ToolError(
            "Connected to KiCad, but no board is open in a PCB editor "
            f"({type(exc).__name__}: {exc}). Open a .kicad_pcb file (launch_kicad "
            "can do this) and retry."
        ) from exc


def open_board_path() -> Path | None:
    """Absolute path of the board open in the editor, if resolvable."""
    board = get_board()
    doc = board._doc
    name = doc.board_filename
    if not name:
        return None
    p = Path(name)
    if p.is_absolute():
        return p if p.exists() else None
    proj = doc.project.path
    if proj:
        base = Path(proj)
        if base.is_file():
            base = base.parent
        candidate = base / name
        if candidate.exists():
            return candidate
    return None


@contextmanager
def board_commit(board: Board, message: str):
    """Group board mutations into a single undo step; drop on failure."""
    commit = board.begin_commit()
    try:
        yield
    except Exception:
        try:
            board.drop_commit(commit)
        except Exception:
            log.exception("drop_commit failed")
        raise
    else:
        board.push_commit(commit, message)


def find_net(board: Board, net_name: str):
    for net in board.get_nets():
        if net.name == net_name:
            return net
    names = sorted(n.name for n in board.get_nets() if n.name)[:40]
    raise ToolError(
        f"Net '{net_name}' not found on the board. Known nets include: {names}"
    )
