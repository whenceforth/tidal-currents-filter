# tide-filter

Find favorable days to sail from the East Bay to the Golden Gate Bridge, based on NOAA tidal current predictions.

A "good day" is one where the flood→ebb slack falls in a target morning window (default 10:00–12:00), leaving a long ebb current to carry the boat out to the Gate. The script reads NOAA annual current prediction files and scores each qualifying day by ebb duration, ebb peak speed, and how early in the window the slack falls.

## Usage

```bash
uv run current-filter.py data/SFB1202_17_Annual_2026.txt
uv run current-filter.py data/SFB1202_17_Annual_2026.txt --weekends-and-holidays-only
uv run current-filter.py data/SFB1202_17_Annual_2026.txt --after 2026-07-01 --before 2026-09-30
uv run current-filter.py data/SFB1202_17_Annual_2026.txt --window-open 09:30 --window-close 12:30
```

No setup required. `uv run` installs the `holidays` dependency automatically via the PEP 723 inline script metadata.

## Output

```
▶   2026-08-08  Sat  slack 10:41  ebb -0.8 kts @ 12:52  end 14:49  (4h08m)  next flood +2.5 @ 18:44  [8h03m to flood]  [3.1]
▶   2026-08-09  Sun  slack 11:33  ebb -1.0 kts @ 13:47  end 16:04  (4h31m)  next flood +2.7 @ 19:46  [8h13m to flood]  [3.3]
 H  2026-09-07  Mon  slack 11:07  ebb -1.2 kts @ 13:38  end 16:27  (5h20m)  next flood +2.5 @ 19:36  [8h29m to flood]  [4.0]  (Labor Day)
```

Flag columns before the date:
- `▶` — weekend
- `H` — weekday US federal holiday (holiday name shown at end of line)
- `?` — secondary window candidate (slack falls between `--window-close` and `--extended`)

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--window-open` | `10:00` | Start of primary slack window |
| `--window-close` | `12:00` | End of primary window / start of secondary |
| `--extended` | `13:00` | End of secondary (marginal) window |
| `--min-ebb` | `2.0` | Minimum ebb duration in hours |
| `--weekends-only` | — | Show only Sat/Sun |
| `--weekends-and-holidays-only` | — | Show only Sat/Sun and US federal holidays |
| `--no-secondary` | — | Suppress secondary-window candidates |
| `--after` | — | Only show dates on or after `YYYY-MM-DD` |
| `--before` | — | Only show dates on or before `YYYY-MM-DD` |

## Lunar data (`--lunar`)

```bash
uv run current-filter.py data/SFB1202_17_Annual_2026.txt --lunar
```

Prints a moon data sub-line under each candidate. On first use, `data/de421.bsp` (~13 MB, JPL planetary ephemeris, valid through 2050) is downloaded automatically.

```
▶   2026-10-18  Sun  slack 10:42  ebb -2.1 kts @ 13:30  end 17:15  (6h33m)  next flood +2.8 @ 19:45  [4h03m to flood]  [4.2]
     🌔 108.0°  decl +18.4°  dist 382k km  peri in 3d  alt 41.0° WSW
```

### Fields

**`🌔 108.0°` — phase and elongation from the sun**
Elongation is the moon's angular distance from the sun: 0° = new moon, 180° = full moon. Near 0° or 180° (within ~45°) you're in a spring tide period — stronger ebbs, more current assist at the Gate, bigger tidal range. Near 90° or 270° (quarter moons) you're in neap tides — milder ebbs, calmer conditions.

**`decl +18.4°` — lunar declination**
The moon's angle north (+) or south (−) of the equator. This is the dominant driver of SF Bay's *diurnal inequality* — the unevenness between the two daily tidal cycles. When the moon is far from the equator (high declination), the two daily ebbs become very unequal: the afternoon ebb this script selects is the *weaker* one, so ebb speeds are mild. When the moon is near the equator (declination near 0°), both daily cycles become more equal and the afternoon ebb is stronger. Declination cycles through its full ±28° range roughly every 27 days.

**`dist 382k km  peri in 3d` — distance and perigee/apogee trajectory**
The moon's distance from Earth varies from ~356,000 km (perigee, closest) to ~406,000 km (apogee, farthest). Closer = stronger gravitational pull = bigger tidal range = stronger ebbs. "peri in 3d" means tides are currently strengthening toward a perigee; "apo 2d ago" means you're past the weakest point and recovering. The perigee/apogee cycle repeats roughly every 27.5 days, offset from the ~29.5-day phase cycle, so the two reinforce unpredictably — a perigee coinciding with a spring tide (new or full moon) produces the strongest conditions of all.

**`alt 41.0° WSW` — moon altitude and bearing at slack time**
The moon's elevation above the horizon and compass direction at the moment of the qualifying slack. Connects the abstract tidal numbers to something you can look up and see. Negative altitude means the moon has already set (or hasn't risen) at departure time.

## Data

Station **SFB1202_17** — Golden Gate Bridge, 0.88 nm NE. Data files for 2026–2028 are included in `data/`. Additional years can be downloaded from:

https://tidesandcurrents.noaa.gov/noaacurrents/annual.html?id=SFB1202_17

## Seasonal context

SF Bay is mixed semidiurnal (two unequal ebb/flood cycles per day). The qualifying slack is always the afternoon ebb — the weaker of the two daily cycles in summer. Ebb speeds run 0.6–1.0 kts in summer and build to 3+ kts by November. Good days cluster in 2–3 day runs at each neap cycle.

The tide and wind regimes are roughly anti-correlated: the reliable afternoon sea breeze runs May–September, while the strongest tidal windows are October onward. September is often the practical sweet spot.
