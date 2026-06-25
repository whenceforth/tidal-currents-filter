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

## Data

Station **SFB1202_17** — Golden Gate Bridge, 0.88 nm NE. Data files for 2026–2028 are included in `data/`. Additional years can be downloaded from:

https://tidesandcurrents.noaa.gov/noaacurrents/annual.html?id=SFB1202_17

## Seasonal context

SF Bay is mixed semidiurnal (two unequal ebb/flood cycles per day). The qualifying slack is always the afternoon ebb — the weaker of the two daily cycles in summer. Ebb speeds run 0.6–1.0 kts in summer and build to 3+ kts by November. Good days cluster in 2–3 day runs at each neap cycle.

The tide and wind regimes are roughly anti-correlated: the reliable afternoon sea breeze runs May–September, while the strongest tidal windows are October onward. September is often the practical sweet spot.
