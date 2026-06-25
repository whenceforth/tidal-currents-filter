#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "holidays",
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

    day_filter = p.add_mutually_exclusive_group()
    day_filter.add_argument('--weekends-only', action='store_true',
                            help='Show only Saturdays and Sundays')
    day_filter.add_argument('--weekends-and-holidays-only', action='store_true',
                            help='Show only Saturdays, Sundays, and US federal holidays')

    args = p.parse_args()

    events = parse_events(args.input)
    if not events:
        sys.exit('No events parsed — check file format.')

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
                  us_holidays=us_holidays_dict)
    print()


if __name__ == '__main__':
    main()
