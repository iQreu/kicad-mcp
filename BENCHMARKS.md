# Testy wydajnościowe

Środowisko: Windows 11, KiCad 10.0.4, Python 3.12, projekt demo `interf_u`
(25 footprintów, 733 ścieżki, 174 sieci, 84 przelotki). Wartości = mediana z 2–5 przebiegów.
Data: 2026-07-14.

## Start serwera i narzut protokołu MCP

| Operacja | Czas |
|---|---|
| Spawn procesu + `initialize` (raz na sesję) | 0,72 s |
| Import serwera / rejestracja 54 narzędzi | 0,55 s |
| `tools/list` (54 narzędzia) | <0,01 s |
| **Narzut protokołu na wywołanie narzędzia** | **~1 ms** |

## Narzędzia live IPC (żywy edytor PCB)

| Narzędzie | Czas |
|---|---|
| start pcbnew + gotowość IPC (jednorazowo) | 7,6 s |
| `board_info` | 24 ms |
| `list_footprints` / `list_nets` / `list_tracks` / `list_vias` | 1–11 ms |
| `get_footprint_pads` (20 padów) | 10 ms |
| `place_footprint` (pojedynczy) | 17 ms |
| **`place_footprints` (wsad ×10)** | **16 ms** |
| `move_footprint` | 35 ms |
| `add_track` (1 segment, z siecią) | 29 ms |
| **`add_tracks` (wsad ×10 polilinii)** | **33 ms** |
| `add_via` | 33 ms |
| `refill_zones` | 0,81 s |

Wniosek: koszt wsadu ×10 ≈ koszt pojedynczej operacji — dominują stałe koszty
rundy IPC, nie liczba elementów.

## Narzędzia headless (kicad-cli / pliki)

| Narzędzie | Czas |
|---|---|
| `search_symbols` — zimny start (budowa indeksu 22,8k symboli) | 0,86 s |
| `search_symbols` / `search_footprints` — ciepłe | <10 ms |
| `get_symbol_details` (zimne / ciepłe) | 0,69 s / <10 ms |
| `run_drc` | 2,2 s |
| `run_erc` | 2,3 s |
| `export_gerbers` (22 pliki + wiercenia) | 0,81 s |
| `export_step` | 2,2 s |
| `export_position_file` | 0,34 s |
| `render_board` (raytracing 3D, 1200 px) | 1,05 s |
| **`view_board` (2D, 1200 px)** | **0,62 s** |
| `view_schematic` (1400 px) | 1,85 s |
| `list_schematic_components` (zimne / cache) | 0,39 s / <10 ms |
| `export_bom` | 0,36 s |
| `create_project` | 0,56 s |
| `set_netclass` | <10 ms |
| `set_custom_drc_rules` + weryfikacja kanarkiem (pełny DRC) | 2,8 s |

## Skalowanie edycji wsadowej schematu (`sch_apply_edits`)

| Rozmiar wsadu | Czas |
|---|---|
| 10 symboli + 9 połączeń | 0,31 s |
| 30 symboli + 29 połączeń | 0,33 s |
| 60 symboli + 59 połączeń | 0,34 s |
| pojedynczy `sch_add_component` do pliku z 60 symbolami | 0,37 s |

Czas jest praktycznie płaski — dominuje stały koszt (load + save + `kicad-cli sch upgrade`),
nie liczba elementów.

## Interpretacja

Serwer dokłada ~1 ms na wywołanie; wszystkie operacje mieszczą się w 0–3 s.
W realnym zadaniu czas zjadają **rundy przez model** (kilkanaście–kilkadziesiąt
sekund każda), dlatego kluczowe dla czasu całkowitego jest używanie narzędzi
wsadowych: obwód 60 symboli to jedno wywołanie (0,34 s + 1 runda modelu)
zamiast 60 rund.
