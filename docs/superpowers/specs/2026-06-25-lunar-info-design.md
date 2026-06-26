# Lunar Info Feature — Design Spec

- **Date:** 2026-06-25
- **Branch:** lunar-info
- **Goal:** Add an optional lunar data sub-line under each candidate in the report, to help the user build intuition about how the moon's position and phase relate to tidal conditions.

---

## Motivation

The moon drives the tides, but the absolute numbers (phase %, distance in km) don't build intuition on their own. This feature surfaces the moon's state in terms that connect directly to tidal quality:
- **Phase angle** shows where we are in the spring/neap cycle
- **Declination** explains the diurnal inequality that SF Bay's mixed semidiurnal tides depend on
- **Distance + perigee/apogee trajectory** shows whether tidal range is strengthening or weakening
- **Altitude/azimuth** grounds the abstract numbers in something visible in the sky

---

## CLI

New flag: `--lunar`

Opt-in, off by default. When absent, output and behavior are identical to the current script. When present, a lunar sub-line is printed under each candidate row.

If `--lunar` is passed and `de421.bsp` is absent, the script auto-downloads it from JPL before proceeding, printing a progress message to stderr. No manual setup required.

---

## Ephemeris File

**Library:** `skyfield` (pure Python, no C extensions), added to the PEP 723 `# dependencies` block alongside `holidays`.

**File:** `data/de421.bsp` (~13 MB, covers 1900–2050, never needs updating). Listed in `.gitignore` since the repo is public and the file is large; auto-downloaded on first `--lunar` run.

Auto-download uses skyfield's own `Loader.download()` method — no additional dependency:

```python
load = Loader(data_dir)
if not ephem_path.exists():
    print(f'Downloading de421.bsp to {ephem_path} (~13 MB)...', file=sys.stderr)
    load.download(_EPHEM_URL)
```

`data_dir` is `str(Path(args.input).parent)` — since NOAA files live in `data/`, the parent directory IS `data/`, so no `/ 'data'` suffix needed.

Loaded via skyfield's `Loader` class pointed at the `data/` directory (relative to the input file's path):

```python
from skyfield.api import Loader
load = Loader(data_dir)
planets = load('de421.bsp')
```

---

## New Parsing: Observer Location

Extend the existing header-parsing logic to extract `# Latitude:` and `# Longitude:` from the NOAA file header. These are already present:

```
# Latitude:         37.8292
# Longitude:        -122.4620
```

Returns `(lat: float, lon: float)` for use as the skyfield observer location. This is the Golden Gate Bridge station — appropriate for altitude/azimuth calculations since it's the tidal reference point and close enough to the departure area.

---

## LunarInfo Dataclass

A new frozen dataclass returned by `lunar_info(dt, lat, lon, planets, earth)`:

```python
@dataclass(frozen=True)
class LunarInfo:
    emoji:        str    # one of 🌑🌒🌓🌔🌕🌖🌗🌘
    elongation:   float  # degrees from sun; 0=new, 180=full
    declination:  float  # degrees; + = north of equator
    distance_km:  int    # rounded to nearest km
    peri_apo:     str    # e.g. "peri in 3d" or "apo 2d ago"
    altitude:     float  # degrees above horizon at slack time
    azimuth_card: str    # compass direction, e.g. "WSW"
```

### Phase emoji

Elongation ranges 0–180°; waxing/waning is a separate boolean (elongation increasing vs decreasing, sampled by comparing `t` vs `t + 1 hour`). Mapping:

Elongation is 0–180° (angular separation from sun). Waxing/waning distinguishes which half of the orbit:

| Elongation | Waxing | Waning |
|---|---|---|
| < 22.5° | 🌑 | 🌑 |
| 22.5–67.5° | 🌒 | 🌘 |
| 67.5–112.5° | 🌓 | 🌗 |
| 112.5–157.5° | 🌔 | 🌖 |
| > 157.5° | 🌕 | 🌕 |

New (🌑) and full (🌕) don't distinguish waxing/waning since they're at the transition point.

### Perigee/apogee trajectory

Scan the moon's distance at daily intervals over a ±30-day window centered on the candidate date. Find local minima (perigee) and maxima (apogee). Report the nearest one as:
- `"peri in Nd"` — perigee is N days in the future
- `"peri Nd ago"` — perigee was N days ago
- `"apo in Nd"` / `"apo Nd ago"` — same for apogee

### Altitude and azimuth

Computed at the qualifying slack datetime using a skyfield `wgs84` observer at the parsed lat/lon. Azimuth in degrees converted to the nearest of 16 compass points (N, NNE, NE, ENE, E, ESE, SE, SSE, S, SSW, SW, WSW, W, WNW, NW, NNW).

---

## Output Format

Sub-line printed immediately after each candidate line, indented 5 spaces (past the `▶H?` flag columns):

```
▶   2026-10-18  Sun  slack 10:42  ebb -2.1 kts @ 13:30  end 17:15  (6h33m)  next flood +2.8 @ 19:45  [4h03m to flood]  [4.2]
     🌔 108°  decl +18.4°  dist 382k km  peri in 3d  alt 41° WSW
```

If the moon is below the horizon at slack time, altitude is shown as a negative number (e.g., `alt -12°`), which is meaningful — it tells you the moon recently set or hasn't risen yet.

---

## Help Text

The `--lunar` argparse entry includes a sample line and field key in its help string:

```
--lunar   Add a lunar data line under each candidate, e.g.:
            🌔 108°  decl +18.4°  dist 382k km  peri in 3d  alt 41° WSW
          Fields:
            🌔       phase emoji (🌑 new → 🌕 full → 🌑)
            108°     elongation from sun (0°=new moon, 180°=full moon)
            decl     moon's declination (+=north, -=south of equator)
            dist     distance from Earth in km
            peri/apo days to/from nearest perigee (closest) or apogee (farthest)
            alt      altitude above horizon at slack time; bearing = compass dir
          Requires data/de421.bsp (13 MB, covers through 2050):
            https://ssd.jpl.nasa.gov/ftp/eph/planets/bsp/de421.bsp
```

---

## Future Work (out of scope)

- **Interior bay station overlay:** The flood→ebb slack at interior Central Bay stations lags the Gate by 1–2 hours. A future `--interior-station` flag could parse a second NOAA file and display the interior slack time on the sub-line for reference, helping estimate how long initial flood current will oppose the departure leg.

---

## Data Flow Changes

```
parse_header_location(path) → (lat, lon)          [new]
lunar_info(dt, lat, lon, planets, earth) → LunarInfo  [new]

main():
  if args.lunar:
    load ephemeris → planets, earth
    parse lat/lon from header
  format_report(..., lunar_fn=...)                 [extended]

format_report():
  for each candidate:
    print existing line
    if lunar_fn:
      info = lunar_fn(candidate.slack.dt)
      print lunar sub-line                         [new]
```
