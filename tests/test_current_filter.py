import io
import sys
import textwrap
import tempfile
import os
import pytest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest.mock import patch
import importlib.util

# Allow importing from the script directly
sys.path.insert(0, str(Path(__file__).parent.parent))

# current-filter.py has a hyphen so we must import via importlib

def _load_script():
    spec = importlib.util.spec_from_file_location(
        "current_filter",
        Path(__file__).parent.parent / "current-filter.py",
    )
    mod = importlib.util.module_from_spec(spec)
    # Register the module so dataclasses work correctly
    sys.modules["current_filter"] = mod
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


# ── Integration test (skipped if ephemeris absent) ────────────────────────────

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


# ── format_report with lunar ──────────────────────────────────────────────────

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
