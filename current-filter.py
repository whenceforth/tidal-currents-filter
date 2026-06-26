#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "holidays",
#   "skyfield",
# ]
# ///
"""
current-filter.py  –  Find favorable sailing windows in NOAA current prediction data.

Identifies days where the flood→ebb slack falls in a target time window,
giving favorable (neutral or ebbing) current conditions for an the East Bay→GGB run.

Station SFB1202: Golden Gate Bridge, 0.88 nm NE of
Units: knots, times in LST/LDT

Data obtained from https://tidesandcurrents.noaa.gov/noaacurrents/annual.html?id=SFB1202_17

Usage:
    uv run current-filter.py SFB1202_17_Annual_2026.txt
    uv run current-filter.py SFB1202_17_Annual_2026.txt --weekends-only
    uv run current-filter.py SFB1202_17_Annual_2026.txt --weekends-and-holidays-only
    uv run current-filter.py SFB1202_17_Annual_2026.txt --after 2026-07-01 --before 2026-09-30
    uv run current-filter.py SFB1202_17_Annual_2026.txt --window-open 09:30 --window-close 12:30
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import holidays

# ── Defaults (override with CLI flags) ────────────────────────────────────────

DEFAULT_WINDOW_OPEN  = time(10, 0)
DEFAULT_WINDOW_CLOSE = time(12, 0)
DEFAULT_EXTENDED     = time(13, 0)   # secondary: worth a look but not ideal
DEFAULT_MIN_EBB_HRS  = 2.0           # ignore trace ebbs

WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Event:
    dt:    datetime
    kind:  str           # 'slack' | 'ebb' | 'flood'
    speed: Optional[float]  # None for slack; negative for ebb, positive for flood


@dataclass
class Candidate:
    """
    A day where the flood→ebb transition falls in the target window.

    Structure:
        [prev_flood] → slack (in window) → ebb_peak → ebb_end → next_flood
                         ^                                 ^
                     qualifying                      useful metric:
                       slack                         how fast does flood rebuild?
    """
    slack:        Event           # the flood→ebb slack in target window
    ebb_peak:     Event           # ebb peak speed and timing
    ebb_end:      Event           # slack ending the ebb phase
    next_flood:   Optional[Event] # first flood peak after ebb (may be absent at EOF)
    tier:         str             # 'primary' | 'secondary'
    window_open:  time            # window parameters carried for scoring
    window_close: time

    @property
    def date(self) -> date:
        return self.slack.dt.date()

    @property
    def ebb_duration(self) -> timedelta:
        return self.ebb_end.dt - self.slack.dt

    @property
    def ebb_duration_hours(self) -> float:
        return self.ebb_duration.total_seconds() / 3600

    @property
    def ebb_speed(self) -> float:
        """Absolute ebb speed at peak, in knots."""
        return abs(self.ebb_peak.speed or 0.0)

    @property
    def time_to_next_flood(self) -> Optional[timedelta]:
        """Time from qualifying slack to the next flood peak."""
        if self.next_flood is None:
            return None
        return self.next_flood.dt - self.slack.dt

    def score(self) -> float:
        """
        Higher = better day.

        Components:
          ebb duration  – primary driver; longer window of good current
          ebb speed     – stronger ebb at GGB = more assist and cleaner conditions
          timing bonus  – earlier slack in window leaves more margin; 0→1 from close→open
        """
        open_mins  = self.window_open.hour  * 60 + self.window_open.minute
        close_mins = self.window_close.hour * 60 + self.window_close.minute
        slack_mins = self.slack.dt.hour     * 60 + self.slack.dt.minute
        timing_bonus = max(
            0.0,
            1.0 - (slack_mins - open_mins) / max(1, close_mins - open_mins)
        )
        s = (
            self.ebb_duration_hours * 0.5
            + self.ebb_speed        * 1.0
            + timing_bonus          * 0.3
        )
        if self.tier == 'secondary':
            s -= 2.0
        return s


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


# ── Parser ────────────────────────────────────────────────────────────────────

def parse_header_years(path: str) -> set[int]:
    """Extract covered years from the '# From:' header line."""
    with open(path) as fh:
        for line in fh:
            if not line.startswith('#'):
                break
            m = re.search(r'# From:\s+(\d{4})-\d{2}-\d{2}.*(\d{4})-\d{2}-\d{2}', line)
            if m:
                return set(range(int(m.group(1)), int(m.group(2)) + 1))
    return set()


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


def parse_events(path: str) -> list[Event]:
    """
    Parse NOAA annual current prediction file.

    Expected format (whitespace-delimited):
        Date       Time (LST_LDT)  Event      Speed (knots)
        2026-06-27 02:27           ebb           -2.2
        2026-06-27 07:04           slack            -
    """
    events: list[Event] = []
    with open(path) as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith('#') or line.startswith('Date'):
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            try:
                dt    = datetime.strptime(parts[0] + ' ' + parts[1], '%Y-%m-%d %H:%M')
                kind  = parts[2].lower()
                speed = None if parts[3] == '-' else float(parts[3])
            except (ValueError, IndexError) as exc:
                print(f"Warning: skipping line {lineno}: {exc}", file=sys.stderr)
                continue
            if kind not in ('slack', 'ebb', 'flood'):
                print(f"Warning: unknown event kind {kind!r} at line {lineno}", file=sys.stderr)
                continue
            events.append(Event(dt=dt, kind=kind, speed=speed))
    return events


# ── Finder ────────────────────────────────────────────────────────────────────

def find_candidates(
    events:       list[Event],
    window_open:  time  = DEFAULT_WINDOW_OPEN,
    window_close: time  = DEFAULT_WINDOW_CLOSE,
    extended:     time  = DEFAULT_EXTENDED,
    min_ebb_hrs:  float = DEFAULT_MIN_EBB_HRS,
) -> list[Candidate]:
    """
    Linear scan through event list.

    Qualifying slack criteria:
      1. kind == 'slack'
      2. time is within [window_open, extended]
      3. previous event is 'flood'  → confirms flood→ebb direction
      4. next event is 'ebb'        → confirms ebb follows
      5. ebb duration >= min_ebb_hrs

    Tier:
      primary   – slack ≤ window_close (10:00–12:00 by default)
      secondary – slack in (window_close, extended] (12:00–13:00 by default)
    """
    candidates: list[Candidate] = []
    n = len(events)

    for i, e in enumerate(events):
        if e.kind != 'slack':
            continue

        t = e.dt.time()
        if not (window_open <= t <= extended):
            continue

        # Need one event before and three after
        if i < 1 or i + 3 >= n:
            continue

        prev       = events[i - 1]
        nxt        = events[i + 1]
        ebb_end    = events[i + 2]
        next_flood = events[i + 3]

        # Direction check: must be flood→ebb, not ebb→flood
        if prev.kind != 'flood':
            continue
        if nxt.kind != 'ebb':
            continue

        # Sanity: sequence should be slack, ebb, slack, flood
        if ebb_end.kind != 'slack' or next_flood.kind != 'flood':
            continue

        ebb_dur_hrs = (ebb_end.dt - e.dt).total_seconds() / 3600
        if ebb_dur_hrs < min_ebb_hrs:
            continue

        tier = 'primary' if t <= window_close else 'secondary'
        candidates.append(Candidate(
            slack=e,
            ebb_peak=nxt,
            ebb_end=ebb_end,
            next_flood=next_flood,
            tier=tier,
            window_open=window_open,
            window_close=window_close,
        ))

    return candidates


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
    dists  = dist_arr.km  # numpy array of distances

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


# ── Formatter ─────────────────────────────────────────────────────────────────

def _hm(dt: datetime) -> str:
    return dt.strftime('%H:%M')

def _dur(td: timedelta) -> str:
    total_mins = int(td.total_seconds()) // 60
    h, m = divmod(total_mins, 60)
    return f'{h}h{m:02d}m'

def _weekday(d: date) -> str:
    return WEEKDAYS[d.weekday()]


def format_report(
    candidates:     list[Candidate],
    show_secondary: bool = True,
    us_holidays:    Optional[dict] = None,
    lunar_fn:       Optional[object] = None,   # Callable[[datetime], LunarInfo] | None
) -> None:
    """
    Tabular output grouped by month.

    Columns:
      ▶ = weekend   H = US holiday   ? = secondary window   date   day
      slack HH:MM   ebb -X.X kts @ HH:MM   end HH:MM   (Xh MMm)
      next flood +X.X @ HH:MM   [score]
    """
    visible = [c for c in candidates if show_secondary or c.tier == 'primary']
    if not visible:
        print('No candidates found.')
        return

    visible.sort(key=lambda c: c.date)

    current_month: Optional[str] = None
    for c in visible:
        month = c.date.strftime('%B %Y')
        if month != current_month:
            print(f'\n── {month} ─────────────────────────────────────────────────────')
            current_month = month

        is_weekend = c.date.weekday() >= 5
        hol_name   = us_holidays.get(c.date, '') if us_holidays else ''
        wkd_flag   = '▶' if is_weekend else ' '
        hol_flag   = 'H' if hol_name else ' '
        tier_flag  = '?' if c.tier == 'secondary' else ' '

        flood_str = (
            f"next flood +{c.next_flood.speed:.1f} @ {_hm(c.next_flood.dt)}"
            if c.next_flood else 'no next flood data'
        )

        flood_lag = (
            f"  [{_dur(c.time_to_next_flood)} to flood]"
            if c.time_to_next_flood else ''
        )

        hol_str = f'  ({hol_name})' if hol_name else ''

        print(
            f"{wkd_flag}{hol_flag}{tier_flag} {c.date}  {_weekday(c.date)}"
            f"  slack {_hm(c.slack.dt)}"
            f"  ebb -{c.ebb_speed:.1f} kts @ {_hm(c.ebb_peak.dt)}"
            f"  end {_hm(c.ebb_end.dt)}  ({_dur(c.ebb_duration)})"
            f"  {flood_str}{flood_lag}"
            f"  [{c.score():.1f}]{hol_str}"
        )
        if lunar_fn is not None:
            info = lunar_fn(c.slack.dt)
            decl_str = f'+{info.declination}°' if info.declination >= 0 else f'{info.declination}°'
            print(
                f'     {info.emoji} {info.elongation}°'
                f'  decl {decl_str}'
                f'  dist {info.distance_km // 1000}k km  {info.peri_apo}'
                f'  alt {info.altitude}° {info.azimuth_card}'
            )


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_time_arg(s: str) -> time:
    try:
        return datetime.strptime(s, '%H:%M').time()
    except ValueError:
        raise argparse.ArgumentTypeError(f'Expected HH:MM, got {s!r}')


def main() -> None:
    p = argparse.ArgumentParser(
        description='Find favorable the East Bay→GGB sailing windows from NOAA current data.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument('input',
                   help='NOAA current prediction .txt file')
    p.add_argument('--window-open',  type=parse_time_arg, default='10:00', metavar='HH:MM',
                   help='Primary window start')
    p.add_argument('--window-close', type=parse_time_arg, default='12:00', metavar='HH:MM',
                   help='Primary window end')
    p.add_argument('--extended',     type=parse_time_arg, default='13:00', metavar='HH:MM',
                   help='Secondary (marginal) window end')
    p.add_argument('--min-ebb',      type=float,          default=2.0,     metavar='HRS',
                   help='Minimum ebb duration in hours')
    p.add_argument('--no-secondary',  action='store_true',
                   help='Suppress secondary (extended window) candidates')
    p.add_argument('--after',  type=date.fromisoformat, metavar='YYYY-MM-DD',
                   help='Only show dates on or after this date')
    p.add_argument('--before', type=date.fromisoformat, metavar='YYYY-MM-DD',
                   help='Only show dates on or before this date')

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
            '  https://ssd.jpl.nasa.gov/ftp/eph/planets/bsp/de421.bsp'
        ),
    )

    day_filter = p.add_mutually_exclusive_group()
    day_filter.add_argument('--weekends-only', action='store_true',
                            help='Show only Saturdays and Sundays')
    day_filter.add_argument('--weekends-and-holidays-only', action='store_true',
                            help='Show only Saturdays, Sundays, and US federal holidays')

    args = p.parse_args()

    events = parse_events(args.input)
    if not events:
        sys.exit('No events parsed — check file format.')

    lunar_fn = None
    if args.lunar:
        from skyfield.api import Loader
        _EPHEM_URL = 'https://ssd.jpl.nasa.gov/ftp/eph/planets/bsp/de421.bsp'
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

    years = parse_header_years(args.input) or {e.dt.year for e in events}
    us_holidays_dict = holidays.US(years=years)

    candidates = find_candidates(
        events,
        window_open  = args.window_open,
        window_close = args.window_close,
        extended     = args.extended,
        min_ebb_hrs  = args.min_ebb,
    )

    if args.after:
        candidates = [c for c in candidates if c.date >= args.after]
    if args.before:
        candidates = [c for c in candidates if c.date <= args.before]
    if args.weekends_only:
        candidates = [c for c in candidates if c.date.weekday() >= 5]
    if args.weekends_and_holidays_only:
        candidates = [c for c in candidates
                      if c.date.weekday() >= 5 or c.date in us_holidays_dict]

    n_primary   = sum(1 for c in candidates if c.tier == 'primary')
    n_secondary = sum(1 for c in candidates if c.tier == 'secondary')

    print(f'Station data : {Path(args.input).name}')
    print(f'Slack window : {args.window_open.strftime("%H:%M")}–{args.window_close.strftime("%H:%M")}'
          f'  (secondary: –{args.extended.strftime("%H:%M")})')
    print(f'Min ebb      : {args.min_ebb:.1f}h')
    print(f'Candidates   : {n_primary} primary, {n_secondary} secondary')
    print('▶ = weekend   H = US holiday   ? = secondary window   [score = relative quality]')

    format_report(candidates, show_secondary=not args.no_secondary,
                  us_holidays=us_holidays_dict, lunar_fn=lunar_fn)
    print()


if __name__ == '__main__':
    main()
