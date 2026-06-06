
                       ▒▒▒▒▒▒▒▒▒▒
                    ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒
                  ▒▒▒▒            ▒▒▒▒
                 ▓▒▒▒  ░            ▒▒▓
                ▒▒▒  ░               ▒▒▓
              ▒▒▒▒ ░                  ▒▒▒▒
              ▒▒▒▒                    ▒▒▒▒
               ▒▓▒▒                  ▒▒▓▒
                ▓▓▒▒                ▒▒▓▓
                 ▓▓▒▒▒            ▒▒▒▓▓
                ▒▒▓▒▒▒▒▒▒▒▒    ▒▒▒▒▒▒▒▓▒▓
                 ▒▓▓▒▓▓▒▒▒▒▒▒▒▒▒▒▓▓▒▒▓▒
                    ▒▓▓▓▒▒▒▒▒▒▒▒▓▓▓▒▒
                        ▒▒▒▒▒▒▒▒

              Atlas — Celestial Navigation for SwissEph

---

## About

Atlas is a celestial navigation interface for Swiss Ephemeris. It computes planetary positions, tracks phases and synodic cycles, detects celestial events, and renders astrological charts using a modern OpenGL pipeline.

The CLI supports single-moment observation, time-series traces, event detection across configurable date ranges, real-time chart playback, a full-sky dome view, and a REST API server — in both tropical and sidereal zodiac systems.

---

## Dependencies

- **pyswisseph** — Swiss Ephemeris bindings (positions, phenomena, houses)
- **rich** — terminal table rendering
- **timezonefinder** / **pytz** — local → UTC conversion from coordinates
- **numpy** — numerical operations
- **moderngl** / **moderngl-window** / **glfw** — OpenGL chart rendering
- **Pillow** — font/image loading for the chart and dome renderer

---

## Installation

```bash
git clone https://github.com/Clairaut/atlas.git
cd atlas
pip install -e .
```

---

## CLI Reference

The top-level command is `atlas`. Subcommands: `observe`, `seek`, `chart`, `dome`, and `serve`.

---

### `observe`

Observe one or more celestial bodies at a moment or over a time range.

```
atlas observe {targets}* [options]
```

| Flag | Description |
|------|-------------|
| `--at` | Observation datetime `'YYYY-MM-DD [HH:MM[:SS]]'` |
| `--from` / `--to` | Time range for trace mode |
| `--step` | Step size for range queries — e.g. `1d`, `6h`, `30M` |
| `-l`, `--location` | Observer location `'(lat,lon,alt)'` |
| `-z`, `--zodiac` | `tropical` (default) or `sidereal` |
| `-a`, `--attributes` | Extra output: `phase`, `aspects`, `elongation`, `mag` |
| `-s`, `--system` | Coordinate systems: `ecliptic`, `equatorial`, `horizontal` |
| `-c`, `--concise` | Compact single-line output |

**Examples:**
```bash
atlas observe sun moon venus                                      # current positions
atlas observe moon --at 1999-08-11                               # positions at a date
atlas observe sun --from 2026-01-01 --to 2026-06-01 --step 1d   # trace
atlas observe moon -a phase                                       # position + phase data
atlas observe sun moon -s ecliptic equatorial                     # multiple systems
```

---

### `seek`

Find celestial events by type. Without `--from`/`--to`, returns the next N occurrences from now (or `--at`). With `--from`/`--to`, returns all event entrances in that range.

```
atlas seek {type} [targets]* [options]
```

**Event types:** `aspect`, `phase`, `ingress`, `station`, `elongation`, `diurnal`

| Flag | Description |
|------|-------------|
| `--detail` | Filter by sub-type — case-insensitive substring match |
| `--at` | Search start moment |
| `--from` / `--to` | Explicit date range |
| `--limit` | Max results in next-occurrence mode (default `1`) |
| `-l`, `--location` | Observer location — required for `diurnal` events |
| `-z`, `--zodiac` | `tropical` (default) or `sidereal` |
| `-c`, `--concise` | Compact output |

#### `--detail` keywords by type

| Type | Keywords |
|------|----------|
| `phase` | `new`, `waxing crescent`, `first quarter`, `waxing gibbous`, `full`, `waning gibbous`, `last quarter`, `waning crescent` |
| `ingress` | `aries`, `taurus`, `gemini`, `cancer`, `leo`, `virgo`, `libra`, `scorpio`, `sagittarius`, `capricorn`, `aquarius`, `pisces` |
| `station` | `retrograde`, `direct` |
| `aspect` | `conjunction`, `sextile`, `square`, `trine`, `opposition` |
| `elongation` | `conjunction`, `eastern quadrature`, `opposition`, `western quadrature` |
| `diurnal` | `rising`, `setting`, `culmination`, `anti-culmination` |

#### Event Types

**`aspect`** — Geometric relationships between bodies.
```bash
atlas seek aspect                                    # next aspect entrance
atlas seek aspect --detail trine                     # next trine
atlas seek aspect --limit 5                          # next 5 aspect entrances
atlas seek aspect --from 2026-01-01 --to 2026-06-01
```

**`phase`** — Phase crossings for the Moon and inferior planets.
```bash
atlas seek phase moon                                # next moon phase crossing
atlas seek phase moon --detail full                  # next full moon
atlas seek phase moon --detail full --limit 6        # next 6 full moons
```

**`ingress`** — Sign ingresses.
```bash
atlas seek ingress moon                              # next moon ingress
atlas seek ingress moon --detail scorpio             # next moon into Scorpio
atlas seek ingress mars --limit 3                    # next 3 mars ingresses
```

**`station`** — Retrograde and direct stations.
```bash
atlas seek station mercury                           # next mercury station
atlas seek station mercury --detail retrograde       # next mercury retrograde
atlas seek station --limit 5                         # next 5 stations, all bodies
```

**`elongation`** — Synodic cycle events for superior planets.
```bash
atlas seek elongation jupiter                        # next jupiter synodic event
atlas seek elongation jupiter --detail opposition    # next jupiter opposition
atlas seek elongation venus --detail eastern         # next venus eastern quadrature
```

**`diurnal`** — Daily horizon crossings relative to the observer.
```bash
atlas seek diurnal moon                              # next moon diurnal event
atlas seek diurnal moon --detail rising              # next moonrise
atlas seek diurnal sun --detail setting              # next sunset
atlas seek diurnal moon --limit 4                    # next 4 diurnal events
```

---

### `chart`

Render an astrological chart. Four modes: static radix, transit (dual-ring), playback, and live.

```
atlas chart [targets]* [options]
```

| Flag | Description |
|------|-------------|
| `--at` | Chart datetime |
| `--transit` | Transit datetime — renders a dual-ring transit chart |
| `--from` / `--to` | Playback range |
| `--step` | Playback time step |
| `--speed` | Playback steps per second (default `1.0`) |
| `--save` | Save path — `.png` for static, `.mp4` for playback |
| `-l`, `--location` | Observer location |
| `-z`, `--zodiac` | `tropical` (default) or `sidereal` |
| `-T`, `--title` | Chart title |

```bash
atlas chart                                                       # radix chart, now
atlas chart --at "1999-08-11 12:00"                               # radix at a date
atlas chart --transit 2026-06-01                                  # dual-ring transit chart
atlas chart --from 2026-01-01 --to 2026-06-01 --step 1d          # playback
atlas chart --save chart.png                                      # save static chart
atlas chart --save playback.mp4                                   # save playback video
```

---

### `dome`

Render an interactive full-sky dome (azimuthal equidistant projection) with star field and planet overlay.

```
atlas dome [targets]* [options]
```

| Flag | Description |
|------|-------------|
| `--at` | Observation datetime |
| `--mag` | Star magnitude cutoff (default `6.5`) |
| `--brightness` | Star brightness multiplier `0.0–2.0` (default `1.0`) |
| `-l`, `--location` | Observer location |

```bash
atlas dome                             # full-sky dome, now
atlas dome --at "2026-06-01 22:00"    # dome at a specific time
atlas dome --mag 5.0                   # brighter stars only
```

---

### `serve`

Start the Atlas REST API server.

```
atlas serve [options]
```

| Flag | Description |
|------|-------------|
| `--host` | Bind host (default `127.0.0.1`) |
| `--port` | Bind port (default `5001`) |

**Endpoint:** `GET /observe`

| Param | Description |
|-------|-------------|
| `at` | Datetime `YYYY-MM-DD[THH:MM:SS]` (default: now) |
| `targets` | Comma-separated body names (default: all configured) |
| `zodiac` | `tropical` (default) or `sidereal` |
| `lat` / `lon` / `alt` | Observer location (default: config values) |

```bash
atlas serve                          # start on 127.0.0.1:5001
atlas serve --port 8080              # custom port

curl "http://127.0.0.1:5001/observe"
curl "http://127.0.0.1:5001/observe?targets=sun,moon&at=1999-09-29T12:00:00"
curl "http://127.0.0.1:5001/observe?zodiac=sidereal&lat=48.85&lon=2.35"
```

---

## Configuration

Atlas reads from `~/.config/atlas/atlas.toml`, creating a default if missing.

- **`location`** — default observer lat/lon/alt used when `--location` is not specified
- **`celestials`** — body registry: SwissEph ID, glyph, name, orbit type
- **`ephemeris`** — path to SwissEph data files

---

## Architecture

```
src/atlas/
├── cli.py                    # argument parsing and display
├── serve.py                  # Flask REST API server
├── core/
│   ├── atlas.py              # high-level state and event building
│   ├── observatory.py        # coordinate systems, JD, SwissEph calls
│   └── scanner.py            # event detection and bisection
├── models/
│   ├── celestial_state.py    # per-body state (position, phase, elongation)
│   ├── aspect.py             # aspect model and definitions
│   ├── event.py              # event model
│   └── location.py           # observer location
├── utils/
│   ├── config.py             # config loader
│   ├── chrono.py             # UTC/local conversion
│   └── constellation.py      # constellation identification
└── view/
    ├── base.py               # shared OpenGL base, glyph atlas, shader loading
    ├── chart.py              # chart renderer (radix, transit, playback, live)
    └── experimental/
        └── dome.py           # full-sky dome renderer
```
