# KiCad MCP Server

Serwer MCP (Model Context Protocol) sterujący **KiCad 10** na Windows. Łączy trzy backendy:

| Backend | Do czego | Wymaga |
|---|---|---|
| **IPC API** (kipy) | odczyt i edycja płytki na żywo (footprinty, ścieżki, przelotki, strefy, selekcja, zapis) | uruchomiony edytor PCB z włączonym API |
| **kicad-cli** | DRC/ERC, gerbery, STEP, PDF, render 3D, BOM, netlisty | nic (headless) |
| **kicad-sch-api** | edycja plików schematów (eksperymentalna, opt-in) | `KICAD_MCP_ENABLE_SCH_EDIT=1` |

Raport z researchu poprzedzającego projekt: [RESEARCH.md](RESEARCH.md).

## Wymagania

- KiCad 10.0.x w `C:\Program Files\KiCad\10.0` (inna ścieżka: ustaw env `KICAD_ROOT`)
- Python 3.10+ (venv w `.venv`)
- Włączone API w KiCadzie: **Preferences → Plugins → Enable KiCad API** (restart KiCada po zmianie)

## Instalacja

```powershell
python -m venv .venv
.venv\Scripts\pip install mcp kicad-python kiutils kicad-sch-api
```

Rejestracja w Claude Code — plik [.mcp.json](.mcp.json) w tym katalogu robi to automatycznie
dla sesji uruchamianych w `C:\KiCAD_MCP`. Globalnie:

```powershell
claude mcp add --scope user kicad -- C:\KiCAD_MCP\.venv\Scripts\python.exe C:\KiCAD_MCP\server.py
```

Claude Desktop (`%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "kicad": {
      "command": "C:\\KiCAD_MCP\\.venv\\Scripts\\python.exe",
      "args": ["C:\\KiCAD_MCP\\server.py"]
    }
  }
}
```

## Narzędzia (39)

**Status / cykl życia:** `kicad_status`, `launch_kicad`

**Odczyt płytki (IPC, żywy edytor):** `board_info`, `list_footprints`, `list_nets`,
`list_tracks`, `list_vias`, `list_zones`, `get_selection`

**Edycja płytki (IPC, każda zmiana = 1 krok undo):** `place_footprints` (wsadowe),
`add_tracks` (wsadowe), `place_footprint`, `move_footprint`, `remove_footprint`,
`add_track`, `add_via`, `remove_items`, `refill_zones`, `save_board`,
`select_items`, `clear_selection`

**Kontrole i eksporty (headless, na plikach):** `run_drc`, `export_gerbers`, `export_step`,
`export_pdf`, `render_board` (zwraca PNG)

**Schematy — odczyt (headless):** `list_schematic_components`, `list_schematic_nets`,
`run_erc`, `export_bom`, `export_schematic_pdf`, `sch_statistics`

**Schematy — edycja (opt-in):** `sch_apply_edits` (wsadowe — cały obwód w jednym
wywołaniu), `sch_edit_status`, `sch_create_schematic`, `sch_add_component`,
`sch_add_wire`, `sch_connect_pins`, `sch_add_label`

## Wydajność — używaj narzędzi wsadowych

Każde wywołanie narzędzia to pełna runda przez model (kilkanaście sekund i więcej).
Budowanie schematu po jednym symbolu na wywołanie zajmuje godziny; **`sch_apply_edits`
wstawia cały obwód (symbole + połączenia pinów + etykiety) w jednym wywołaniu w ~2 s**.
Analogicznie na PCB: `place_footprints` i `add_tracks` zamiast pętli pojedynczych wywołań.
Operacje wsadowe są atomowe: błąd w dowolnym elemencie = plik/płytka bez zmian.

## Konwencje

- Współrzędne i wymiary w **mm**; rotacje w stopniach; warstwy nazwami kanonicznymi (`F.Cu`, `Edge.Cuts`).
- Narzędzia plikowe bez podanej ścieżki działają na płytce otwartej w edytorze (zapisując ją najpierw).
- Edycje płytki nie zapisują pliku — wywołaj `save_board`.
- Edycja schematów tworzy kopię zapasową `*.mcp-backup-<timestamp>` przy pierwszej zmianie w sesji;
  po edycji plik trzeba ponownie otworzyć w eeschema (KiCad nie robi hot-reload).

## Ograniczenia (KiCad 10)

- IPC API wymaga **działającego GUI** edytora PCB (headless `kicad-cli api-server` dopiero w KiCad 11).
- Brak IPC API dla schematów (stąd edycja plikowa jako opcja eksperymentalna; API w KiCad 11).
- Gdy KiCad ma otwarty dialog modalny, wywołania IPC timeoutują — zamknij dialog i ponów.
- Przy kilku instancjach KiCada ustaw `KICAD_API_SOCKET` (nazwa gniazda zawiera wtedy PID).

## Zmienne środowiskowe

| Zmienna | Domyślnie | Znaczenie |
|---|---|---|
| `KICAD_ROOT` | `C:\Program Files\KiCad\10.0` | katalog instalacji KiCada |
| `KICAD_CLI` | `<KICAD_ROOT>\bin\kicad-cli.exe` | ścieżka kicad-cli |
| `KICAD_MCP_ENABLE_SCH_EDIT` | `0` | `1` włącza edycję schematów |
| `KICAD_MCP_LAUNCH_WAIT` | `45` | ile sekund czekać na IPC po `launch_kicad` |
| `KICAD_API_SOCKET` | auto | jawna ścieżka gniazda IPC (wiele instancji) |

## Licencja

[MIT](LICENSE)
