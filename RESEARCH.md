# Research: Serwer MCP dla KiCad 10.0 (Windows)

Data: 2026-07-13 · Instalacja badana: `C:\Program Files\KiCad\10.0` (KiCad **10.0.4**) · System: Windows 11

---

## 1. Zweryfikowany stan lokalnej instalacji

| Element | Stan | Uwagi |
|---|---|---|
| KiCad | 10.0.4 | `kicad-cli version` → 10.0.4 |
| Python wbudowany | 3.11.5 | `C:\Program Files\KiCad\10.0\bin\python.exe` |
| Bindingi SWIG `pcbnew` | ✅ działają | `import pcbnew` OK w Pythonie KiCada (site-packages: `pcbnew.py`, `_pcbnew.pyd`) |
| IPC API (biblioteki) | ✅ obecne | `kiapi.dll`, `nng.dll` (transport), `libprotobuf.dll` |
| `kicad-cli.exe` | ✅ pełny zestaw | pcb: drc/export/render/import/upgrade; sch: erc/export; fp/sym; jobset |
| Python systemowy | 3.12.10 | Windows Store (`WindowsApps\python.exe`), brak `py` launchera |
| Flaga `api.enable_server` | była **false** → ustawiona **true** | `%APPDATA%\kicad\10.0\kicad_common.json`; backup: `kicad_common.json.bak-mcp-research` |

### 1.1 Test praktyczny end-to-end (wykonany na tej maszynie)

Zainstalowano `kicad-python` (kipy) **0.7.1** w venv na Pythonie 3.12, uruchomiono `pcbnew.exe`
z testową płytką i połączono się przez IPC API:

```text
connected on attempt 1
kicad version: 10.0.4 (10.0.4)
api version:   10.0.1 (10.0.1-0-g2db9e5a72b)
board: test_board.kicad_pcb  · nets: 1 · footprints: 0
```

Zapis również działa — utworzono przelotkę przez `begin_commit()` / `create_items()` / `push_commit()`.

**Wniosek: pełna ścieżka MCP → kipy → KiCad 10 na Windows jest potwierdzona praktycznie.**

Wykryta pułapka API: property zwracają **kopie** obiektów proto — `via.position.x_nm = ...`
nie zadziała (mutuje kopię). Trzeba przypisywać całe obiekty: `via.position = Vector2.from_xy(...)`.

Wykryty błąd kipy 0.7.1: moduł `kipy.schematic` **nie importuje się** (`ImportError: BusEntryType`) —
wygenerowane protobufy w wydaniu PyPI zawierają tylko ułamek typów schematu. To spójne z faktem,
że serwer IPC dla schematów istnieje dopiero w KiCad 11 (patrz §3).

---

## 2. Cztery możliwe drogi integracji z KiCad

| Droga | Edycja PCB | Edycja SCH | Headless | Status w v10 | Przyszłość |
|---|---|---|---|---|---|
| **A. IPC API (kipy)** | ✅ pełna, live w GUI | ❌ (v11+) | ❌ (v11: `kicad-cli api-server`) | oficjalne, stabilne | **docelowa droga KiCada** |
| **B. SWIG `pcbnew`** | ✅ na plikach | ❌ | ✅ | deprecated od v9 | **usuwane w KiCad 11** |
| **C. `kicad-cli`** | ❌ (tylko odczyt/eksport) | ❌ | ✅ | stabilne | rozwijane (jobsets) |
| **D. Parsowanie S-expression** (kiutils, kicad-sch-api) | ⚠️ ryzykowna | ⚠️ jedyna opcja w v10 | ✅ | nieoficjalne | ryzyko przy zmianach formatu |

### A. IPC API — szczegóły
- Architektura: **protobuf + NNG**; na Windows **named pipe** (`api.sock`, przy wielu instancjach dopisywany PID).
- Połączenie: env `KICAD_API_SOCKET` i `KICAD_API_TOKEN` (kipy czyta je domyślnie; przy jednej instancji `KiCad()` bez argumentów wystarcza — potwierdzone lokalnie).
- Wymaga **działającego GUI KiCad** z włączonym API (Preferences → Plugins → „Enable KiCad API", czyli `api.enable_server` w `kicad_common.json`). Serwer API działa też w samodzielnym `pcbnew.exe` (potwierdzone).
- Wywołania są **synchroniczne** i przechodzą przez wątek UI — gdy KiCad ma otwarty dialog modalny, wołania timeoutują. Serwer MCP musi to obsługiwać (retry/backoff + czytelny błąd).
- Model transakcji: `begin_commit()` → zmiany → `push_commit()` (jeden krok undo) / `drop_commit()`.
- Zakres Board API (zweryfikowany introspekcją kipy 0.7.1): footprints, tracks, vias, zones (+`refill_zones`), nets, pads, groups, wymiary, stackup, selekcja, `hit_test`, `get_items_by_net/netclass` (10.0.1+), `save/save_as`, title block, `get_as_string` (S-expr wycinka), `run_action` (niestabilne).
- **Brak w API**: uruchamiania DRC (tylko przez `kicad-cli pcb drc`), plotowania/eksportów (tylko CLI), schematów (v11).
- Debug: log żądań API włączany w `kicad_advanced`, plik `logs/api.log`.

### B. SWIG pcbnew
Działa headless na plikach `.kicad_pcb` bez uruchomionego KiCada, ale wymaga Pythona
z instalacji KiCada (3.11) i **znika w KiCad 11**. Nadaje się co najwyżej jako
przejściowy fallback — nie warto na nim opierać nowego projektu.

### C. kicad-cli (10.0.4)
- `pcb`: **drc**, export (gerbers, drill, pos, step/glb/stl/brep/ply/u3d/xao, pdf/3dpdf, dxf, svg, ipc2581, odb, ipcd356, gencad, stats), **render** (PNG/JPEG 3D — świetne do podglądu dla LLM), import, upgrade.
- `sch`: **erc**, export (netlist: kicadsexpr/kicadxml/spice/pads…, bom, pdf, svg, dxf, hpgl?), upgrade.
- `fp`/`sym`: export svg, upgrade. `jobset run` — automatyzacja wielu zadań naraz.
- W v10 **nie ma** `api-server` (headless IPC) — to KiCad 11.

### D. Pliki S-expression
Jedyny sposób na **edycję schematów** w v10 (brak oficjalnego API SCH). Biblioteki:
`kiutils`, `kicad-sch-api` (format-preserving), `kicad-skip`. Wszystkie projekty
używające tej drogi określają ją jako „experimental" — bywały korupcje plików.
KiCad nie robi hot-reload: po edycji pliku trzeba zamknąć/otworzyć dokument.

---

## 3. Wersje i harmonogram KiCada (istotne dla planowania)

- **KiCad 10.0.0**: wydany 2026-03-20; 10.0.4 = bieżąca instalacja użytkownika.
- **KiCad 10 nie dodał** API schematów ani headless — to cechy **KiCad 11** (w rozwoju):
  `kicad-cli api-server`, handlery API w eeschema, `kipy.get_schematic()`, `KiCad(headless=True)`.
- **SWIG usuwany w v11.** Nowy kod → wyłącznie IPC API.
- Stanowisko zespołu KiCad (Seth Hillbrand, devlist 2025-10): **brak planów oficjalnej integracji AI/LLM**;
  wszystkie serwery MCP to projekty społeczności. Sensowne kierunki wg zespołu: generowanie
  symboli/footprintów z datasheetów, ERC wzbogacone o datasheety.

### kipy / kicad-python
- PyPI: `kicad-python`, import `kipy`; **0.7.1** (2026-04-17); Python ≥3.9; zależności: `protobuf`, `pynng`; MIT; wspiera KiCad 9.0+.
- Dokumentacja: https://docs.kicad.org/kicad-python-main/ (uwaga: dokumentuje gałąź dev = KiCad 11).
- Repo: https://gitlab.com/kicad/code/kicad-python

---

## 4. Istniejące serwery MCP dla KiCada (stan 2026-07-13)

| Projekt | ★ | Aktywność | Podejście | Zakres | Windows |
|---|---|---|---|---|---|
| [mixelpixx/KiCAD-MCP-Server](https://github.com/mixelpixx/KiCAD-MCP-Server) | ~1519 | bardzo aktywny | TS+Python; hybryda SWIG + IPC (eksperym.) + CLI + kicad-skip | **122 narzędzia** (PCB, SCH, DRC, eksporty, JLCPCB, Freerouting) | ✅ pełne |
| [mixelpixx/**Konnect**](https://github.com/mixelpixx/Konnect) | 38 (nowy, 2026-07) | bardzo aktywny | **Rust, czysty IPC API**, natywny plugin KiCad 10 | 171 narzędzi, skills, DFM | ✅ | 
| [lamaalrajih/kicad-mcp](https://github.com/lamaalrajih/kicad-mcp) | ~487 | ⚠️ martwy od 2025-10 | Python FastMCP; tylko pliki + CLI | analiza/odczyt, bez edycji | ✅ |
| [Seeed-Studio/kicad-mcp-server](https://github.com/Seeed-Studio/kicad-mcp-server) | 62 | umiarkowana | S-expr + SWIG + CLI | 23 narzędzia analityczne; edycja SCH eksperym. | ✅ |
| [oaslananka/kicad-mcp-pro](https://github.com/oaslananka/kicad-mcp-pro) | 24 | aktywny | CLI + pliki; PyPI `kicad-mcp-pro` | **377 narzędzi** (deklarowane), SI/PI, SPICE, DFM | ? |
| [Huaqiu-Electronics/kicad-mcp](https://github.com/Huaqiu-Electronics/kicad-mcp) | 8 | średnia | **czysty IPC (kipy)**; PyPI `kicad-mcp` | 4 typy edytorów; skąpa dokumentacja | ? |
| [ProductOfAmerica/mcp-server-kicad](https://github.com/ProductOfAmerica/mcp-server-kicad) | 4 | krótki zryw (03.2026) | kiutils + CLI (bez KiCada) | 102 narzędzia w 5 serwerach | ✅ |
| [bunnyf/pcb-mcp](https://github.com/bunnyf/pcb-mcp) | 9 | stagnacja | CLI/pliki; PyPI `kicad-mcp-server` | 23 narzędzia, Freerouting async | ✅ |
| [circuit-synth/mcp-kicad-sch-api](https://github.com/circuit-synth/mcp-kicad-sch-api) | 20 | martwy | kicad-sch-api (S-expr) | tylko schematy, 9 narzędzi | ✅ |

Wnioski z ekosystemu:
1. **mixelpixx dominuje**, a jego pivot do Konnect (Rust, czysty IPC, AGPL-3.0) potwierdza kierunek: **IPC API to przyszłość, SWIG jest porzucany**.
2. Nazwy na PyPI już zajęte: `kicad-mcp` (Huaqiu), `kicad-mcp-server` (bunnyf), `kicad-mcp-pro`, `mcp-server-kicad`.
3. Czyste serwery IPC są niedojrzałe — **nisza na dopracowany, windowsowy serwer IPC+CLI istnieje**.
4. Każdy projekt edytujący schematy plikowo nazywa to „experimental".
5. Alternatywy code-first: tscircuit (LLM-native, TS), atopile (poszło w Agent Skills, nie MCP), SKiDL.

---

## 5. Stack MCP po stronie serwera (stan 2026-07)

- Spec MCP: stabilna rewizja **2025-11-25**; 2026-07-28 (RC) wnosi stateless core i Tasks — kompatybilne wstecz.
- **Oficjalne SDK `mcp` 1.28.x** (`from mcp.server.fastmcp import FastMCP`) — stabilne; v2.0 w becie (rename `FastMCP`→`MCPServer`), na dziś nie używać w produkcji.
- **`fastmcp` 3.x** (projekt jlowin): timeouty narzędzi, testy in-memory, middleware, auth — wygodniejszy do sterowania aplikacją desktopową.
- Python ≥3.10 (systemowy 3.12.10 pasuje).
- Transport dla Claude Code/Desktop: **stdio**. Windows: podawać **bezwzględną ścieżkę do python.exe z venv** (unikać aliasu WindowsApps); `cmd /c` potrzebny tylko dla npx, nie dla Pythona.
- Rejestracja w Claude Code: `claude mcp add kicad -- C:\KiCAD_MCP\.venv\Scripts\python.exe C:\KiCAD_MCP\server.py` lub `.mcp.json`.
- Zasady projektowe: nigdy nie pisać na stdout (tylko stderr); długie operacje (render, autorouting, DRC dużej płytki) jako **start → job_id → status/poll → cancel**; błędy domenowe jako tool error (`isError: true`), nie wyjątki protokołu; structured output z typów zwracanych; zwracać podsumowania + ID zamiast wielkich zrzutów (limit ~10k tokenów).

---

## 6. Rekomendowana architektura

**Serwer w Pythonie (systemowy 3.12 + venv w `C:\KiCAD_MCP`), stdio, trzy warstwy backendów:**

```
Claude (MCP client)
   │ stdio
┌──▼───────────────────────────────────────────┐
│  server.py  (FastMCP)                        │
│                                              │
│  Backend 1: kipy (IPC) ──────► żywa sesja    │  edycja PCB, selekcja, commit/undo,
│    · auto-detekcja/launch KiCada             │  odczyt płytki, refill zones
│    · ping/reconnect, obsługa timeoutów       │
│                                              │
│  Backend 2: kicad-cli (subprocess) ─► pliki  │  DRC/ERC, gerbery, STEP, render PNG,
│    · headless, bez GUI                       │  BOM, netlisty, jobsets
│                                              │
│  Backend 3: kiutils / kicad-sch-api ─► pliki │  odczyt schematów zawsze;
│    · edycja SCH za flagą "experimental"      │  edycja opt-in, z backupem pliku
└──────────────────────────────────────────────┘
```

Decyzje:
- **Nie używać SWIG** — znika w v11; wszystko co daje SWIG, da kipy (edycja) lub CLI (headless).
- **Jedno narzędzie = jedna intencja użytkownika** (np. `place_footprint`, `route_track`, `run_drc`, `export_gerbers`, `board_snapshot_png`), nie 1:1 z metodami API.
- Jednostki: API używa **nanometrów** — na granicy MCP przyjmować mm i konwertować (`kipy.util.units.from_mm`).
- Health-check: narzędzie `kicad_status` (ping, wersja, otwarte dokumenty, czy API włączone) + automatyczna diagnostyka „KiCad nie działa / API wyłączone / dialog modalny blokuje".
- Render podglądu: `kicad-cli pcb render` → PNG zwracany jako image content — daje LLM „oczy" bez GUI.

**Etapy implementacji:**
1. **MVP (1 dzień):** połączenie + status, odczyt płytki (footprints/nets/tracks), `run_drc`, `export_gerbers`, `render_board`.
2. **Edycja PCB:** commit-wrapper, place/move footprint, tracks/vias/zones, selekcja, save.
3. **Schematy (odczyt):** kiutils + `kicad-cli sch export netlist/bom` + ERC.
4. **Schematy (edycja, opt-in):** kicad-sch-api z backupami; jasne ostrzeżenia.
5. **KiCad 11 (przyszłość):** przejście na `kicad-cli api-server` (headless) i schematic IPC — architektura z warstwą backendów zrobi to bezboleśnie.

**Ryzyka:**
- IPC wymaga uruchomionego GUI (v10) — serwer musi umieć wystartować KiCada/pcbnew i czekać na socket.
- Timeouty przy dialogach modalnych — komunikować użytkownikowi „zamknij dialog w KiCadzie".
- kipy 0.7.1: proto-copy semantics (przypisywać całe obiekty), zepsuty moduł `schematic` (nie dotykać do v11).
- Równoległe instancje KiCada → nazwa pipe z PID; obsłużyć wybór instancji.

---

## 7. Zmiany wykonane na tej maszynie podczas researchu

- `%APPDATA%\kicad\10.0\kicad_common.json`: `api.enable_server` **false → true** (wymagane dla IPC; backup obok: `kicad_common.json.bak-mcp-research`).
- Venv testowy + skrypty + testowa płytka w katalogu scratchpad sesji (tymczasowe, poza projektem).
- Testowy `pcbnew.exe` uruchomiony i zamknięty; zmiany na testowej płytce nie były zapisywane.

## 8. Kluczowe źródła

- IPC API: https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/
- kipy docs: https://docs.kicad.org/kicad-python-main/ · repo: https://gitlab.com/kicad/code/kicad-python · PyPI: https://pypi.org/project/kicad-python/
- kicad-cli 10.0: https://docs.kicad.org/10.0/en/cli/cli.html
- KiCad 10.0.0 release: https://www.kicad.org/blog/2026/03/Version-10.0.0-Released/
- Stanowisko zespołu ws. AI: http://www.mail-archive.com/devlist@kicad.org/msg00800.html
- MCP spec: https://modelcontextprotocol.io/specification/2025-11-25 · Python SDK: https://github.com/modelcontextprotocol/python-sdk · FastMCP: https://gofastmcp.com
- Claude Code MCP: https://code.claude.com/docs/en/mcp
- Projekty: linki w tabeli §4
