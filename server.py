"""KiCad MCP server entry point (stdio).

Run: .venv\\Scripts\\python.exe server.py
Never print to stdout here — stdio carries the MCP protocol; logs go to stderr.
"""

import logging
import sys

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
)

from kicad_mcp.app import mcp  # noqa: E402

# Importing the tool modules registers their @mcp.tool() functions.
from kicad_mcp.tools import (  # noqa: E402, F401
    board_edit,
    board_read,
    drc_rules,
    export,
    library,
    preview,
    project,
    prompts,
    schematic_edit,
    schematic_read,
    status,
)

if __name__ == "__main__":
    mcp.run()
