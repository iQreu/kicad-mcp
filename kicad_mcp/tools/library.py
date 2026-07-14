"""Symbol and footprint library discovery.

Lets the model find valid lib_ids instead of guessing. A lightweight regex
index over the installed .kicad_sym / .pretty libraries is built lazily once
per server session (~2 s for the full KiCad library set) and searched in
milliseconds. Third-party libraries from the user's sym-lib-table /
fp-lib-table are included when their paths resolve.
"""

import logging
import re
from pathlib import Path

from mcp.server.fastmcp.exceptions import ToolError

from kicad_mcp import config
from kicad_mcp.app import READONLY, mcp

log = logging.getLogger(__name__)

_symbol_index: list[tuple[str, str]] | None = None  # (lib_id, description)
_footprint_index: list[str] | None = None

_SYM_SPLIT_RE = re.compile(r'\n\t\(symbol "([^"]+)"')
_DESC_RE = re.compile(r'\(property "(?:ki_description|Description)"\s+"((?:[^"\\]|\\.)*)"')
_TABLE_ENTRY_RE = re.compile(r'\(name "((?:[^"\\]|\\.)*)"\)\s*\(type "[^"]*"\)\s*\(uri "((?:[^"\\]|\\.)*)"\)')


def _expand_uri(uri: str) -> Path:
    subs = {
        "${KICAD10_SYMBOL_DIR}": str(config.KICAD_ROOT / "share/kicad/symbols"),
        "${KICAD10_FOOTPRINT_DIR}": str(config.KICAD_ROOT / "share/kicad/footprints"),
        "${KICAD10_3DMODEL_DIR}": str(config.KICAD_ROOT / "share/kicad/3dmodels"),
    }
    for var, val in subs.items():
        uri = uri.replace(var, val)
    return Path(uri)


def _table_entries(table_file: Path) -> list[tuple[str, Path]]:
    if not table_file.exists():
        return []
    text = table_file.read_text(encoding="utf-8", errors="replace")
    return [(name, _expand_uri(uri)) for name, uri in _TABLE_ENTRY_RE.findall(text)]


def _symbol_libraries() -> list[tuple[str, Path]]:
    libs = {
        p.stem: p
        for p in (config.KICAD_ROOT / "share/kicad/symbols").glob("*.kicad_sym")
    }
    for name, path in _table_entries(config.KICAD_SETTINGS_DIR / "sym-lib-table"):
        if path.suffix == ".kicad_sym" and path.exists():
            libs[name] = path
    return sorted(libs.items())


def _footprint_libraries() -> list[tuple[str, Path]]:
    libs = {
        p.stem: p
        for p in (config.KICAD_ROOT / "share/kicad/footprints").glob("*.pretty")
    }
    for name, path in _table_entries(config.KICAD_SETTINGS_DIR / "fp-lib-table"):
        if path.suffix == ".pretty" and path.is_dir():
            libs[name] = path
    return sorted(libs.items())


def _build_symbol_index() -> list[tuple[str, str]]:
    global _symbol_index
    if _symbol_index is not None:
        return _symbol_index
    index: list[tuple[str, str]] = []
    for libname, libpath in _symbol_libraries():
        try:
            text = libpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Split into per-symbol chunks so descriptions map to the right name.
        parts = _SYM_SPLIT_RE.split(text)
        # parts = [prefix, name1, body1, name2, body2, ...]
        for name, body in zip(parts[1::2], parts[2::2]):
            m = _DESC_RE.search(body)
            index.append((f"{libname}:{name}", m.group(1) if m else ""))
    _symbol_index = index
    log.info("symbol index built: %d symbols", len(index))
    return index


def _build_footprint_index() -> list[str]:
    global _footprint_index
    if _footprint_index is not None:
        return _footprint_index
    index = [
        f"{libname}:{mod.stem}"
        for libname, libpath in _footprint_libraries()
        for mod in libpath.glob("*.kicad_mod")
    ]
    _footprint_index = index
    log.info("footprint index built: %d footprints", len(index))
    return index


@mcp.tool(annotations=READONLY)
def search_symbols(query: str, limit: int = 20) -> dict:
    """Search installed schematic symbol libraries by name/description
    (e.g. 'esp32', 'op amp single', 'usb-c connector'). Returns valid lib_ids
    for sch_add_component / sch_apply_edits. All query words must match."""
    words = [w.lower() for w in query.split() if w]
    if not words:
        raise ToolError("Empty query.")
    hits = []
    for lib_id, desc in _build_symbol_index():
        hay = f"{lib_id} {desc}".lower()
        if all(w in hay for w in words):
            hits.append({"lib_id": lib_id, "description": desc})
            if len(hits) >= limit:
                break
    return {"query": query, "returned": len(hits), "symbols": hits}


@mcp.tool(annotations=READONLY)
def search_footprints(query: str, limit: int = 20) -> dict:
    """Search installed footprint libraries by name (e.g. '0603', 'SOIC-8',
    'ESP32 WROOM'). Returns valid library_ids for place_footprint(s) and the
    footprint field of schematic components. All query words must match."""
    words = [w.lower() for w in query.split() if w]
    if not words:
        raise ToolError("Empty query.")
    hits = []
    for fp_id in _build_footprint_index():
        hay = fp_id.lower()
        if all(w in hay for w in words):
            hits.append(fp_id)
            if len(hits) >= limit:
                break
    return {"query": query, "returned": len(hits), "footprints": hits}


@mcp.tool(annotations=READONLY)
def get_symbol_details(lib_id: str) -> dict:
    """Full details of one library symbol: description, datasheet, reference
    prefix and the PIN LIST (number, name, type). Check pins here before
    wiring connections with sch_apply_edits / sch_connect_pins."""
    import kicad_sch_api as ksa

    info = ksa.get_symbol_info(lib_id)
    if info is None:
        raise ToolError(
            f"Symbol '{lib_id}' not found. Use search_symbols to find valid lib_ids."
        )
    pins = []
    try:
        for pin in info.pins:
            pins.append(
                {
                    "number": getattr(pin, "number", None),
                    "name": getattr(pin, "name", None),
                    "type": str(getattr(pin, "pin_type", getattr(pin, "type", ""))),
                }
            )
    except Exception:
        pass
    return {
        "lib_id": lib_id,
        "description": info.description,
        "keywords": info.keywords,
        "datasheet": info.datasheet,
        "reference_prefix": info.reference_prefix,
        "power_symbol": bool(info.power_symbol),
        "pin_count": len(pins),
        "pins": pins,
    }
