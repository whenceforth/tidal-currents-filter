# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-file Python script that reads NOAA annual current prediction files and identifies days with favorable sailing conditions for an the East Bay→Golden Gate Bridge run. "Favorable" means the flood→ebb slack falls in a target morning time window (default 10:00–12:00), leaving a long ebb to carry the boat out to the Gate.

## Running the script

```bash
uv run current-filter.py data/SFB1202_17_Annual_2026.txt
uv run current-filter.py data/SFB1202_17_Annual_2026.txt --weekends-and-holidays-only
uv run current-filter.py data/SFB1202_17_Annual_2026.txt --after 2026-07-01 --before 2026-09-30
```

The script uses PEP 723 inline dependency metadata (`# /// script` block at top); `uv run` handles the `holidays` package automatically with no setup required.

## Running tests

```bash
uv run pytest tests/ -v
```

A `pyproject.toml` exists for test dependencies (pytest, skyfield). The PEP 723 `# /// script` block only applies when running the script itself via `uv run`; pytest needs the separate `pyproject.toml`.

## Testing gotcha: importing the hyphenated script

`current-filter.py` can't be imported with a normal `import` statement. Tests use `importlib.util.spec_from_file_location()` and register the module in `sys.modules` (required for Python 3.13 dataclass validation). See `tests/test_current_filter.py` for the boilerplate.

## Lunar feature (`--lunar`)

```bash
uv run current-filter.py data/SFB1202_17_Annual_2026.txt --lunar
```

Prints a moon data sub-line under each candidate: phase emoji, elongation from sun, declination, distance + perigee/apogee trajectory, altitude/azimuth at slack time. Uses `skyfield` + JPL ephemeris `data/de421.bsp` (gitignored, ~13 MB, auto-downloaded on first use from `https://ssd.jpl.nasa.gov/ftp/eph/planets/bsp/de421.bsp`).

## Architecture

**Data flow:** `parse_header_years` + `parse_events` → `find_candidates` → filter → `format_report`

**Key design decision:** the finder works linearly on the event list, not indexed by calendar date. Each event is either `slack`, `ebb`, or `flood`. When a qualifying slack is found at index `i`, the script grabs `events[i-1..i+3]` directly to get the surrounding context (previous flood peak, ebb peak, ebb-end slack, next flood peak).

**Direction check:** the NOAA data has two slacks per tidal cycle — flood→ebb and ebb→flood. The script distinguishes them by checking `events[i-1].kind == 'flood'` (not by speed, which is always `-` for slacks).

**`Candidate` dataclass** carries the qualifying slack plus its surrounding events, tier (`primary`/`secondary`), and the window bounds used to find it. The window bounds are stored on the candidate so `score()` can compute a timing bonus relative to the actual window, not hardcoded defaults.

**Scoring** (`Candidate.score()`): weighted sum of ebb duration (×0.5), ebb peak speed (×1.0), and timing bonus (×0.3, higher for earlier slack in window). Secondary-window candidates get −2.0.

**Output flags** (columns 0–2 before the date): `▶` weekend, `H` weekday holiday, `?` secondary window.

## Data

NOAA annual current prediction files for station SFB1202_17 (Golden Gate Bridge, 0.88 nm NE). Files in `data/` cover 2026–2028. Download additional years from:
`https://tidesandcurrents.noaa.gov/noaacurrents/annual.html?id=SFB1202_17`

File format: whitespace-delimited, `Date Time Event Speed` with `#` comment header. The `# From:` header line gives the date range and is used to load the correct holiday years. The `# Latitude:` and `# Longitude:` header lines give the station coordinates (used by `--lunar` for altitude/azimuth). NOAA timestamps are LST/LDT (Pacific local time with DST); convert to UTC via `ZoneInfo('America/Los_Angeles')`.

## Domain context

SF Bay tides are **mixed semidiurnal** — two unequal ebb/flood cycles per day. The qualifying slack is always the *afternoon* ebb (the weaker of the two daily ebbs in summer). Ebb speeds are mild in summer (0.6–1.0 kts) and grow stronger in fall (up to 3+ kts in November). Good days cluster in 2–3 day runs at each neap cycle. The tide and wind are roughly anti-correlated seasonally: the reliable afternoon westerly runs May–September while the strongest tidal windows are October onward.
