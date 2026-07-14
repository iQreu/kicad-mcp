"""Shared FastMCP application instance and common tool annotations."""

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

# Annotation shorthands (hints for MCP clients; Claude Code batches
# readOnlyHint=True calls in parallel).
READONLY = ToolAnnotations(readOnlyHint=True)
EDIT = ToolAnnotations(readOnlyHint=False, destructiveHint=False)
EXPORT = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True)

mcp = FastMCP(
    "kicad",
    instructions=(
        "Controls KiCad 10 on this machine. Live PCB reading/editing uses the IPC API and "
        "requires a running KiCad PCB editor with the API enabled (use kicad_status / "
        "launch_kicad first). DRC/ERC, exports, renders, BOM and netlists run headless "
        "through kicad-cli on files. Coordinates are millimetres. Schematic file editing "
        "is disabled unless the server is started with KICAD_MCP_ENABLE_SCH_EDIT=1."
    ),
)
