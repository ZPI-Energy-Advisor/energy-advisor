"""Dom jako magazyn ciepła (ogrzewanie pompą ciepła w planie): temperatura w domu kwadrans po kwadransie.

Opis: docs/heat-pump.md, „Plan: temperatura w domu”. Moduł nie korzysta z bazy.

- Straty ciepła domu (kW na stopień różnicy temperatur) wynikają z modelu pompy (`heat_pump_model`): ciepło na
  stopniodzień / 24 h. Próg stopniodni 18 °C przy 21 °C w domu oznacza, że ludzie, urządzenia i słońce dają
  równowartość 3 °C (`GAINS_K`), więc dom traci `straty × (w domu − na dworze − 3)` kW.
- Pojemność cieplna domu (kWh na stopień): ile ciepła trzeba, żeby ogrzać dom o 1 °C. Z plików jej nie poznamy
  (zużycie jest dobowe), więc przyjmujemy klasy z EN ISO 13790 według typu budynku: mieszkanie w bloku ciężkie
  (beton), dom i szeregowiec średnie (mur), domek letniskowy lekki. Bez metrażu: stała czasowa 40 h.
- Pompa grzeje w kwadransie z mocą 0, połowy albo całej (pompy inwerterowe modulują moc), a ciepła daje COP razy
  więcej niż prądu; COP zależy od temperatury na dworze w tym kwadransie.

Bez planu dom grzeje termostat: co kwadrans tyle, żeby wrócić do ustawionej temperatury (`thermostat`). Plan
wybiera najtańsze kwadranse (`optimize`, programowanie dynamiczne jak w `water_heater`), tak żeby temperatura
w domu nie spadła poniżej ustawionej − 1 °C i nie przekroczyła ustawionej + 1 °C, a na koniec doby wróciła do
ustawionej (dom nie „pożycza” ciepła z kolejnego dnia).
"""

from dataclasses import dataclass

from app.services.heat_pump_model import DEFAULT_INDOOR_C, HDD_BASE_C, HeatModel, heating_cop

SLOT_HOURS = 0.25
COMFORT_BAND_C = 1.0
GAINS_K = DEFAULT_INDOOR_C - HDD_BASE_C
LEVELS = (0.0, 0.5, 1.0)
TEMP_STEP_C = 0.05
SHORTFALL_PENALTY = 100.0
OVER_LIMIT_PENALTY = 10.0
# Pojemność cieplna na m² (kWh/K): EN ISO 13790, klasy średnia 165 kJ/(m²·K), ciężka 260, lekka 110.
MEDIUM_CAPACITY = 165 / 3600
CAPACITY_KWH_PER_M2_K = {
    "apartment": 260 / 3600,
    "single_family_house": MEDIUM_CAPACITY,
    "terrace_house": MEDIUM_CAPACITY,
    "recreational_cottage": 110 / 3600,
}
DEFAULT_TIME_CONSTANT_H = 40.0


def house_capacity(property_type: str | None, area_m2: float | None, loss_kw_per_k: float) -> float:
    """Pojemność cieplna domu (kWh/K) z typu budynku i metrażu; bez metrażu stała czasowa `DEFAULT_TIME_CONSTANT_H`."""
    if area_m2:
        return CAPACITY_KWH_PER_M2_K.get(property_type or "", MEDIUM_CAPACITY) * area_m2
    return DEFAULT_TIME_CONSTANT_H * loss_kw_per_k


@dataclass(frozen=True)
class House:
    loss_kw_per_k: float
    capacity_kwh_per_k: float
    floor_heating: bool
    indoor_c: float

    @classmethod
    def of(cls, model: HeatModel, property_type: str | None, area_m2: float | None, indoor_c: float,
           share: float = 1.0) -> "House":
        """Dom (albo jego część ogrzewana tą pompą, `share`) z modelu pompy i profilu."""
        loss = model.heat_per_hdd / 24
        return cls(
            loss_kw_per_k=loss * share,
            capacity_kwh_per_k=house_capacity(property_type, area_m2, loss) * share,
            floor_heating=model.floor_heating,
            indoor_c=indoor_c,
        )

    @property
    def low(self) -> float:
        return self.indoor_c - COMFORT_BAND_C

    @property
    def high(self) -> float:
        return self.indoor_c + COMFORT_BAND_C

    @property
    def time_constant_h(self) -> float:
        return self.capacity_kwh_per_k / self.loss_kw_per_k if self.loss_kw_per_k else 0.0

    def loss_kwh(self, indoor: float, outdoor: float) -> float:
        """Ciepło, które dom traci w kwadransie (ujemne, gdy zyski są większe od strat, np. ciepły dzień)."""
        return self.loss_kw_per_k * (indoor - outdoor - GAINS_K) * SLOT_HOURS

    def step(self, indoor: float, outdoor: float, heat_kwh: float) -> float:
        return indoor + (heat_kwh - self.loss_kwh(indoor, outdoor)) / self.capacity_kwh_per_k

    def cooling_per_hour(self, outdoor: float) -> float:
        """O ile °C na godzinę stygnie dom bez grzania przy ustawionej temperaturze i tej temperaturze na dworze."""
        return max(self.loss_kwh(self.indoor_c, outdoor), 0.0) * 4 / self.capacity_kwh_per_k


@dataclass(frozen=True)
class HouseHeating:
    # Prąd pompy w każdym kwadransie (kWh) i temperatura w domu na końcu kwadransu.
    kwh: list[float]
    temps: list[float]
    cost: float
    heat_kwh: float
    # Największe niedogrzanie poniżej ustawionej − 1 °C (°C); 0, gdy temperatura zawsze w zakresie.
    shortfall: float


def _simulate(house: House, outdoor: list[float], prices: list[float], kwh: list[float], power_kw: float) -> HouseHeating:
    temps, temp, cost, heat, shortfall = [], house.indoor_c, 0.0, 0.0, 0.0
    for slot, electricity in enumerate(kwh):
        cop = heating_cop(outdoor[slot], house.floor_heating)
        temp = house.step(temp, outdoor[slot], electricity * cop)
        temps.append(round(temp, 2))
        cost += prices[slot] * electricity
        heat += electricity * cop
        shortfall = max(shortfall, house.low - temp)
    return HouseHeating(kwh=kwh, temps=temps, cost=cost, heat_kwh=heat, shortfall=round(max(shortfall, 0.0), 1))


def thermostat(house: House, outdoor: list[float], prices: list[float], power_kw: float,
               blocked: set[int] | None = None) -> HouseHeating:
    """Bez planu: co kwadrans tyle ciepła, żeby wrócić do ustawionej temperatury (najwyżej pełna moc pompy).
    W kwadransach `blocked` pompa grzeje wodę, więc dom nie dostaje nic."""
    blocked = blocked or set()
    cap = power_kw * SLOT_HOURS
    kwh, temp = [], house.indoor_c
    for slot, value in enumerate(outdoor):
        cop = heating_cop(value, house.floor_heating)
        need = house.loss_kwh(temp, value) + (house.indoor_c - temp) * house.capacity_kwh_per_k
        electricity = 0.0 if slot in blocked else min(max(need, 0.0) / cop, cap)
        kwh.append(electricity)
        temp = house.step(temp, value, electricity * cop)
    return _simulate(house, outdoor, prices, kwh, power_kw)


def optimize(house: House, outdoor: list[float], prices: list[float], power_kw: float,
             allowed: list[bool] | None = None, blocked: set[int] | None = None) -> HouseHeating:
    """Najtańsze grzanie przy temperaturze w domu w zakresie ustawiona ± 1 °C (programowanie dynamiczne).

    Stany to temperatura w domu co `TEMP_STEP_C` (zostaje tańszy, z dokładną temperaturą). `allowed`: kwadranse
    w limicie przyłącza (poza nimi kara `OVER_LIMIT_PENALTY`, miękko, jak w bojlerze). `blocked`: kwadranse grzania
    wody, w których pompa nie grzeje domu. Ciepło ważniejsze od limitu, a limit od ceny."""
    blocked = blocked or set()
    cap = power_kw * SLOT_HOURS
    start = house.indoor_c
    states: dict[int, tuple[float, float]] = {round(start / TEMP_STEP_C): (0.0, start)}
    choices: list[dict[int, tuple[int, float]]] = []
    for slot, value in enumerate(outdoor):
        cop = heating_cop(value, house.floor_heating)
        new_states: dict[int, tuple[float, float]] = {}
        choice: dict[int, tuple[int, float]] = {}
        for key, (base, temp) in states.items():
            for level in LEVELS:
                if level and slot in blocked:
                    continue
                electricity = level * cap
                after = house.step(temp, value, electricity * cop)
                if level and after > house.high:
                    continue
                total = base + prices[slot] * electricity + SHORTFALL_PENALTY * max(house.low - after, 0.0)
                if level and allowed is not None and not allowed[slot]:
                    total += OVER_LIMIT_PENALTY
                bucket = round(after / TEMP_STEP_C)
                if total < new_states.get(bucket, (float("inf"), 0.0))[0] - 1e-9:
                    new_states[bucket], choice[bucket] = (total, after), (key, electricity)
        choices.append(choice)
        states = new_states

    # Na koniec doby dom wraca do ustawionej temperatury: kolejny dzień zaczyna od tego samego.
    def final(key: int) -> tuple[float, int]:
        cost, temp = states[key]
        return cost + SHORTFALL_PENALTY * max(start - TEMP_STEP_C - temp, 0.0), key

    key = min(final(value) for value in states)[1]
    kwh = [0.0] * len(outdoor)
    for slot in range(len(outdoor) - 1, -1, -1):
        key, kwh[slot] = choices[slot][key]
    return _simulate(house, outdoor, prices, kwh, power_kw)
