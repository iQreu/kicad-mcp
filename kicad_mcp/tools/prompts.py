"""MCP prompts - exposed by Claude Code as /mcp__kicad__<name> commands."""

from kicad_mcp.app import mcp


@mcp.prompt(title="Design review")
def design_review(project_dir: str) -> str:
    """Full review of a KiCad project: ERC, DRC, BOM sanity and visual checks."""
    return f"""Przeprowadź przegląd projektu KiCad w katalogu: {project_dir}

1. Znajdź pliki .kicad_sch i .kicad_pcb w tym katalogu.
2. Uruchom run_erc na schemacie i run_drc na płytce; podsumuj naruszenia wg wagi.
3. Wygeneruj BOM (export_bom) i sprawdź: brakujące footprinty, puste wartości,
   niespójne oznaczenia.
4. Obejrzyj view_schematic i view_board - oceń czytelność rozmieszczenia
   i oczywiste problemy (nakładające się elementy, brak obrysu płytki).
5. Podaj listę problemów od najpoważniejszych, z konkretnymi lokalizacjami,
   oraz proponowane poprawki. Nie wprowadzaj zmian bez potwierdzenia."""


@mcp.prompt(title="Fabrication package")
def fab_package(board_path: str) -> str:
    """Generate a complete manufacturing package for a board."""
    return f"""Przygotuj komplet plików produkcyjnych dla płytki: {board_path}

1. Najpierw run_drc - jeśli są błędy (severity=error), zatrzymaj się i pokaż je.
2. export_gerbers (z plikami wierceń), export_position_file (csv, mm),
   export_step oraz export_pdf (F.Cu,B.Cu,F.SilkS,B.SilkS,Edge.Cuts).
3. Wypisz ścieżki wszystkich wygenerowanych plików i krótkie podsumowanie
   (liczba warstw, liczba elementów, rozmiar płytki z board_info jeśli dostępne)."""
