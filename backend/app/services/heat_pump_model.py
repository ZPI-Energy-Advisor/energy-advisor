"""Zużycie prądu przez pompę ciepła w zależności od temperatury na zewnątrz (ZP-119). Opis: docs/heat-pump.md.

Ciepło do ogrzania domu w dobie jest proporcjonalne do stopniodni grzania (Eurostat: 18 °C − średnia temperatura
doby, gdy średnia nie przekracza 15 °C; między 15 a 18 °C ogrzewanie maleje płynnie do zera), a prąd pompy to
ciepło podzielone przez COP. Stopniodni zależą też od temperatury w domu: próg 18 °C odpowiada ok. 21 °C w środku. COP pompy powietrznej
liczymy jak w When2Heat (Ruhnau, Hirth, Praktiknjo 2019, Scientific Data 6:189): kwadratowa funkcja różnicy
temperatur wody i powietrza, razy 0,85 na straty w praktyce (odszranianie, pompy obiegowe).

Moduł nie korzysta z bazy, więc liczy z niego też generator plików urządzeń.
"""

from dataclasses import dataclass

HDD_BASE_C = 18.0
HEATING_LIMIT_C = 15.0
# Temperatura w domu, której odpowiada próg 18 °C (zyski ciepła od ludzi, urządzeń i słońca dają resztę).
# Inna temperatura w domu przesuwa próg i granicę ogrzewania o tyle samo stopni.
DEFAULT_INDOOR_C = 21
COP_AIR = (6.08, -0.0941, 0.000464)
COP_CORRECTION = 0.85
MIN_LIFT_K = 15.0
HOT_WATER_SUPPLY_C = 50.0
FLOOR_HEATING_FROM_YEAR = 2000
# Ciepło użytkowe na ogrzewanie domu jednorodzinnego (kWh/m² rocznie) według roku budowy: środki zakresów
# z polskich zestawień (do 1966: 240–350, 1967–1985: 240–280, 1986–1992: 160–200, 1993–1997: 120–160,
# po 1998: 90–120) i założenia dla nowszych warunków technicznych (WT2008, WT2014/2017, WT2021).
HEAT_DEMAND_BY_YEAR = (
    (1966, 290.0),
    (1985, 260.0),
    (1992, 180.0),
    (1997, 140.0),
    (2008, 105.0),
    (2013, 85.0),
    (2020, 65.0),
)
NEWEST_HEAT_DEMAND = 45.0
# Zapotrzebowanie na m² w zestawieniach dotyczy domów wolnostojących. Mieszkanie w bloku ma sąsiadów za ścianami,
# nad i pod sobą, a szeregowiec dwie ściany wspólne, więc traci mniej ciepła na m² (przybliżenie typologii budynków).
PROPERTY_TYPE_DEMAND = {"apartment": 0.55, "terrace_house": 0.8}
# Typowy rok w Polsce, stopniodni według Eurostatu. Wrocław 2026 z archiwum Open-Meteo: ok. 3100.
REFERENCE_HDD = 3300.0
# Ciepła woda: tyle co w modelu bojlera (1,6 kWh ciepła na osobę na dobę) i ok. 20% strat zasobnika i cyrkulacji.
HOT_WATER_KWH_PER_PERSON = 1.6
HOT_WATER_LOSSES = 1.2


def heating_degree_days(mean_c: float, indoor_c: float = DEFAULT_INDOOR_C) -> float:
    """Stopniodni doby: poniżej granicy ogrzewania jak Eurostat (próg − średnia), a między granicą a progiem
    maleją płynnie do zera (parabola), żeby średnia 15,1 °C nie dawała nagle zera zamiast 3 stopniodni."""
    shift = indoor_c - DEFAULT_INDOOR_C
    base, limit = HDD_BASE_C + shift, HEATING_LIMIT_C + shift
    if mean_c <= limit:
        return base - mean_c
    if mean_c >= base:
        return 0.0
    return (base - limit) * ((base - mean_c) / (base - limit)) ** 2


def supply_temperature(outdoor_c: float, floor_heating: bool) -> float:
    """Temperatura wody grzewczej z krzywej grzewczej When2Heat: podłogówka 30 − 0,5·T, grzejniki 40 − T."""
    return 30.0 - 0.5 * outdoor_c if floor_heating else 40.0 - outdoor_c


def cop(outdoor_c: float, supply_c: float) -> float:
    lift = max(supply_c - outdoor_c, MIN_LIFT_K)
    a, b, c = COP_AIR
    return COP_CORRECTION * (a + b * lift + c * lift * lift)


def heating_cop(outdoor_c: float, floor_heating: bool) -> float:
    return cop(outdoor_c, supply_temperature(outdoor_c, floor_heating))


def hot_water_cop(outdoor_c: float) -> float:
    return cop(outdoor_c, HOT_WATER_SUPPLY_C)


def floor_heating_for(year_built: int | None) -> bool:
    """Bez danych o instalacji: nowsze domy zwykle mają podłogówkę, starsze grzejniki."""
    return year_built is not None and year_built >= FLOOR_HEATING_FROM_YEAR


def heat_demand_per_m2(year_built: int | None) -> float:
    if year_built is None:
        return HEAT_DEMAND_BY_YEAR[3][1]
    for last_year, demand in HEAT_DEMAND_BY_YEAR:
        if year_built <= last_year:
            return demand
    return NEWEST_HEAT_DEMAND


def building_heat_per_hdd(year_built: int | None, area_m2: float, property_type: str | None = None) -> float:
    """Ciepło na stopniodzień (kWh) z roku budowy, powierzchni i typu budynku: roczne zapotrzebowanie / stopniodni
    typowego roku."""
    factor = PROPERTY_TYPE_DEMAND.get(property_type or "", 1.0)
    return heat_demand_per_m2(year_built) * area_m2 * factor / REFERENCE_HDD


def hot_water_heat(residents: int | None) -> float:
    return (residents or 0) * HOT_WATER_KWH_PER_PERSON * HOT_WATER_LOSSES


@dataclass(frozen=True)
class HeatModel:
    """Dom z pompą ciepła: ciepło na stopniodzień, ciepło na wodę na dobę i rodzaj ogrzewania.

    `source`: "history" (dopasowany do zużycia pompy z plików), "building" (z profilu: rok budowy, metraż,
    liczba osób) albo "mixed" (ogrzewanie z profilu, a woda z plików, gdy w plikach jest za mało zimnych dni).
    """

    heat_per_hdd: float
    hot_water_kwh: float
    floor_heating: bool
    source: str
    days: int = 0
    heating_days: int = 0
    mape: float | None = None

    def day(self, mean_c: float, indoor_c: float = DEFAULT_INDOOR_C) -> "HeatingDay":
        hdd = heating_degree_days(mean_c, indoor_c)
        space_cop = heating_cop(mean_c, self.floor_heating)
        water_cop = hot_water_cop(mean_c)
        space_heat = self.heat_per_hdd * hdd
        return HeatingDay(
            mean_c=mean_c,
            hdd=hdd,
            heat_kwh=space_heat + self.hot_water_kwh,
            space_heat_kwh=space_heat,
            hot_water_heat_kwh=self.hot_water_kwh,
            cop=space_cop if hdd else water_cop,
            kwh=space_heat / space_cop + self.hot_water_kwh / water_cop,
            water_kwh=self.hot_water_kwh / water_cop,
            water_cop=water_cop,
        )

    def kwh(self, mean_c: float, indoor_c: float = DEFAULT_INDOOR_C) -> float:
        return self.day(mean_c, indoor_c).kwh


@dataclass(frozen=True)
class HeatingDay:
    mean_c: float
    hdd: float
    heat_kwh: float
    space_heat_kwh: float
    hot_water_heat_kwh: float
    cop: float
    kwh: float
    # Prąd na ciepłą wodę (część `kwh`) i sprawność pompy przy grzaniu wody.
    water_kwh: float = 0.0
    water_cop: float = 0.0


def building_model(year_built: int | None, area_m2: float | None, residents: int | None,
                   hot_water: bool = True, property_type: str | None = None) -> HeatModel | None:
    if not area_m2:
        return None
    return HeatModel(
        heat_per_hdd=building_heat_per_hdd(year_built, area_m2, property_type),
        hot_water_kwh=hot_water_heat(residents) if hot_water else 0.0,
        floor_heating=floor_heating_for(year_built),
        source="building",
    )


MIN_DAY_KWH = 0.2
MIN_FIT_DAYS = 10
MIN_HEATING_DAYS = 7
OUTLIER_SHARE = 0.5
OUTLIER_MIN_KWH = 2.0


def _regressors(mean_c: float, floor_heating: bool) -> tuple[float, float]:
    return heating_degree_days(mean_c) / heating_cop(mean_c, floor_heating), 1.0 / hot_water_cop(mean_c)


def _least_squares(rows: list[tuple[float, float, float]]) -> tuple[float, float]:
    """kWh = A·x1 + B·x2 bez wyrazu wolnego, A i B nieujemne (przy ujemnym zostaje druga zmienna sama)."""
    s11 = sum(x1 * x1 for x1, _, _ in rows)
    s22 = sum(x2 * x2 for _, x2, _ in rows)
    s12 = sum(x1 * x2 for x1, x2, _ in rows)
    s1y = sum(x1 * y for x1, _, y in rows)
    s2y = sum(x2 * y for _, x2, y in rows)
    det = s11 * s22 - s12 * s12
    if det > 1e-9:
        a = (s1y * s22 - s2y * s12) / det
        b = (s2y * s11 - s1y * s12) / det
        if a >= 0 and b >= 0:
            return a, b
    a_only = s1y / s11 if s11 else 0.0
    b_only = s2y / s22 if s22 else 0.0
    error_a = sum((y - a_only * x1) ** 2 for x1, _, y in rows)
    error_b = sum((y - b_only * x2) ** 2 for _, x2, y in rows)
    return (max(a_only, 0.0), 0.0) if error_a <= error_b else (0.0, max(b_only, 0.0))


def _hot_water_only(rows, heat_per_hdd: float) -> float:
    s22 = sum(x2 * x2 for _, x2, _ in rows)
    rest = sum(x2 * (y - heat_per_hdd * x1) for x1, x2, y in rows)
    return max(rest / s22, 0.0) if s22 else 0.0


def fit(days: list[tuple[float, float]], floor_heating: bool, fallback: HeatModel | None) -> HeatModel | None:
    """Model z historii: `days` to (średnia temperatura doby, kWh pompy z plików).

    Dni bez pracy pompy (np. wyjazd, wyłączona) pomijamy, a potem odrzucamy dni, które odbiegają od dopasowania
    o ponad połowę (i co najmniej 2 kWh). Gdy zimnych dni jest za mało, ogrzewanie bierzemy z profilu
    (`fallback`), a z plików tylko ciepłą wodę. Bez wystarczającej historii zwraca `fallback`.
    """
    rows = [(*_regressors(mean_c, floor_heating), kwh) for mean_c, kwh in days if kwh >= MIN_DAY_KWH]
    if len(rows) < MIN_FIT_DAYS:
        return fallback
    # Dzień z ogrzewaniem jak u Eurostatu: średnia do 15 °C. Dni 15–18 °C mają już tylko resztki stopniodni,
    # więc nie mówią, ile dom potrzebuje na stopniodzień (x1 maleje z temperaturą, więc wystarczy próg x1).
    heating_x1 = _regressors(HEATING_LIMIT_C, floor_heating)[0] - 1e-9
    heating_rows = [row for row in rows if row[0] >= heating_x1]
    if len(heating_rows) >= MIN_HEATING_DAYS:
        a, b = _least_squares(rows)
        kept = [row for row in rows if abs(row[2] - (a * row[0] + b * row[1])) <= max(OUTLIER_SHARE * (a * row[0] + b * row[1]), OUTLIER_MIN_KWH)]
        if len(kept) >= MIN_FIT_DAYS and sum(1 for row in kept if row[0] >= heating_x1) >= MIN_HEATING_DAYS:
            rows = kept
            a, b = _least_squares(rows)
        source = "history"
    elif fallback is not None:
        a = fallback.heat_per_hdd
        b = _hot_water_only(rows, a)
        source = "mixed"
    else:
        return None
    return HeatModel(
        heat_per_hdd=a,
        hot_water_kwh=b,
        floor_heating=floor_heating,
        source=source,
        days=len(rows),
        heating_days=sum(1 for row in rows if row[0] >= heating_x1),
        mape=_leave_one_out_mape(rows) if source == "history" else None,
    )


def _leave_one_out_mape(rows: list[tuple[float, float, float]]) -> float | None:
    errors = []
    for index, (x1, x2, kwh) in enumerate(rows):
        if x1 <= 0 or kwh < 1.0:
            continue
        a, b = _least_squares(rows[:index] + rows[index + 1:])
        errors.append(abs(a * x1 + b * x2 - kwh) / kwh)
    return round(sum(errors) / len(errors), 3) if errors else None
