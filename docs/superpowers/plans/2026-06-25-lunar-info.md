# Lunar Info Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--lunar` flag to `current-filter.py` that prints a moon data sub-line under each candidate row, surfacing phase, elongation, declination, distance, perigee/apogee trajectory, and altitude/azimuth at the qualifying slack time.

**Architecture:** All changes live in the single-file script `current-filter.py`, following the existing pattern of dataclasses + pure functions. A new `LunarInfo` dataclass holds computed lunar fields; a `lunar_info()` function computes them via `skyfield`; `format_report()` gains an optional `lunar_fn` callback; `main()` wires the flag. A new `tests/test_current_filter.py` covers the pure helper functions (no ephemeris required) plus one skip-if-absent integration test.

**Tech Stack:** Python 3.11+, `skyfield` (pure Python astronomy library), `de421.bsp` JPL ephemeris file (~13 MB, covers 1900–2050), `zoneinfo` (stdlib, for UTC conversion of LST/LDT timestamps), `pytest` for tests.

## Global Constraints

- Single-file script: all production code stays in `current-filter.py`
- PEP 723 inline script metadata: all new dependencies go in the `# dependencies = [...]` block
- Run with: `uv run current-filter.py <args>`
- Run tests with: `uv run pytest tests/` (add `pytest` to dependencies block if not present)
- Ephemeris file lives at `data/de421.bsp` relative to the NOAA input file's directory
- NOAA timestamps are LST/LDT (Pacific local time with DST); must convert to UTC via `zoneinfo.ZoneInfo('America/Los_Angeles')` before passing to skyfield
- `--lunar` is opt-in; default behavior is unchanged
- Python 3.11+ (`zoneinfo` is stdlib; `requires-python = ">=3.11"` already set)

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `current-filter.py` | Modify | All production code: new dependency, new parsing, new dataclass, new helpers, new computation function, updated formatter and CLI |
| `tests/test_current_filter.py` | Create | Unit tests for pure helpers; one integration test (skipped if `data/de421.bsp` absent) |

---

### Task 1: Parse observer location from NOAA header

**Files:**
- Modify: `current-filter.py` (add `parse_header_location()` near `parse_header_years()`)
- Create: `tests/test_current_filter.py`

**Interfaces:**
- Produces: `parse_header_location(path: str) -> tuple[float, float]` — returns `(lat, lon)` as floats; raises `SystemExit` with a clear message if lines are missing

- [ ] **Step 1: Create test file and write failing test**

Create `tests/__init__.py` (empty) and `tests/test_current_filter.py`:

```python
import sys
import textwrap
import tempfile
import os
from pathlib import Path

# Allow importing from the script directly
sys.path.insert(0, str(Path(__file__).parent.parent))

# current-filter.py has a hyphen so we must import via importlib
import importlib.util, types

def _load_script():
    spec = importlib.util.spec_from_file_location(
        "current_filter",
        Path(__file__).parent.parent / "current-filter.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

cf = _load_script()


def _make_noaa_file(content: str) -> str:
    """Write content to a temp file and return its path."""
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
    f.write(content)
    f.close()
    return f.name


SAMPLE_HEADER = textwrap.dedent("""\
    # Source:           NOAA/NOS/CO-OPS
    # Station ID:       SFB1202
    # Station Name:     Golden Gate Bridge, 0.88 nm NE of
    # Latitude:         37.8292
    # Longitude:        -122.4620
    # From:             2026-01-01 00:00 - 2026-12-31 23:59
    Date       Time (LST_LDT)  Event      Speed (knots)
    2026-01-01 01:21           ebb           -0.8
""")


def test_parse_header_location_returns_lat_lon():
    path = _make_noaa_file(SAMPLE_HEADER)
    try:
        lat, lon = cf.parse_header_location(path)
        assert abs(lat - 37.8292) < 0.0001
        assert abs(lon - (-122.4620)) < 0.0001
    finally:
        os.unlink(path)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_current_filter.py::test_parse_header_location_returns_lat_lon -v
```

Expected: `AttributeError: module 'current_filter' has no attribute 'parse_header_location'`

- [ ] **Step 3: Implement `parse_header_location()`**

In `current-filter.py`, add immediately after `parse_header_years()`:

```python
def parse_header_location(path: str) -> tuple[float, float]:
    """Extract observer lat/lon from the NOAA file's # Latitude/Longitude header lines."""
    lat = lon = None
    with open(path) as fh:
        for line in fh:
            if not line.startswith('#'):
                break
            m = re.match(r'#\s+Latitude:\s+([-\d.]+)', line)
            if m:
                lat = float(m.group(1))
            m = re.match(r'#\s+Longitude:\s+([-\d.]+)', line)
            if m:
                lon = float(m.group(1))
    if lat is None or lon is None:
        sys.exit('Error: could not find # Latitude / # Longitude in file header.')
    return lat, lon
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_current_filter.py::test_parse_header_location_returns_lat_lon -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add current-filter.py tests/__init__.py tests/test_current_filter.py
git commit \
  -m "feat: add parse_header_location() and test scaffolding" \
  -m "Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 2: LunarInfo dataclass and pure helper functions

**Files:**
- Modify: `current-filter.py` (add `LunarInfo` dataclass and helpers in the Data model section)
- Modify: `tests/test_current_filter.py` (add tests for all helpers)

**Interfaces:**
- Produces: `LunarInfo` dataclass (frozen)
- Produces: `_phase_emoji(elongation: float, waxing: bool) -> str`
- Produces: `_azimuth_card(az_deg: float) -> str`
- Produces: `_peri_apo_str(label: str, days_offset: float) -> str` — `label` is `'peri'` or `'apo'`; `days_offset` is positive if in the future, negative if in the past

- [ ] **Step 1: Write failing tests for all three helpers**

Append to `tests/test_current_filter.py`:

```python
# ── _phase_emoji ──────────────────────────────────────────────────────────────

def test_phase_emoji_new_moon():
    assert cf._phase_emoji(5.0, waxing=True) == '🌑'
    assert cf._phase_emoji(5.0, waxing=False) == '🌑'

def test_phase_emoji_full_moon():
    assert cf._phase_emoji(170.0, waxing=True) == '🌕'
    assert cf._phase_emoji(170.0, waxing=False) == '🌕'

def test_phase_emoji_waxing():
    assert cf._phase_emoji(45.0, waxing=True) == '🌒'
    assert cf._phase_emoji(90.0, waxing=True) == '🌓'
    assert cf._phase_emoji(135.0, waxing=True) == '🌔'

def test_phase_emoji_waning():
    assert cf._phase_emoji(135.0, waxing=False) == '🌖'
    assert cf._phase_emoji(90.0, waxing=False) == '🌗'
    assert cf._phase_emoji(45.0, waxing=False) == '🌘'

def test_phase_emoji_boundary_22_5():
    # Just inside new-moon zone
    assert cf._phase_emoji(22.0, waxing=True) == '🌑'
    # Just outside → crescent
    assert cf._phase_emoji(23.0, waxing=True) == '🌒'

# ── _azimuth_card ─────────────────────────────────────────────────────────────

def test_azimuth_card_cardinals():
    assert cf._azimuth_card(0.0)   == 'N'
    assert cf._azimuth_card(90.0)  == 'E'
    assert cf._azimuth_card(180.0) == 'S'
    assert cf._azimuth_card(270.0) == 'W'
    assert cf._azimuth_card(360.0) == 'N'

def test_azimuth_card_intercardinals():
    assert cf._azimuth_card(247.5) == 'WSW'
    assert cf._azimuth_card(22.5)  == 'NNE'

# ── _peri_apo_str ─────────────────────────────────────────────────────────────

def test_peri_apo_str_future():
    assert cf._peri_apo_str('peri', 3.4) == 'peri in 3d'

def test_peri_apo_str_past():
    assert cf._peri_apo_str('apo', -2.7) == 'apo 3d ago'

def test_peri_apo_str_today():
    assert cf._peri_apo_str('peri', 0.3) == 'peri in 0d'
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_current_filter.py -k "phase_emoji or azimuth_card or peri_apo" -v
```

Expected: all `AttributeError` (functions not yet defined)

- [ ] **Step 3: Add `LunarInfo` dataclass and helpers to `current-filter.py`**

In the `# ── Data model` section, after the `Candidate` dataclass, add:

```python
@dataclass(frozen=True)
class LunarInfo:
    emoji:        str    # one of 🌑🌒🌓🌔🌕🌖🌗🌘
    elongation:   float  # degrees from sun; 0=new, 180=full
    declination:  float  # degrees; + = north of equator
    distance_km:  int    # rounded to nearest km
    peri_apo:     str    # e.g. "peri in 3d" or "apo 3d ago"
    altitude:     float  # degrees above horizon at slack time
    azimuth_card: str    # compass direction, e.g. "WSW"


_COMPASS_16 = [
    'N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
    'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW',
]


def _phase_emoji(elongation: float, waxing: bool) -> str:
    """Map elongation (0–180°) + waxing flag to a moon phase emoji."""
    if elongation < 22.5 or elongation > 157.5:
        return '🌑' if elongation < 22.5 else '🌕'
    if elongation < 67.5:
        return '🌒' if waxing else '🌘'
    if elongation < 112.5:
        return '🌓' if waxing else '🌗'
    return '🌔' if waxing else '🌖'


def _azimuth_card(az_deg: float) -> str:
    """Convert azimuth in degrees (0=N, clockwise) to nearest 16-point compass label."""
    idx = round(az_deg / 22.5) % 16
    return _COMPASS_16[idx]


def _peri_apo_str(label: str, days_offset: float) -> str:
    """Format perigee/apogee proximity string.
    days_offset > 0 means the event is in the future, < 0 means it's in the past.
    """
    days = round(abs(days_offset))
    if days_offset >= 0:
        return f'{label} in {days}d'
    return f'{label} {days}d ago'
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_current_filter.py -k "phase_emoji or azimuth_card or peri_apo" -v
```

Expected: all `PASSED`

- [ ] **Step 5: Commit**

```bash
git add current-filter.py tests/test_current_filter.py
git commit \
  -m "feat: add LunarInfo dataclass and phase/azimuth/peri-apo helpers" \
  -m "Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 3: `lunar_info()` computation function

**Files:**
- Modify: `current-filter.py` — add `skyfield` import block (guarded by `TYPE_CHECKING`-style pattern) and `lunar_info()` function in a new `# ── Lunar ──` section
- Modify: `tests/test_current_filter.py` — add integration test

**Interfaces:**
- Consumes (from Task 2): `LunarInfo`, `_phase_emoji()`, `_azimuth_card()`, `_peri_apo_str()`
- Produces: `lunar_info(dt: datetime, lat: float, lon: float, ts, planets) -> LunarInfo`
  - `ts` = `skyfield` timescale object
  - `planets` = loaded `de421.bsp` kernel

Note on `skyfield` objects: `planets['earth']`, `planets['moon']`, `planets['sun']` are bodies. `wgs84.latlon(lat, lon)` creates a surface observer. These are imported at the top of the function from `skyfield.api` and `skyfield.toposlib`.

Note on timezone: NOAA times are LST/LDT (Pacific local time). Convert with `zoneinfo.ZoneInfo('America/Los_Angeles')` before passing to skyfield's `ts.from_datetime()`.

- [ ] **Step 1: Add `skyfield` to PEP 723 dependencies**

In `current-filter.py`, update the `# dependencies` block:

```python
# dependencies = [
#   "holidays",
#   "skyfield",
# ]
```

Also add to the imports section, near the top (after stdlib imports, before `holidays`):

```python
from zoneinfo import ZoneInfo
```

- [ ] **Step 2: Write the integration test (skipped if ephemeris absent)**

Append to `tests/test_current_filter.py`:

```python
import pytest
from datetime import datetime

_EPHEM_PATH = Path(__file__).parent.parent / 'data' / 'de421.bsp'


@pytest.mark.skipif(not _EPHEM_PATH.exists(), reason='data/de421.bsp not present')
def test_lunar_info_returns_valid_lunarinfo():
    from skyfield.api import Loader
    load = Loader(str(_EPHEM_PATH.parent))
    ts = load.timescale()
    planets = load('de421.bsp')

    # 2026-10-18 10:42 PDT = known waxing gibbous period
    dt = datetime(2026, 10, 18, 10, 42)
    info = cf.lunar_info(dt, lat=37.8292, lon=-122.462, ts=ts, planets=planets)

    assert isinstance(info, cf.LunarInfo)
    assert info.emoji in '🌑🌒🌓🌔🌕🌖🌗🌘'
    assert 0.0 <= info.elongation <= 180.0
    assert -90.0 <= info.declination <= 90.0
    assert 300_000 < info.distance_km < 410_000
    assert 'peri' in info.peri_apo or 'apo' in info.peri_apo
    assert -90.0 <= info.altitude <= 90.0
    assert info.azimuth_card in cf._COMPASS_16
```

- [ ] **Step 3: Run integration test to verify it's skipped (ephemeris not yet present)**

```bash
uv run pytest tests/test_current_filter.py::test_lunar_info_returns_valid_lunarinfo -v
```

Expected: `SKIPPED (data/de421.bsp not present)` — confirms the skip guard works. The file will be auto-downloaded at runtime (Task 4); once it exists, this test will run too.

- [ ] **Step 4: Add `data/de421.bsp` to `.gitignore`**

Create `.gitignore` in the repo root (it doesn't exist yet):

```
data/de421.bsp
```

The file will be auto-downloaded at runtime on first `--lunar` use; it must not be committed since the repo is public and the file is 13 MB.

- [ ] **Step 5: Implement `lunar_info()`**

In `current-filter.py`, add a new section after the `# ── Finder ──` section:

```python
# ── Lunar ─────────────────────────────────────────────────────────────────────

_TZ_PACIFIC = ZoneInfo('America/Los_Angeles')


def lunar_info(
    dt: datetime,
    lat: float,
    lon: float,
    ts,       # skyfield Timescale
    planets,  # skyfield kernel (de421.bsp)
) -> LunarInfo:
    """
    Compute lunar data for the given local Pacific datetime and observer position.

    dt is a naive datetime in LST/LDT (Pacific local time, as stored in NOAA data).
    """
    from skyfield.api import wgs84

    earth = planets['earth']
    moon  = planets['moon']
    sun   = planets['sun']

    # Convert LST/LDT → UTC for skyfield
    dt_local = dt.replace(tzinfo=_TZ_PACIFIC)
    t        = ts.from_datetime(dt_local)
    t1h      = ts.from_datetime(dt_local + timedelta(hours=1))

    # ── Elongation and waxing/waning ──────────────────────────────────────────
    e_now  = earth.at(t).observe(sun).apparent()
    m_now  = earth.at(t).observe(moon).apparent()
    e_1h   = earth.at(t1h).observe(sun).apparent()
    m_1h   = earth.at(t1h).observe(moon).apparent()

    elongation    = m_now.separation_from(e_now).degrees
    elongation_1h = m_1h.separation_from(e_1h).degrees
    waxing        = elongation_1h > elongation

    # ── Declination and distance ──────────────────────────────────────────────
    moon_astrometric = earth.at(t).observe(moon)
    _, dec, dist     = moon_astrometric.radec()
    declination  = dec.degrees
    distance_km  = int(round(dist.km))

    # ── Perigee / apogee: scan ±30 days at daily intervals ───────────────────
    day_offsets = range(-30, 31)
    times  = ts.from_datetimes([dt_local + timedelta(days=d) for d in day_offsets])
    _, _, dist_arr = earth.at(times).observe(moon).radec()
    dists  = dist_arr.km  # distance array (AU Distance object → km array)

    # Find local minima (perigee) and maxima (apogee)
    best_label    = None
    best_offset   = None
    best_abs      = float('inf')

    for i in range(1, len(dists) - 1):
        if dists[i] < dists[i-1] and dists[i] < dists[i+1]:
            label, offset = 'peri', float(day_offsets[i])
        elif dists[i] > dists[i-1] and dists[i] > dists[i+1]:
            label, offset = 'apo', float(day_offsets[i])
        else:
            continue
        if abs(offset) < best_abs:
            best_abs, best_label, best_offset = abs(offset), label, offset

    peri_apo = _peri_apo_str(best_label, best_offset) if best_label else 'unknown'

    # ── Altitude and azimuth ──────────────────────────────────────────────────
    observer   = wgs84.latlon(lat, lon)
    topo       = (earth + observer).at(t).observe(moon).apparent()
    alt, az, _ = topo.altaz()
    altitude   = alt.degrees
    az_card    = _azimuth_card(az.degrees)

    return LunarInfo(
        emoji        = _phase_emoji(elongation, waxing),
        elongation   = round(elongation, 1),
        declination  = round(declination, 1),
        distance_km  = distance_km,
        peri_apo     = peri_apo,
        altitude     = round(altitude, 1),
        azimuth_card = az_card,
    )
```

Note: `skyfield` vectorises over time arrays natively; the `times` computation passes a list of `datetime` objects. The `numpy` import is used implicitly by skyfield's internals — it's a skyfield dependency, not a new direct dependency.

- [ ] **Step 6: Run integration test — expect SKIPPED (ephemeris absent until Task 4 smoke test downloads it)**

```bash
uv run pytest tests/test_current_filter.py::test_lunar_info_returns_valid_lunarinfo -v
```

Expected: `SKIPPED (data/de421.bsp not present)` — the file is auto-downloaded by `main()` in Task 4; this test will pass once that happens.

- [ ] **Step 7: Run all unit tests**

```bash
uv run pytest tests/ -v
```

Expected: all unit tests pass; integration test is skipped.

- [ ] **Step 8: Commit**

```bash
git add current-filter.py tests/test_current_filter.py .gitignore
git commit \
  -m "feat: add lunar_info() with skyfield integration" \
  -m "Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 4: CLI integration — `--lunar` flag, formatter update, help text

**Files:**
- Modify: `current-filter.py` — update `format_report()`, update `main()`
- Modify: `tests/test_current_filter.py` — add test for format_report with lunar

**Interfaces:**
- Consumes (from Task 3): `lunar_info()`, `LunarInfo`, `parse_header_location()`
- Modifies: `format_report(candidates, show_secondary, us_holidays, lunar_fn=None)` — `lunar_fn` is `Optional[Callable[[datetime], LunarInfo]]`

- [ ] **Step 1: Write failing test for format_report with lunar output**

Append to `tests/test_current_filter.py`:

```python
import io
from unittest.mock import patch
from datetime import datetime, date, time, timedelta

def _make_candidate():
    """Build a minimal Candidate for format_report testing."""
    slack     = cf.Event(dt=datetime(2026, 10, 18, 10, 42), kind='slack',  speed=None)
    ebb_peak  = cf.Event(dt=datetime(2026, 10, 18, 13, 30), kind='ebb',    speed=-2.1)
    ebb_end   = cf.Event(dt=datetime(2026, 10, 18, 17, 15), kind='slack',  speed=None)
    nxt_flood = cf.Event(dt=datetime(2026, 10, 18, 19, 45), kind='flood',  speed=2.8)
    return cf.Candidate(
        slack=slack, ebb_peak=ebb_peak, ebb_end=ebb_end, next_flood=nxt_flood,
        tier='primary',
        window_open=time(10, 0), window_close=time(12, 0),
    )


def test_format_report_with_lunar_fn_prints_subline():
    fake_info = cf.LunarInfo(
        emoji='🌔', elongation=108.0, declination=18.4,
        distance_km=382000, peri_apo='peri in 3d',
        altitude=41.0, azimuth_card='WSW',
    )
    candidates = [_make_candidate()]
    with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
        cf.format_report(candidates, show_secondary=True, us_holidays={},
                         lunar_fn=lambda dt: fake_info)
        output = mock_out.getvalue()
    assert '🌔' in output
    assert '108.0°' in output
    assert 'decl +18.4°' in output
    assert '382k km' in output
    assert 'peri in 3d' in output
    assert 'alt 41.0° WSW' in output


def test_format_report_without_lunar_fn_no_subline():
    candidates = [_make_candidate()]
    with patch('sys.stdout', new_callable=io.StringIO) as mock_out:
        cf.format_report(candidates, show_secondary=True, us_holidays={},
                         lunar_fn=None)
        output = mock_out.getvalue()
    assert '🌔' not in output
    assert 'decl' not in output
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_current_filter.py -k "format_report" -v
```

Expected: `TypeError` (unexpected keyword argument `lunar_fn`)

- [ ] **Step 3: Update `format_report()` to accept and print lunar sub-line**

Change the signature and add the sub-line print. Replace the existing `format_report` function signature and add the sub-line block after the main `print(...)` call:

```python
def format_report(
    candidates:     list[Candidate],
    show_secondary: bool = True,
    us_holidays:    Optional[dict] = None,
    lunar_fn:       Optional[object] = None,   # Callable[[datetime], LunarInfo] | None
) -> None:
```

Inside the `for c in visible:` loop, after the existing `print(...)` call, add:

```python
        if lunar_fn is not None:
            info = lunar_fn(c.slack.dt)
            decl_str = f'+{info.declination}°' if info.declination >= 0 else f'{info.declination}°'
            print(
                f'     {info.emoji} {info.elongation}°'
                f'  decl {decl_str}'
                f'  dist {info.distance_km // 1000}k km  {info.peri_apo}'
                f'  alt {info.altitude}° {info.azimuth_card}'
            )
```

- [ ] **Step 4: Run format_report tests to verify they pass**

```bash
uv run pytest tests/test_current_filter.py -k "format_report" -v
```

Expected: both `PASSED`

- [ ] **Step 5: Update `main()` to wire `--lunar`**

In `main()`, add the argument after the existing `--no-secondary` argument:

```python
    p.add_argument(
        '--lunar', action='store_true',
        help=(
            'Add a lunar data line under each candidate, e.g.:\n'
            '  🌔 108.0°  decl +18.4°  dist 382k km  peri in 3d  alt 41.0° WSW\n'
            'Fields:\n'
            '  🌔       phase emoji (🌑 new → 🌕 full → 🌑)\n'
            '  108.0°  elongation from sun (0°=new moon, 180°=full moon)\n'
            '  decl    moon\'s declination (+=north, -=south of equator)\n'
            '  dist    distance from Earth in km\n'
            '  peri/apo  days to/from nearest perigee (closest) or apogee (farthest)\n'
            '  alt     altitude above horizon at slack time; bearing = compass dir\n'
            'Requires data/de421.bsp (13 MB, covers through 2050):\n'
            '  https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/planets/de421.bsp'
        ),
    )
```

Then after the `events = parse_events(args.input)` line, add ephemeris loading:

```python
    lunar_fn = None
    if args.lunar:
        from skyfield.api import Loader
        _EPHEM_URL = 'https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/planets/de421.bsp'
        data_dir   = str(Path(args.input).parent)   # NOAA files live in data/, so parent IS data/
        ephem_path = Path(data_dir) / 'de421.bsp'
        load       = Loader(data_dir)
        if not ephem_path.exists():
            print(f'Downloading de421.bsp to {ephem_path} (~13 MB)...', file=sys.stderr)
            load.download(_EPHEM_URL)
        ts       = load.timescale()
        planets  = load('de421.bsp')
        lat, lon = parse_header_location(args.input)
        lunar_fn = lambda dt: lunar_info(dt, lat=lat, lon=lon, ts=ts, planets=planets)
```

Finally, pass `lunar_fn` to `format_report`:

```python
    format_report(candidates, show_secondary=not args.no_secondary,
                  us_holidays=us_holidays_dict, lunar_fn=lunar_fn)
```

- [ ] **Step 6: Smoke test the full script**

```bash
uv run current-filter.py data/SFB1202_17_Annual_2026.txt \
  --after 2026-10-01 --before 2026-10-31 --lunar
```

Expected: candidates for October 2026 each followed by a `🌔/🌒/...` sub-line with all fields populated. Verify:
- Emoji looks right for the date (mid-October 2026 has a full moon around Oct 13)
- `dist` is in the range 356k–406k km
- `alt` is a plausible angle (-90 to 90)
- `peri in Nd` or `apo Nd ago` appears

- [ ] **Step 7: Verify `--help` output includes sample line**

```bash
uv run current-filter.py --help
```

Expected: `--lunar` section shows sample line and field key.

- [ ] **Step 8: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add current-filter.py tests/test_current_filter.py
git commit \
  -m "feat: wire --lunar flag with format_report integration and help text" \
  -m "Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```
