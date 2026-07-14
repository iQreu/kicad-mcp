"""Read-only tools for the board open in the live PCB editor (IPC API)."""

from kipy.proto.board.board_commands_pb2 import BoardOriginType
from mcp.server.fastmcp.exceptions import ToolError

from kicad_mcp.app import READONLY, mcp
from kicad_mcp.backends import ipc
from kicad_mcp.util import angle_deg, enum_to_layer, kiid_str, mm, pos_to_mm


@mcp.tool(annotations=READONLY)
def board_info() -> dict:
    """Overview of the board open in the PCB editor: file, layer setup,
    item counts and title block."""
    board = ipc.get_board()
    nets = board.get_nets()
    footprints = board.get_footprints()
    tracks = board.get_tracks()
    vias = board.get_vias()
    zones = board.get_zones()
    tb = board.get_title_block_info()
    path = ipc.open_board_path()
    return {
        "file": board.name,
        "path": str(path) if path else None,
        "copper_layer_count": board.get_copper_layer_count(),
        "enabled_layers": [enum_to_layer(l) for l in board.get_enabled_layers()],
        "counts": {
            "footprints": len(footprints),
            "tracks": len(tracks),
            "vias": len(vias),
            "zones": len(zones),
            "nets": len(nets),
        },
        "grid_origin_mm": pos_to_mm(board.get_origin(BoardOriginType.BOT_GRID)),
        "drill_origin_mm": pos_to_mm(board.get_origin(BoardOriginType.BOT_DRILL)),
        "title_block": {
            "title": tb.title,
            "date": tb.date,
            "revision": tb.revision,
            "company": tb.company,
        },
    }


@mcp.tool(annotations=READONLY)
def list_footprints(limit: int = 200) -> dict:
    """List footprints on the live board with reference, value, library id,
    position (mm), rotation and layer."""
    board = ipc.get_board()
    footprints = board.get_footprints()
    items = []
    for fp in footprints[:limit]:
        lib = fp.definition.id if fp.definition else None
        items.append(
            {
                "id": kiid_str(fp),
                "reference": fp.reference_field.text.value,
                "value": fp.value_field.text.value,
                "library_id": str(lib) if lib else None,
                "position_mm": pos_to_mm(fp.position),
                "rotation_deg": angle_deg(fp.orientation),
                "layer": enum_to_layer(fp.layer),
                "locked": fp.locked,
            }
        )
    return {"total": len(footprints), "returned": len(items), "footprints": items}


@mcp.tool(annotations=READONLY)
def list_nets(name_filter: str | None = None) -> dict:
    """List nets on the live board, optionally filtered by substring."""
    board = ipc.get_board()
    nets = board.get_nets()
    names = [n.name for n in nets]
    if name_filter:
        needle = name_filter.lower()
        names = [n for n in names if needle in n.lower()]
    return {"total": len(nets), "returned": len(names), "nets": sorted(names)}


@mcp.tool(annotations=READONLY)
def list_tracks(net_name: str | None = None, limit: int = 300) -> dict:
    """List track segments (and arcs) on the live board: endpoints (mm),
    width, layer and net. Optionally filter by net name."""
    board = ipc.get_board()
    tracks = board.get_tracks()
    items = []
    for t in tracks:
        net = t.net.name if t.net else None
        if net_name and net != net_name:
            continue
        items.append(
            {
                "id": kiid_str(t),
                "start_mm": pos_to_mm(t.start),
                "end_mm": pos_to_mm(t.end),
                "width_mm": mm(t.width),
                "layer": enum_to_layer(t.layer),
                "net": net,
            }
        )
        if len(items) >= limit:
            break
    return {"total": len(tracks), "returned": len(items), "tracks": items}


@mcp.tool(annotations=READONLY)
def list_vias(net_name: str | None = None, limit: int = 300) -> dict:
    """List vias on the live board: position (mm), drill, diameter and net."""
    board = ipc.get_board()
    vias = board.get_vias()
    items = []
    for v in vias:
        net = v.net.name if v.net else None
        if net_name and net != net_name:
            continue
        items.append(
            {
                "id": kiid_str(v),
                "position_mm": pos_to_mm(v.position),
                "drill_mm": mm(v.drill_diameter),
                "net": net,
            }
        )
        if len(items) >= limit:
            break
    return {"total": len(vias), "returned": len(items), "vias": items}


@mcp.tool(annotations=READONLY)
def list_zones() -> dict:
    """List zones on the live board: name, layers, net, priority, fill state."""
    board = ipc.get_board()
    zones = board.get_zones()
    items = []
    for z in zones:
        items.append(
            {
                "id": kiid_str(z),
                "name": z.name,
                "layers": [enum_to_layer(l) for l in z.layers],
                "net": z.net.name if z.net else None,
                "priority": z.priority,
                "filled": z.filled,
            }
        )
    return {"total": len(zones), "zones": items}


@mcp.tool(annotations=READONLY)
def get_footprint_pads(reference: str) -> dict:
    """Pads of a footprint on the live board (e.g. 'U1'): pad number, net and
    absolute board position (mm). Essential before routing tracks to pins."""
    board = ipc.get_board()
    fp = None
    for candidate in board.get_footprints():
        if candidate.reference_field.text.value == reference:
            fp = candidate
            break
    if fp is None:
        refs = sorted(f.reference_field.text.value for f in board.get_footprints())[:60]
        raise ToolError(f"Footprint '{reference}' not found. Present: {refs}")
    pads = []
    for pad in fp.definition.pads:
        # Pads of a placed footprint come back in absolute board coordinates
        # (verified against KiCad 10.0.4).
        pads.append(
            {
                "number": pad.number,
                "net": pad.net.name if pad.net else None,
                "position_mm": pos_to_mm(pad.position),
            }
        )
    return {
        "reference": reference,
        "position_mm": pos_to_mm(fp.position),
        "rotation_deg": angle_deg(fp.orientation),
        "pad_count": len(pads),
        "pads": pads,
    }


@mcp.tool(annotations=READONLY)
def get_selection() -> dict:
    """Describe items currently selected in the PCB editor (type and id),
    plus KiCad's own textual dump of the selection."""
    board = ipc.get_board()
    selection = board.get_selection()
    items = [
        {"type": type(item).__name__, "id": kiid_str(item)}
        for item in selection
    ]
    text = ""
    try:
        text = board.get_selection_as_string()
    except Exception:
        pass
    return {"count": len(items), "items": items, "as_text": text[:8000]}
