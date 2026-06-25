
ME:
You said:
> The morning ebb at GGB is strong (2–3 kts) but ends well before 10am in summer. What you're catching here is the second, weaker daily ebb — the mixed semidiurnal afternoon cycle. In July it's only 0.6–0.8 kts, which is mild at the Gate but not nothing. By October it's 1.5–2.5 kts, and by November it's touching 3 kts.

Why that seasonal variation? Unfortunately, by October the winds on the bay are much less reliable.

---

CLAUDE:

The seasonal variation in the diurnal inequality is driven by the interaction between the lunar and solar diurnal tidal constituents.

SF Bay tides are mixed semidiurnal: you get two unequal ebb/flood cycles per day. The *inequality* between them is primarily driven by the Moon's declination — when the Moon is well north or south of the equator ("tropic tides"), one of the two daily cycles is much larger than the other. When the Moon's declination is near zero ("equatorial tides"), both cycles are more similar. That cycles over roughly 27 days.

The *seasonal* variation layered on top of that comes from the solar diurnal constituent (P1, period ~24.07h) and its interaction with the lunisolar K1 (~23.93h). The Sun's declination follows its annual cycle, which shifts the relative phase of the solar diurnal forcing. In summer, the solar component tends to partially cancel the lunar diurnal inequality in one of the two daily cycles — which in SF's geometry happens to be the afternoon ebb. In fall and winter, those same constituents reinforce rather than cancel, so both daily ebbs grow more nearly equal and stronger.

It's worth noting you're seeing two things layered together in the output: (1) the seasonal envelope where fall/winter afternoon ebbs are intrinsically stronger, and (2) the fortnightly lunar declination cycle that creates the 2-3 day clusters of qualifying days within each month.

Your practical observation is exactly right — the tide and wind regimes are roughly anti-correlated seasonally on the Bay. The reliable afternoon westerly runs May through September; October is transitional; by November the wind is hit-or-miss. So the best tidal windows (October onward) coincide with the worst wind reliability.

September is probably the sweet spot in the data. Sep 6–9 has ebb speeds of 0.9–1.8 kts and ebb durations of 4h45m–6h10m, and the afternoon sea breeze is still reasonably dependable that early in the fall. The Sep 19–25 cluster is even stronger tidally but starts getting into the transitional period for wind.

---

ME:

Is the solar declination just the earth tilting on its axis, which produces the seasons, or is it something else? and the lunar declination?

---

CLAUDE:

Yes, solar declination is exactly that — the Earth's axial tilt (23.5°) means the Sun appears to move between 23.5°N and 23.5°S over the course of the year. Maximum declination at the solstices, zero at the equinoxes. Nothing more exotic than the seasons.

Lunar declination is the same concept — the Moon's angle above or below the celestial equator — but driven by the Moon's own orbital geometry. The Moon's orbit is tilted about 5° relative to the ecliptic (the plane of Earth's orbit around the Sun), and the ecliptic itself is tilted 23.5° to the equator. So the Moon's declination ranges roughly ±28.5° at its maximum (when the orbital tilt adds to the ecliptic tilt) and only ±18.5° at its minimum (when they partially subtract). That extreme cycles over about 18.6 years — the nodal cycle — which actually matters for long-range tide prediction. Within that, the Moon swings from its maximum north declination to maximum south and back every 27.2 days (the tropical month), which is what produces the fortnightly inequality pattern you see in the current data.

The tidal connection is fairly direct: when the Moon is over the equator, it pulls ocean water symmetrically and the two daily bulges are similar. When it's well north or south, the two bulges a location experiences as the Earth rotates are unequal — one passes directly under the Moon, the other is offset. That's the diurnal inequality.

---

ME:

Is there a good online resource that provides this information with illustrations?

---

CLAUDE:

NOAA's own tidal education pages are pretty good and obviously authoritative for the practical application. They cover the basics with diagrams:

[https://oceanservice.noaa.gov/education/tutorial_tides/welcome.html](https://oceanservice.noaa.gov/education/tutorial_tides/welcome.html)

For the harmonic constituent theory — the part about how you decompose tides into overlapping sine waves with names like K1 and P1 — the best illustrated treatment I've seen is in the manual for the XTide prediction software, written by David Flater. It's unusually clear for a technical document.

Beyond that I'd suggest searching for university oceanography course notes. The ones from UC San Diego (Scripps) and Oregon State tend to be well-illustrated and freely available. Search for something like "tide generating force declination oceanography lecture notes" and you'll find PDF slide decks that cover exactly the declination geometry with diagrams.

I should be honest that my knowledge of what's currently online is stale and I may be misremembering the XTide documentation specifically — I'd verify before spending time on it.


