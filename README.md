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
.venv\Scripts\pip install -r requirements.txt
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

## Narzędzia (54) i prompty

**Status / cykl życia:** `kicad_status`, `launch_kicad`, `create_project`

**Podgląd wizualny (samokontrola modelu):** `view_board` (szybki widok 2D warstw),
`view_schematic` (PNG arkusza schematu) — kicad-cli SVG + rasteryzacja resvg

**Ustawienia projektu:** `list_netclasses`, `set_netclass` (szerokości ścieżek,
prześwity, przelotki, pary różnicowe + przypisania sieci wzorcami w .kicad_pro),
`get_custom_drc_rules`, `set_custom_drc_rules` (reguły .kicad_dru z weryfikacją
„kanarkiem" — KiCad po cichu ignoruje pliki z błędną składnią lub BOM)

**Biblioteki (odkrywanie lib_id):** `search_symbols`, `search_footprints`,
`get_symbol_details` (opis, datasheet i **lista pinów** — sprawdź przed łączeniem)

**Odczyt płytki (IPC, żywy edytor):** `board_info`, `list_footprints`, `list_nets`,
`list_tracks`, `list_vias`, `list_zones`, `get_footprint_pads` (pozycje i sieci padów
— podstawa routingu), `get_selection`

**Edycja płytki (IPC, każda zmiana = 1 krok undo):** `place_footprints` (wsadowe),
`add_tracks` (wsadowe), `place_footprint`, `move_footprint`, `remove_footprint`,
`add_track`, `add_via`, `add_copper_zone` (strefa miedzi z refillem),
`draw_board_outline` (Edge.Cuts), `remove_items`, `refill_zones`, `save_board`,
`select_items`, `clear_selection`

**Kontrole i eksporty (headless, na plikach):** `run_drc`, `export_gerbers`, `export_step`,
`export_pdf`, `export_position_file` (pick&place dla montażu), `run_jobset`,
`render_board` (raytracing PNG)

**Prompty (w Claude Code jako slash-komendy):** `/mcp__kicad__design_review <katalog>`
(pełny przegląd: ERC+DRC+BOM+wizualna ocena), `/mcp__kicad__fab_package <płytka>`
(komplet plików produkcyjnych z bramką DRC)

Wszystkie narzędzia mają adnotacje MCP (`readOnlyHint`/`destructiveHint`/`idempotentHint`) —
klienci mogą np. zrównoleglać wywołania tylko-do-odczytu.

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
- Po każdym zapisie schematu plik jest normalizowany do bieżącego formatu KiCada
  (`kicad-cli sch upgrade`) — pliki zawsze wychodzą w formacie zainstalowanej wersji (v10),
  a nieudany upgrade przywraca poprzednią zawartość pliku (podwójna walidacja zapisu).

## Ograniczenia (KiCad 10)

- IPC API wymaga **działającego GUI** edytora PCB (headless `kicad-cli api-server` dopiero w KiCad 11).
- Brak IPC API dla schematów (stąd edycja plikowa jako opcja eksperymentalna; API w KiCad 11).
- Gdy KiCad ma otwarty dialog modalny, wywołania IPC timeoutują — zamknij dialog i ponów.
- Przy kilku instancjach KiCada ustaw `KICAD_API_SOCKET` (nazwa gniazda zawiera wtedy PID);
  `launch_kicad` sam celuje w instancję z żądaną płytką, a wyniki narzędzi mutujących
  zawierają pole `board` z nazwą zmienionej płytki.
- Odpowiedzi „KiCad is busy" (np. w trakcie refillu stref) są automatycznie ponawiane
  z backoffem — narzędzia nie zwracają ulotnych błędów zajętości.

## Roadmapa (KiCad 11, spodziewany ~luty 2027)

- `Board.import_netlist` (synchronizacja schemat→PCB, odpowiednik F8) — jest w gałęzi dev
  kipy / KiCad 11; w KiCad 10 brak tej ścieżki przez IPC.
- Tryb headless `kicad-cli api-server` — zniesie wymóg działającego GUI; IPC API
  zyska też plotowanie i edytor schematów.
- Autorouting Freerouting: w KiCad 10 headless DSN/SES istnieje wyłącznie przez
  przestarzałe SWIG (`ExportSpecctraDSN`/`ImportSpecctraSES` — usuwane w v11,
  brak następcy; kicad-cli nie ma eksportu Specctra nawet w gałęzi master).
- Kreator jobsetów (.kicad_jobset to JSON — `run_jobset` już je uruchamia).

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
