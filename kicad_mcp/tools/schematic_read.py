"""Read-only schematic tools (headless).

KiCad 10 has no IPC API for schematics, so these tools work on .kicad_sch
files through kicad-cli: the XML netlist is the source of truth for
components and nets, ERC/BOM/PDF come straight from the CLI.
"""

import csv
import json
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from mcp.server.fastmcp.exceptions import ToolError

from kicad_mcp.app import EXPORT, READONLY, mcp
from kicad_mcp.backends import cli


def _resolve_sch(sch_path: str) -> Path:
    p = Path(sch_path)
    if not p.exists():
        raise ToolError(f"Schematic file not found: {p}")
    if p.suffix.lower() != ".kicad_sch":
        raise ToolError(f"Not a KiCad schematic (.kicad_sch): {p}")
    return p


_netlist_cache: dict[str, tuple[float, ET.Element]] = {}


def _netlist_xml(sch: Path) -> ET.Element:
    """Export (or reuse a cached) XML netlist; cache key is the file mtime."""
    key = str(sch.resolve()).lower()
    mtime = sch.stat().st_mtime
    cached = _netlist_cache.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    out = Path(tempfile.mkdtemp(prefix="kicad_mcp_")) / f"{sch.stem}.xml"
    cli.run_cli(
        ["sch", "export", "netlist", "--format", "kicadxml", "--output", str(out), str(sch)]
    )
    root = ET.parse(out).getroot()
    if len(_netlist_cache) > 8:
        _netlist_cache.clear()
    _netlist_cache[key] = (mtime, root)
    return root


@mcp.tool(annotations=READONLY)
def list_schematic_components(sch_path: str) -> dict:
    """List components of a schematic (all hierarchy sheets): reference,
    value, footprint, library symbol and sheet."""
    sch = _resolve_sch(sch_path)
    root = _netlist_xml(sch)
    comps = []
    for comp in root.iterfind("./components/comp"):
        libsource = comp.find("libsource")
        sheetpath = comp.find("sheetpath")
        comps.append(
            {
                "reference": comp.get("ref"),
                "value": (comp.findtext("value") or "").strip(),
                "footprint": (comp.findtext("footprint") or "").strip(),
                "library_symbol": (
                    f"{libsource.get('lib')}:{libsource.get('part')}" if libsource is not None else None
                ),
                "sheet": sheetpath.get("names") if sheetpath is not None else "/",
            }
        )
    return {"schematic": str(sch), "count": len(comps), "components": comps}


@mcp.tool(annotations=READONLY)
def list_schematic_nets(sch_path: str, name_filter: str | None = None, limit: int = 200) -> dict:
    """List nets of a schematic with their connected pins (reference + pin
    number), from the exported netlist."""
    sch = _resolve_sch(sch_path)
    root = _netlist_xml(sch)
    nets = []
    for net in root.iterfind("./nets/net"):
        name = net.get("name", "")
        if name_filter and name_filter.lower() not in name.lower():
            continue
        nodes = [
            {"ref": n.get("ref"), "pin": n.get("pin"), "pinfunction": n.get("pinfunction")}
            for n in net.iterfind("node")
        ]
        nets.append({"name": name, "nodes": nodes})
        if len(nets) >= limit:
            break
    return {"schematic": str(sch), "returned": len(nets), "nets": nets}


@mcp.tool(annotations=EXPORT)
def run_erc(sch_path: str) -> dict:
    """Run Electrical Rules Check on a schematic; returns violation counts
    and details from the JSON report."""
    sch = _resolve_sch(sch_path)
    report = sch.parent / "mcp-exports" / "erc" / f"{sch.stem}-erc.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    cli.run_cli(
        ["sch", "erc", "--format", "json", "--severity-all", "--output", str(report), str(sch)]
    )
    data = json.loads(report.read_text(encoding="utf-8"))
    violations = []
    by_severity: dict[str, int] = {}
    for sheet in data.get("sheets", []):
        for v in sheet.get("violations", []):
            sev = v.get("severity", "unknown")
            by_severity[sev] = by_severity.get(sev, 0) + 1
            if len(violations) < 50:
                violations.append(
                    {
                        "sheet": sheet.get("path"),
                        "type": v.get("type"),
                        "severity": sev,
                        "description": v.get("description"),
                    }
                )
    return {
        "schematic": str(sch),
        "report_file": str(report),
        "violation_count": sum(by_severity.values()),
        "violations_by_severity": by_severity,
        "violations": violations,
    }


@mcp.tool(annotations=EXPORT)
def export_bom(sch_path: str, output_path: str | None = None) -> dict:
    """Export a BOM (CSV, grouped by value+footprint) and return its rows."""
    sch = _resolve_sch(sch_path)
    out = (
        Path(output_path)
        if output_path
        else sch.parent / "mcp-exports" / "bom" / f"{sch.stem}-bom.csv"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    cli.run_cli(
        [
            "sch",
            "export",
            "bom",
            "--fields",
            "Reference,Value,Footprint,${QUANTITY}",
            "--group-by",
            "Value,Footprint",
            "--output",
            str(out),
            str(sch),
        ]
    )
    with out.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    return {"schematic": str(sch), "bom_file": str(out), "line_count": len(rows), "lines": rows[:300]}


@mcp.tool(annotations=EXPORT)
def export_schematic_pdf(sch_path: str, output_path: str | None = None) -> dict:
    """Plot the schematic (all sheets) to a PDF."""
    sch = _resolve_sch(sch_path)
    out = (
        Path(output_path)
        if output_path
        else sch.parent / "mcp-exports" / "pdf" / f"{sch.stem}.pdf"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    cli.run_cli(["sch", "export", "pdf", "--output", str(out), str(sch)])
    return {"schematic": str(sch), "pdf_file": str(out)}
