"""Repair for kicad-sch-api's empty (instances) bug.

When kicad-sch-api 0.5.6 edits a schematic that was originally created by
KiCad (not by the library itself), it writes symbols with an EMPTY
(instances) block. KiCad then treats those symbols as absent from every
sheet: they don't render, don't netlist and don't ERC - silently.

The fix fills each empty (instances) block with the standard root-sheet
instance entry derived from the symbol's own Reference property and unit.
"""

import re

_ROOT_UUID_RE = re.compile(r'^\t\(uuid "([0-9a-fA-F-]+)"\)', re.M)
_REFERENCE_RE = re.compile(r'\(property "Reference"\s+"((?:[^"\\]|\\.)*)"')
_UNIT_RE = re.compile(r'\(unit (\d+)\)')
_EMPTY_INSTANCES_RE = re.compile(r'\n(\t+)\(instances\)')


def fill_empty_instances(text: str, project_name: str = "") -> tuple[str, int]:
    """Return (fixed_text, fill_count). Safe no-op when nothing is empty."""
    if "\n\t\t(instances)" not in text and "(instances)" not in text:
        return text, 0
    m = _ROOT_UUID_RE.search(text)
    if not m:
        return text, 0
    root_uuid = m.group(1)

    # Work symbol-block by symbol-block so each empty (instances) gets ITS
    # OWN reference/unit. Root-level symbol instances start with "\n\t(symbol\n".
    parts = re.split(r'(?=\n\t\(symbol\n)', text)
    fixed = 0
    out = []
    for part in parts:
        if "\n\t\t(instances)" in part or re.search(_EMPTY_INSTANCES_RE, part):
            ref_m = _REFERENCE_RE.search(part)
            unit_m = _UNIT_RE.search(part)
            ref = ref_m.group(1) if ref_m else "?"
            unit = unit_m.group(1) if unit_m else "1"

            def _fill(match: re.Match) -> str:
                indent = match.group(1)
                inner = indent + "\t"
                return (
                    f"\n{indent}(instances"
                    f"\n{inner}(project \"{project_name}\""
                    f"\n{inner}\t(path \"/{root_uuid}\""
                    f"\n{inner}\t\t(reference \"{ref}\")"
                    f"\n{inner}\t\t(unit {unit})"
                    f"\n{inner}\t)"
                    f"\n{inner})"
                    f"\n{indent})"
                )

            part, n = _EMPTY_INSTANCES_RE.subn(_fill, part)
            fixed += n
        out.append(part)
    return "".join(out), fixed
