
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

The CLI supports single-moment observation, time-series traces, event detection across configurable date ranges, real-time chart playback, and a REST API server — in both tropical and sidereal zodiac systems.

---

## Dependencies

- **pyswisseph** — Swiss Ephemeris bindings (positions, phenomena, houses)
- **rich** — terminal table rendering
- **timezonefinder** / **pytz** — local → UTC conversion from coordinates
- **numpy** — numerical operations
- **moderngl** / **moderngl-window** / **glfw** — OpenGL chart rendering
- **Pillow** — font/image loading for the chart renderer

---

## Installation

```bash
git clone https://github.com/Clairaut/atlas.git
cd atlas
pip install .
```

---

## CLI Reference

The top-level command is `atlas`. Four subcommands are available: `observe`, `seek`, `chart`, and `serve`.

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
| `--step` | Step size for range queries — e.g. `1d`, `6h`, `30m` |
| `-l`, `--location` | Observer location `'(lat,lon,alt)'` |
| `-z`, `--zodiac` | `tropical` (default) or `sidereal` |
| `-a`, `--attributes` | Extra output: `phase`, `aspects`, `elongation` |
| `-f`, `--frames` | Coordinate frames: `ecliptic`, `equatorial`, `horizontal` |
| `-c`, `--concise` | Compact single-line output |

**Examples:**
```bash
atlas observe sun moon venus                        # current positions
atlas observe moon --at 1999-08-11                 # positions at a date
atlas observe sun --from 2026-01-01 --to 2026-06-01 --step 1d   # trace
atlas observe moon -a phase                        # position + phase data
atlas observe sun moon -f ecliptic equatorial      # multiple frames
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
| `--detail` | Filter by sub-type (e.g. `full`, `trine`, `rising`, `scorpio`) |
| `--at` | Search start moment |
| `--from` / `--to` | Explicit date range |
| `--limit` | Max results in next-occurrence mode (default `1`) |
| `-l`, `--location` | Observer location — required for `diurnal` events |
| `-z`, `--zodiac` | `tropical` (default) or `sidereal` |
| `-c`, `--concise` | Compact output |

#### Event Types

**`aspect`** — Geometric relationships between bodies (conjunction, sextile, square, trine, opposition).
Without a range, returns a snapshot of currently active aspects. With `--limit`, returns the next N aspect formations.
```bash
atlas seek aspect                                  # active aspects now
atlas seek aspect sun moon --at 1999-09-29         # active aspects on a date
atlas seek aspect --detail trine                   # active trines now
atlas seek aspect --limit 5                        # next 5 aspect entrances
atlas seek aspect --from 2026-01-01 --to 2026-06-01
```

**`phase`** — Phase crossings: new, waxing crescent, first quarter, waxing gibbous, full, waning gibbous, last quarter, waning crescent.
```bash
atlas seek phase moon                              # next moon phase crossing
atlas seek phase moon --detail full                # next full moon
atlas seek phase moon --detail full --limit 6      # next 6 full moons
atlas seek phase venus --detail new                # next new venus
```

**`ingress`** — Sign ingresses (body enters a new zodiac sign).
```bash
atlas seek ingress moon                            # next moon ingress
atlas seek ingress moon --detail scorpio           # next moon into Scorpio
atlas seek ingress mars --limit 3                  # next 3 mars ingresses
```

**`station`** — Retrograde and direct stations (dlon crosses zero).
```bash
atlas seek station mercury                         # next mercury station
atlas seek station mercury --detail retrograde     # next mercury retrograde
atlas seek station --limit 5                       # next 5 stations, all bodies
```

**`elongation`** — Synodic cycle events for superior planets: conjunction, eastern quadrature, opposition, western quadrature.
```bash
atlas seek elongation jupiter                      # next jupiter synodic event
atlas seek elongation jupiter --detail opposition  # next jupiter opposition
atlas seek elongation saturn --limit 4
```

**`diurnal`** — Daily horizon crossings relative to the observer: rising, setting, culmination (upper transit), anti-culmination (lower transit). Requires a configured observer location.
```bash
atlas seek diurnal moon                            # next moon diurnal event
atlas seek diurnal moon --detail rising            # next moonrise
atlas seek diurnal sun --detail setting            # next sunset
atlas seek diurnal moon --detail culmination       # next moon at MC
atlas seek diurnal moon --limit 4                  # next 4 diurnal events
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

**Modes:**
```bash
atlas chart                                        # radix chart, now
atlas chart --at 1999-08-11 12:00                  # radix at a date
atlas chart --transit 2026-06-01                   # dual-ring transit chart
atlas chart --from 2026-01-01 --to 2026-06-01 --step 1d   # playback
atlas chart live                                   # real-time live chart
atlas chart --save chart.png                       # save static chart
atlas chart --save playback.mp4                    # save playback video
```

---

### `serve`

Start the Atlas REST API server. Exposes celestial observation data over HTTP.

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
curl "1http://127.0.0.1:5001/observe?targets=sun,moon&at=1999-09-29T12:00:00"
curl "http://127.0.0.1:5001/observe?zodiac=sidereal&lat=48.85&lon=2.35"
```

---

## Configuration

Atlas reads from `~/.config/atlas/atlas.toml`, creating a default if missing. Key sections:

- **`location`** — default observer lat/lon/alt used when `--location` is not specified
- **`celestials`** — body registry: SwissEph ID, glyph, name, orbit type
- **`ephemeris`** — path to SwissEph data files

---

## Architecture

```
src/atlas/
├── cli.py                  # argument parsing and display
├── serve.py                # Flask REST API server
├── clients/
│   └── ephe_client.py      # SwissEph wrapper (positions, phenomena, houses, horizontal conversion)
├── core/
│   ├── observatory.py      # coordinate system management, JD, observation calls
│   └── wizard.py           # high-level event detection and state conjuring
├── models/
│   ├── celestial_state.py  # per-body state (position, phase, elongation, horizontal)
│   ├── aspect.py           # aspect model and definitions
│   ├── event.py            # event model
│   └── location.py         # observer location
├── utils/
│   ├── config.py           # config loader
│   ├── logger.py           # logging
│   └── chrono.py           # UTC conversion
└── view/
    └── chart.py            # OpenGL chart renderer (radix, transit, playback, live)
```
