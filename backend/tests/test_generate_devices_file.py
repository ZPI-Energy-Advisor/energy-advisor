import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
GENERATOR = SCRIPTS / "generate_devices_file.py"
VALIDATOR = SCRIPTS / "validate_devices_file.py"
DEMO_FILE = Path(__file__).parent / "fixtures" / "devices_demo_30d.json"
WEATHER = Path(__file__).parent / "fixtures" / "weather_demo_30d.json"
METER_PV_DEMO = Path(__file__).parent / "fixtures" / "meter_pv_demo_30d.csv"
SAMPLE_FILE = Path(__file__).resolve().parents[2] / "frontend" / "public" / "samples" / "devices-example.json"
PV = ["--with-pv", "--weather", WEATHER]
DEMO_ARGS = ["--start", "2026-10-01", "--days", "30", "--seed", "42", "--devices", "full", *PV]


def run_script(script: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *map(str, args)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def generate(path: Path, *args) -> bytes:
    result = run_script(GENERATOR, *args, "--out", path)
    assert result.returncode == 0, result.stderr
    return path.read_bytes()


@pytest.mark.parametrize("seed", [1, 7, 42])
@pytest.mark.parametrize("options", [["--devices", "standard"], ["--devices", "full", *PV]])
def test_generated_file_passes_validation(tmp_path, seed, options):
    path = tmp_path / "devices.json"
    generate(path, "--seed", seed, "--days", 14, *options)

    result = run_script(VALIDATOR, path)

    assert result.returncode == 0, result.stdout


def test_water_heater_is_optional_and_passes_validation(tmp_path):
    path = tmp_path / "devices.json"
    generate(path, "--days", 14, "--with-water-heater")

    result = run_script(VALIDATOR, path)
    document = json.loads(path.read_text(encoding="utf-8"))
    heater_actions = [action for action in document["energy_usage"] if action["device_id"] == "dev_wh_01"]

    assert result.returncode == 0, result.stdout
    assert {d["device_type"] for d in document["devices"]} >= {"water_heater"}
    assert len(heater_actions) >= 14  # rano i wieczorem, część może nie zmieścić się pod limitem


def _daily_pv_spread(document) -> float:
    """Średnie odchylenie dziennej produkcji od pogody: |(produkcja / nasłonecznienie) / mediana − 1|."""
    start, weather = _weather_hours()
    gti = weather["tilted_w_m2"]["35/0"]
    produced, sunlight = {}, {}
    for moment, kwh in _pv_by_quarter(document).items():
        produced[moment.date()] = produced.get(moment.date(), 0.0) + kwh
    for hour, value in enumerate(gti):
        day = (start + timedelta(hours=hour)).date()
        sunlight[day] = sunlight.get(day, 0.0) + (value or 0.0) * 6 / 1000
    ratios = sorted(produced[day] / sunlight[day] for day in produced if sunlight.get(day, 0) > 1)
    median = ratios[len(ratios) // 2]
    return sum(abs(ratio / median - 1) for ratio in ratios) / len(ratios)


def test_weather_error_spreads_daily_production_like_a_real_installation(tmp_path):
    plain = json.loads(generate(tmp_path / "plain.json", *DEMO_ARGS))
    realistic = json.loads(generate(tmp_path / "real.json", *DEMO_ARGS, "--weather-error"))

    assert _daily_pv_spread(plain) < 0.06
    assert 0.07 < _daily_pv_spread(realistic) < 0.35
    assert run_script(VALIDATOR, tmp_path / "real.json").returncode == 0


def test_ev_charges_per_week_limits_charging(tmp_path):
    def ev_charges(path, *options):
        document = json.loads(generate(path, "--days", 28, "--devices", "full", *options))
        return sum(action["device_id"] == "dev_ev_01" for action in document["energy_usage"])

    assert ev_charges(tmp_path / "rzadko.json", "--ev-charges-per-week", 2) <= 8
    assert ev_charges(tmp_path / "domyslnie.json") >= 12


def test_new_options_need_pv_and_an_ev(tmp_path):
    no_pv = run_script(GENERATOR, "--weather-error", "--out", tmp_path / "a.json")
    no_ev = run_script(GENERATOR, "--devices", "standard", "--ev-charges-per-week", 2, "--out", tmp_path / "b.json")

    assert no_pv.returncode != 0 and "--weather-error" in no_pv.stderr
    assert no_ev.returncode != 0 and "--ev-charges-per-week" in no_ev.stderr


def test_generator_respects_grid_limit(tmp_path):
    path = tmp_path / "devices.json"
    generate(path, "--devices", "full", *PV, "--max-grid-kw", 6)

    result = run_script(VALIDATOR, path, "--max-grid-kw", 6)

    assert result.returncode == 0, result.stdout


def test_same_seed_gives_identical_file(tmp_path):
    first = generate(tmp_path / "a.json", "--seed", 5, *PV)
    second = generate(tmp_path / "b.json", "--seed", 5, *PV)
    other_seed = generate(tmp_path / "c.json", "--seed", 6, *PV)

    assert first == second
    assert first != other_seed


def test_demo_file_matches_generator(tmp_path):
    # read_text zamienia CRLF na LF, więc test nie zależy od core.autocrlf w gicie.
    assert generate(tmp_path / "demo.json", *DEMO_ARGS).decode("utf-8") == DEMO_FILE.read_text(encoding="utf-8")


def test_meter_demo_with_pv_matches_generator(tmp_path):
    result = run_script(GENERATOR, *DEMO_ARGS, "--out", tmp_path / "dom.json", "--meter-out", tmp_path / "licznik.csv")

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "licznik.csv").read_text(encoding="utf-8") == METER_PV_DEMO.read_text(encoding="utf-8")


def _weather_hours():
    weather = json.loads(WEATHER.read_text(encoding="utf-8"))
    start = datetime.fromisoformat(weather["start"].replace("Z", "+00:00"))
    return start, weather


def _pv_by_quarter(document) -> dict:
    production = {}
    for action in document["energy_usage"]:
        if action["device_id"] == "dev_pv_01":
            start = datetime.fromisoformat(action["action_start"]).astimezone(timezone.utc)
            for index, value in enumerate(action["profile_kwh"]):
                production[start + timedelta(minutes=15 * index)] = -value
    return production


def test_pv_follows_historical_weather_with_some_randomness():
    start, weather = _weather_hours()
    gti = weather["tilted_w_m2"]["35/0"]
    production = _pv_by_quarter(json.loads(DEMO_FILE.read_text(encoding="utf-8")))
    hourly = {}
    for moment, kwh in production.items():
        hour = int((moment - start) / timedelta(hours=1))
        hourly[hour] = hourly.get(hour, 0.0) + kwh

    assert all(kwh == 0 for hour, kwh in hourly.items() if gti[hour] == 0)
    sunny = [kwh / (gti[hour] * 6 / 1000) for hour, kwh in hourly.items() if gti[hour] >= 300]
    assert 0.65 < min(sunny) and max(sunny) < 1.0
    assert max(sunny) - min(sunny) > 0.08


def test_pv_device_follows_panel_groups(tmp_path):
    path = tmp_path / "dom.json"
    weather = json.loads(WEATHER.read_text(encoding="utf-8"))
    weather["tilted_w_m2"]["20/-90"] = [value * 0.7 if value is not None else None for value in weather["tilted_w_m2"]["35/0"]]
    (tmp_path / "pogoda.json").write_text(json.dumps(weather), encoding="utf-8")
    generate(path, "--days", 3, "--with-pv", "--weather", tmp_path / "pogoda.json", "--pv-array", "4/35/0",
             "--pv-array", "2/20/-90", "--inverter-kw", 5)

    document = json.loads(path.read_text(encoding="utf-8"))
    device = next(d for d in document["devices"] if d["device_id"] == "dev_pv_01")

    assert (device["device_name"], device["max_power_kw"]) == ("Instalacja PV 6 kWp", 5)
    assert max(_pv_by_quarter(document).values()) <= 5 * 0.25


def test_pv_needs_weather_covering_the_period(tmp_path):
    no_weather = run_script(GENERATOR, "--with-pv", "--out", tmp_path / "a.json")
    outside = run_script(GENERATOR, *PV, "--start", "2026-11-15", "--out", tmp_path / "b.json")
    other_plane = run_script(GENERATOR, *PV, "--pv-array", "3/20/90", "--out", tmp_path / "c.json")
    bad_array = run_script(GENERATOR, *PV, "--pv-array", "6-35-0", "--out", tmp_path / "d.json")

    assert no_weather.returncode != 0 and "--weather" in no_weather.stderr
    assert outside.returncode != 0 and "nie obejmuje" in outside.stderr
    assert other_plane.returncode != 0 and "nie obejmuje" in other_plane.stderr
    assert bad_array.returncode != 0 and "KWP/NACHYLENIE/AZYMUT" in bad_array.stderr


def test_meter_with_pv_is_devices_minus_production():
    from app.parsers import parse_energy_file
    from app.services.calculation_service import CalculationService

    document = json.loads(DEMO_FILE.read_text(encoding="utf-8"))
    production = _pv_by_quarter(document)
    consumption = sum(action["energy_kwh"] for action in document["energy_usage"] if action["device_id"] != "dev_pv_01")
    with METER_PV_DEMO.open("rb") as handle:
        parsed = parse_energy_file(handle)
    readings = CalculationService.quarter_hour_readings(parsed)

    assert len(readings) == 30 * 96
    exported = sum(export for _, _, export in readings)
    assert exported > 50
    assert abs(sum(used for _, used, _ in readings) - exported - (consumption - sum(production.values()))) < 2


def test_demo_file_covers_dst_change():
    document = json.loads(DEMO_FILE.read_text(encoding="utf-8"))
    fridge_on_dst_day = next(
        action for action in document["energy_usage"]
        if action["device_id"] == "dev_fr_01" and action["action_start"].startswith("2026-10-25")
    )

    start = datetime.fromisoformat(fridge_on_dst_day["action_start"])
    end = datetime.fromisoformat(fridge_on_dst_day["action_end"])

    assert document["period"]["start"].endswith("+02:00")
    assert document["period"]["end"].endswith("+01:00")
    assert (start.isoformat()[-6:], end.isoformat()[-6:]) == ("+02:00", "+01:00")
    assert end - start == timedelta(hours=25)


def test_generator_uses_sample_file_device_catalog():
    sample = json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))
    demo = json.loads(DEMO_FILE.read_text(encoding="utf-8"))

    assert demo["devices"] == sample["devices"]


METER_DEMO = Path(__file__).parent / "fixtures" / "meter_demo_30d.csv"
DEVICES_FROM_METER_DEMO = Path(__file__).parent / "fixtures" / "devices_from_meter_demo_30d.json"
TAURON_HEADER = "Nr platnika;Nr punktu poboru energii;Rodzaj energii;Data i godzina;Strefa;Wartosc[kWh/kvar];Kompletnosc[%]"


def _quarters(path: Path) -> dict:
    from app.parsers import parse_energy_file
    from app.services.calculation_service import CalculationService

    with path.open("rb") as handle:
        return {moment: used for moment, used, _ in CalculationService.quarter_hour_readings(parse_energy_file(handle))}


def _hourly_meter(path: Path) -> Path:
    """Plik godzinowy z sum kwadransów pliku demo, w tym samym formacie Tauron."""
    hours = {}
    for moment, used in _quarters(METER_DEMO).items():
        end = moment.replace(minute=0) + timedelta(hours=1)
        hours[end] = hours.get(end, 0.0) + used
    lines = [TAURON_HEADER] + [
        f"1;2;Pobór energii czynnej;{end:%d.%m.%Y %H:%M};1;{f'{kwh:.3f}'.replace('.', ',')};100"
        for end, kwh in sorted(hours.items())
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_from_meter_demo_file_matches_generator(tmp_path):
    generated = generate(tmp_path / "dom.json", "--from-meter", METER_DEMO).decode("utf-8")

    assert generated == DEVICES_FROM_METER_DEMO.read_text(encoding="utf-8")


@pytest.mark.parametrize("hourly", [False, True], ids=["co-15-min", "godzinowy"])
def test_from_meter_devices_add_up_to_meter_in_every_quarter(tmp_path, hourly):
    meter = _hourly_meter(tmp_path / "licznik.csv") if hourly else METER_DEMO
    path = tmp_path / "dom.json"
    generate(path, "--from-meter", meter, "--seed", 7)

    validation = run_script(VALIDATOR, path)
    metered, devices = _quarters(meter), _quarters(path)
    document = json.loads(path.read_text(encoding="utf-8"))
    other = sum(action["energy_kwh"] for action in document["energy_usage"] if action["device_id"] == "dev_other_01")

    assert validation.returncode == 0, validation.stdout
    assert devices.keys() == metered.keys()
    assert max(abs(devices[moment] - metered[moment]) for moment in metered) <= 0.001
    assert other < 0.15 * sum(metered.values())
    assert {"dev_wm_01", "dev_dw_01", "dev_ev_01", "dev_hp_01"} <= {a["device_id"] for a in document["energy_usage"]}


def test_from_meter_same_seed_gives_identical_file(tmp_path):
    first = generate(tmp_path / "a.json", "--from-meter", METER_DEMO, "--seed", 3)
    second = generate(tmp_path / "b.json", "--from-meter", METER_DEMO, "--seed", 3)

    assert first == second


def test_from_meter_does_not_support_pv_yet(tmp_path):
    result = run_script(GENERATOR, "--from-meter", METER_DEMO, "--with-pv", "--out", tmp_path / "dom.json")

    assert result.returncode != 0
    assert "--with-pv" in result.stderr


def test_fetched_radiation_belongs_to_the_hour_that_ends_at_its_timestamp():
    sys.path.insert(0, str(SCRIPTS))
    from pv_weather import Array, fetch_weather

    asked = []

    def fake_archive(url, params):
        asked.append(params)
        return {"hourly": {
            "time": ["2026-10-01T10:00", "2026-10-01T11:00", "2026-10-01T12:00"],
            "global_tilted_irradiance": [100.0, 200.0, 300.0],
            "temperature_2m": [10.0, 11.0, 12.0],
        }}

    start = datetime(2026, 10, 1, 10, tzinfo=timezone.utc)
    weather = fetch_weather(51.1, 17.0, start, start + timedelta(hours=2), [Array(6, 35, 0), Array(1, 35, 0)], fake_archive)

    assert weather.tilted_w_m2 == {"35/0": [200.0, 300.0]}
    assert weather.temperature_c == [10.0, 11.0]
    assert len(asked) == 1 and (asked[0]["tilt"], asked[0]["azimuth"], asked[0]["timezone"]) == (35, 0, "GMT")


def test_frontend_samples_with_pv_are_the_demo_files():
    samples = SAMPLE_FILE.parent

    assert (samples / "przyklad-urzadzenia-pv-30-dni.json").read_text(encoding="utf-8") == DEMO_FILE.read_text(encoding="utf-8")
    assert (samples / "przyklad-licznik-pv-30-dni.csv").read_text(encoding="utf-8") == METER_PV_DEMO.read_text(encoding="utf-8")


def _flat_weather(snowfall: float, temperature: float):
    sys.path.insert(0, str(SCRIPTS))
    from pv_weather import Weather

    start = datetime(2026, 1, 9, 23, tzinfo=timezone.utc)
    hours = 72
    gti = [0.0] * 7 + [400.0] * 8 + [0.0] * 9
    return Weather(51.1, 17.0, start, [temperature] * hours, {"35/0": gti * 3}, [snowfall] + [0.0] * (hours - 1))


@pytest.mark.parametrize("snowfall, temperature, snowy", [(3.0, -2.0, True), (0.0, -2.0, False), (3.0, 4.0, False)])
def test_snow_covers_panels_only_after_snowfall_in_frost(snowfall, temperature, snowy):
    import random

    from pv_weather import Array, day_production

    weather = _flat_weather(snowfall, temperature)
    day_start = weather.start + timedelta(days=1)
    produced = sum(day_production(weather, [Array(6, 35, 0)], 6, day_start, day_start + timedelta(days=1), random.Random(1)))

    assert (produced < 0.35 * 6 * 0.4 * 8 * 0.83) == snowy


def test_weather_download_error_is_readable(tmp_path, monkeypatch):
    sys.path.insert(0, str(SCRIPTS))
    import urllib.error

    import pv_weather

    def offline(request, timeout):
        raise urllib.error.URLError("brak sieci")

    monkeypatch.setattr(pv_weather.urllib.request, "urlopen", offline)

    with pytest.raises(ValueError, match="Nie udało się pobrać pogody"):
        pv_weather.fetch_weather(51.1, 17.0, datetime(2026, 1, 1, tzinfo=timezone.utc),
                                 datetime(2026, 1, 2, tzinfo=timezone.utc), [pv_weather.Array(6, 35, 0)])


def test_weather_file_for_another_place_is_rejected(tmp_path):
    result = run_script(GENERATOR, *PV, "--latitude", 52.2, "--longitude", 21.0, "--out", tmp_path / "a.json")

    assert result.returncode != 0 and "jest dla" in result.stderr
