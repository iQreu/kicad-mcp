"""Thin wrapper around kicad-cli (headless exports, DRC/ERC, renders)."""

import logging
import subprocess

from mcp.server.fastmcp.exceptions import ToolError

from kicad_mcp import config

log = logging.getLogger(__name__)


def run_cli(args: list[str], timeout: float = 300.0) -> str:
    """Run kicad-cli with args; return stdout, raise ToolError on failure."""
    if not config.KICAD_CLI.exists():
        raise ToolError(
            f"kicad-cli not found at {config.KICAD_CLI}. Set the KICAD_CLI or "
            "KICAD_ROOT environment variable for this MCP server."
        )
    cmd = [str(config.KICAD_CLI), *args]
    log.info("running: %s", subprocess.list2cmdline(cmd))
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"kicad-cli timed out after {timeout}s: {args}") from exc
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise ToolError(
            f"kicad-cli failed (exit {proc.returncode}) for {args}: {err[-2000:]}"
        )
    return proc.stdout
