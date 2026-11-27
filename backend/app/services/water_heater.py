"""Bojler jako magazyn ciepła (ZP-112): temperatura wody kwadrans po kwadransie i najtańsze grzanie.

Model (czysty, bez bazy), liczony dla doby planu (00:00–24:00):
- grzałka pracuje pełną mocą przez cały kwadrans albo wcale; kwadrans grzania podnosi temperaturę
  o `kWh / (litry × 1,163 Wh/(l·K))`, np. 0,5 kWh w 80 l to ok. +5,4°C;
- pobór ciepłej wody (prysznice, zmywanie rąk) obniża temperaturę tak samo; rozkładamy go na 2 h po
  każdej godzinie „woda gotowa na”;
- woda stygnie proporcjonalnie do różnicy z temperaturą pomieszczenia (`ROOM_TEMP`): przy 55°C ok.
  0,5°C na godzinę, przy 75°C o ok. 60% szybciej, przy 45°C wolniej. Dlatego grzanie na zapas
  kosztuje większe straty i opłaca się tylko przy wyraźnie tańszym prądzie;
- na godziny „woda gotowa na” co najmniej `READY_TEMP`, poza nimi nigdy poniżej `MIN_TEMP`,
  nigdy powyżej `MAX_TEMP` (termostat bezpieczeństwa).

Temperatura o północy:
- bez planu bojler to zwykły termostat: grzeje, gdy woda ma mniej niż `READY_TEMP`, więc o północy
  ma ok. `READY_TEMP` (`THERMOSTAT_START_TEMP`);
- z planem w nocy wystarczy niewiele ponad `MIN_TEMP`: po wieczornym myciu woda może stygnąć i zostać
  dogrzana w tanich godzinach przed rankiem, więc plan zaczyna dobę od `PLAN_START_TEMP`.
Obie wersje muszą skończyć dobę z co najmniej taką temperaturą, z jaką ją zaczęły: każdy dzień wygląda
tak samo i nikt nie „pożycza” ciepła z kolejnego dnia, więc koszty są porównywalne.

Plan wybiera kwadranse grzania programowaniem dynamicznym po (kwadrans, temperatura): stany o tej samej
temperaturze z dokładnością do 0,1°C łączymy (zostaje tańszy, z dokładną temperaturą), więc stanów jest
najwyżej 96 × ok. 750 i wynik liczy się w ułamku sekundy. Temperatury w wyniku liczy dokładna symulacja. Gdy grzałka nie nadąża (za mała moc albo zbiornik), plan minimalizuje niedogrzanie
i zwraca je w `shortfall`.
"""

from dataclasses import dataclass

WATER_KWH_PER_LITER_KELVIN = 1.163 / 1000
HOT_WATER_KWH_PER_PERSON = 1.6
MIN_TEMP = 40.0
READY_TEMP = 55.0
MAX_TEMP = 75.0
ROOM_TEMP = 22.0
# Stygnięcie: 0,5°C na godzinę przy 55°C, proporcjonalnie do różnicy z temperaturą pomieszczenia.
LOSS_C_PER_HOUR_AT_READY = 0.5
LOSS_RATE_PER_HOUR = LOSS_C_PER_HOUR_AT_READY / (READY_TEMP - ROOM_TEMP)
THERMOSTAT_START_TEMP = READY_TEMP
PLAN_START_TEMP = 45.0
DRAW_SLOTS = 8
SLOT_HOURS = 0.25
# Kara za każdy °C poniżej wymaganej temperatury w kwadransie: dużo większa niż koszt grzania.
SHORTFALL_PENALTY = 100.0
# Kara za kwadrans grzania ponad limit przyłącza (zł): dużo większa niż cena prądu (ok. 0,5 zł za kwadrans),
# więc plan omija takie kwadranse, kiedy tylko może, ale dużo mniejsza niż kara za zimną wodę (kwadrans
# grzania to kilka °C, czyli kilkaset zł kary), więc ciepła woda jest ważniejsza niż limit.
OVER_LIMIT_PENALTY = 10.0
# Pobór z historii nie może wyjść ujemny ani absurdalnie mały (np. bojler wyłączony na urlopie).
MIN_DAILY_DRAW_KWH = 0.5


@dataclass(frozen=True)
class TankLimits:
    """Temperatury zbiornika: nigdy poniżej `min_temp`, na godziny gotowości `ready_temp`, nigdy powyżej
    `max_temp`, a plan zaczyna dobę od `plan_start_temp`. Bojler z grzałką ma domyślne; zasobnik pompy ciepła
    niższe, bo pompa grzeje wodę zwykle najwyżej do ok. 55 °C."""

    min_temp: float = MIN_TEMP
    ready_temp: float = READY_TEMP
    max_temp: float = MAX_TEMP
    plan_start_temp: float = PLAN_START_TEMP


BOILER = TankLimits()


def default_tank_liters(residents: int) -> int:
    """Typowy zbiornik dla liczby osób: 80 l dla 1–2, 120 l dla 3–4, 150 l od 5."""
    if residents <= 2:
        return 80
    if residents <= 4:
        return 120
    return 150


@dataclass(frozen=True)
class Tank:
    liters: float
    power_kw: float

    @property
    def slot_kwh(self) -> float:
        return self.power_kw * SLOT_HOURS

    def degrees(self, kwh: float) -> float:
        return kwh / (self.liters * WATER_KWH_PER_LITER_KELVIN)

    def kwh(self, degrees: float) -> float:
        return degrees * self.liters * WATER_KWH_PER_LITER_KELVIN


@dataclass(frozen=True)
class Heating:
    on: list[bool]
    # Temperatura na końcu każdego kwadransu.
    temps: list[float]
    cost: float
    # Największe niedogrzanie względem wymagań (°C); 0, gdy wszystko spełnione.
    shortfall: float
    start_temp: float


def daily_draw_kwh(residents: int) -> float:
    """Ciepła woda na dobę z liczby osób, gdy nie ma historii bojlera."""
    return residents * HOT_WATER_KWH_PER_PERSON


def thermostat_loss_kwh(liters: float) -> float:
    """Straty postojowe na dobę przy wodzie trzymanej przez termostat na `READY_TEMP`."""
    return Tank(liters=liters, power_kw=1.0).kwh(LOSS_C_PER_HOUR_AT_READY * 24)


def draw_from_history(daily_kwh: float, liters: float) -> float:
    """Ciepła woda na dobę z historii bojlera: plik pokazuje zużycie bojlera z termostatem, czyli pobór
    i straty przy `READY_TEMP`, więc pobór to energia z pliku minus te straty."""
    return max(daily_kwh - thermostat_loss_kwh(liters), MIN_DAILY_DRAW_KWH)


def draws(slots: int, ready_indices: list[int], daily_kwh: float) -> list[float]:
    """Pobór ciepłej wody w kwadransach doby: po równo w 2 h od każdej godziny gotowości.

    Pobór, który wypada po północy (godzina gotowości po 22:00, np. 23:00 albo 00:00), należy do kolejnej
    doby i tu go pomijamy. Wciśnięty w ostatni kwadrans dawałby nierealny spadek temperatury naraz
    (przy 00:00 cały 2-godzinny pobór w 15 minut). Gotowość na tę godzinę i tak sprawdza `minimums`:
    o północy woda musi mieć `READY_TEMP`."""
    result = [0.0] * slots
    if not ready_indices:
        return result
    share = daily_kwh / len(ready_indices) / DRAW_SLOTS
    for index in ready_indices:
        for slot in range(index, min(index + DRAW_SLOTS, slots)):
            result[slot] += share
    return result


def minimums(slots: int, ready_indices: list[int], end_temp: float, limits: TankLimits = BOILER) -> list[float]:
    """Wymagana temperatura na końcu kwadransu: gotowość tuż przed godziną, na koniec doby `end_temp`."""
    result = [limits.min_temp] * slots
    for index in ready_indices:
        if 0 < index <= slots:
            result[index - 1] = max(result[index - 1], limits.ready_temp)
    result[-1] = max(result[-1], end_temp)
    return result


def step(tank: Tank, temp: float, active: bool, draw_kwh: float) -> float:
    """Temperatura po kwadransie: grzanie, pobór i stygnięcie zależne od temperatury."""
    loss = LOSS_RATE_PER_HOUR * (temp - ROOM_TEMP) * SLOT_HOURS
    gained = tank.degrees((tank.slot_kwh if active else 0.0) - draw_kwh)
    return temp + gained - loss


def simulate(tank: Tank, start_temp: float, on: list[bool], draw: list[float], prices: list[float],
             required: list[float]) -> Heating:
    temps, temp, cost, shortfall = [], start_temp, 0.0, 0.0
    for slot, active in enumerate(on):
        temp = step(tank, temp, active, draw[slot])
        temps.append(round(temp, 2))
        cost += prices[slot] * tank.slot_kwh if active else 0.0
        shortfall = max(shortfall, required[slot] - temp)
    return Heating(on=on, temps=temps, cost=cost, shortfall=round(max(shortfall, 0.0), 1), start_temp=start_temp)


def thermostat(tank: Tank, draw: list[float], prices: list[float], ready_indices: list[int],
               limits: TankLimits = BOILER) -> Heating:
    """Bez planu: od temperatury gotowości grzeje cały kwadrans, gdy woda ma mniej niż `ready_temp`."""
    start = limits.ready_temp
    on, temp = [], start
    for slot in range(len(draw)):
        active = temp < limits.ready_temp and step(tank, temp, True, draw[slot]) <= limits.max_temp
        on.append(active)
        temp = step(tank, temp, active, draw[slot])
    return simulate(tank, start, on, draw, prices, minimums(len(draw), ready_indices, start, limits))


def optimize(tank: Tank, draw: list[float], prices: list[float], ready_indices: list[int],
             start_temp: float | None = None, allowed: list[bool] | None = None,
             limits: TankLimits = BOILER) -> Heating:
    """Najtańsze kwadranse grzania spełniające wymagania temperatury (programowanie dynamiczne).

    `allowed`: kwadranse, w których grzałka mieści się w limicie przyłącza obok reszty domu; None to wszystkie.
    Limit jest miękki: grzanie w pozostałych kwadransach kosztuje `OVER_LIMIT_PENALTY`. Kolejność ważności to
    ciepła woda, potem limit, potem cena: plan grzeje ponad limit tylko wtedy, gdy inaczej woda byłaby
    za zimna, i tylko w tylu kwadransach, ile trzeba. `shortfall` zostaje więc tylko wtedy, gdy grzałka
    fizycznie nie nadąża (za mała moc albo zbiornik)."""
    slots = len(draw)
    start_temp = limits.plan_start_temp if start_temp is None else start_temp
    required = minimums(slots, ready_indices, start_temp, limits)
    # states: temperatura co 0,1°C -> (koszt z karą, dokładna temperatura) po bieżącym kwadransie.
    states: dict[float, tuple[float, float]] = {round(start_temp, 1): (0.0, start_temp)}
    choices: list[dict[float, tuple[float, bool]]] = []
    for slot in range(slots):
        new_states: dict[float, tuple[float, float]] = {}
        choice: dict[float, tuple[float, bool]] = {}
        for key, (base, temp) in states.items():
            for active in (False, True):
                after = step(tank, temp, active, draw[slot])
                if active and after > limits.max_temp:
                    continue
                total = base + (prices[slot] * tank.slot_kwh if active else 0.0)
                if active and allowed is not None and not allowed[slot]:
                    total += OVER_LIMIT_PENALTY
                total += SHORTFALL_PENALTY * max(required[slot] - after, 0.0)
                bucket = round(after, 1)
                if total < new_states.get(bucket, (float("inf"), 0.0))[0] - 1e-9:
                    new_states[bucket], choice[bucket] = (total, after), (key, active)
        choices.append(choice)
        states = new_states

    key = min(states, key=lambda value: (states[value][0], value))
    on = [False] * slots
    for slot in range(slots - 1, -1, -1):
        key, on[slot] = choices[slot][key]
    return simulate(tank, start_temp, on, draw, prices, required)
