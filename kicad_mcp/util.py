"""Unit and layer-name conversions between MCP tools (mm, "F.Cu") and kipy (nm, enums)."""

from kipy.geometry import Vector2
from kipy.proto.board.board_types_pb2 import BoardLayer
from kipy.util.units import from_mm, to_mm
from mcp.server.fastmcp.exceptions import ToolError


def vec_mm(x_mm: float, y_mm: float) -> Vector2:
    return Vector2.from_xy(from_mm(x_mm), from_mm(y_mm))


def pos_to_mm(v) -> dict:
    return {"x_mm": round(to_mm(v.x), 6), "y_mm": round(to_mm(v.y), 6)}


def layer_to_enum(name: str) -> int:
    """Canonical KiCad layer name ("F.Cu", "Edge.Cuts") -> BoardLayer enum value."""
    key = "BL_" + name.strip().replace(".", "_")
    try:
        return BoardLayer.Value(key)
    except ValueError:
        valid = [n.removeprefix("BL_").replace("_", ".") for n in BoardLayer.keys()]
        raise ToolError(f"Unknown layer '{name}'. Valid layers: {valid}") from None


def enum_to_layer(value: int) -> str:
    try:
        return BoardLayer.Name(value).removeprefix("BL_").replace("_", ".")
    except ValueError:
        return f"unknown({value})"


def mm(nm_value: int) -> float:
    return round(to_mm(nm_value), 6)


def kiid_str(item) -> str:
    """Stable string form of an item's KIID, tolerant of wrapper differences."""
    kiid = getattr(item, "id", None)
    if kiid is None:
        return ""
    return str(getattr(kiid, "value", kiid))


def angle_deg(angle) -> float:
    """Degrees from a kipy Angle, tolerant of wrapper differences."""
    for attr in ("degrees", "value_degrees"):
        v = getattr(angle, attr, None)
        if isinstance(v, (int, float)):
            return float(v)
    try:
        import math

        return round(math.degrees(angle.to_radians()), 4)
    except Exception:
        return 0.0
