"""Rachunek domu z PV w planie na jutro i w raporcie z symulacji (ZP-121). Opis: docs/scheduling.md.

Operator bilansuje pobór i oddanie w każdej godzinie, więc rachunek liczymy w godzinach. W godzinie:

- zużycie C (reszta domu i urządzenia z planu) i produkcja P (prognoza PV);
- C > P: dom pobiera C − P. Płaci ceny kwadransów za tę część zużycia, której nie pokryły panele:
  (C − P) / C × Σ zużycie kwadransu × cena kwadransu;
- C ≤ P: nic nie pobiera i oddaje P − C, warte P − C × wartość oddania (przychód, więc rachunek ujemny).

Bez produkcji to dokładnie Σ zużycie × cena kwadransu, czyli koszt bez PV, więc plan domu bez paneli się nie zmienia.
Koszt urządzenia to zmiana rachunku godzin, w których pracuje: w godzinie z nadwyżką kosztuje tyle, ile dom
traci na oddaniu, a nie pełną cenę zakupu.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta

SLOT = timedelta(minutes=15)
HOUR = timedelta(hours=1)
EMPTY: Mapping[datetime, float] = {}


def hour_of(slot: datetime) -> datetime:
    """Godzina kwadransu (UTC; w Polsce przesunięcie strefy to pełne godziny)."""
    return slot.replace(minute=0, second=0, microsecond=0)


@dataclass
class Summary:
    consumption_kwh: float = 0.0
    production_kwh: float = 0.0
    self_kwh: float = 0.0
    export_kwh: float = 0.0
    import_kwh: float = 0.0
    plan_from_pv_kwh: float = 0.0
    export_pln: float = 0.0


@dataclass(frozen=True)
class HourBalance:
    hour: datetime
    production_kwh: float
    rest_kwh: float
    plan_kwh: float
    export_kwh: float

    @property
    def surplus_kwh(self) -> float:
        """Nadwyżka paneli nad resztą domu, zanim dojdą urządzenia z planu."""
        return max(self.production_kwh - self.rest_kwh, 0.0)


@dataclass
class HouseBalance:
    """`base`: zużycie reszty domu, `production`: produkcja PV (kWh na kwadrans), `buy`: cena zakupu kwadransu,
    `sell`: wartość kWh oddanej w godzinie (początek godziny); godzina bez wartości oddania nic za nie nie daje."""

    base: Mapping[datetime, float]
    production: Mapping[datetime, float]
    buy: Mapping[datetime, float]
    sell: Mapping[datetime, float]
    _hour_production: dict[datetime, float] = field(init=False, repr=False)

    def __post_init__(self):
        self._hour_production = defaultdict(float)
        for slot, kwh in self.production.items():
            if kwh > 0:
                self._hour_production[hour_of(slot)] += kwh

    def with_base(self, extra: Mapping[datetime, float]) -> "HouseBalance":
        base = defaultdict(float, self.base)
        for slot, kwh in extra.items():
            base[slot] += kwh
        return HouseBalance(dict(base), self.production, self.buy, self.sell)

    @property
    def has_production(self) -> bool:
        return any(kwh > 0 for kwh in self._hour_production.values())

    def _consumption(self, hour: datetime, *layers: Mapping[datetime, float]) -> list[tuple[datetime, float]]:
        quarters = []
        for index in range(4):
            slot = hour + index * SLOT
            quarters.append((slot, self.base.get(slot, 0.0) + sum(layer.get(slot, 0.0) for layer in layers)))
        return quarters

    def hour_bill(self, hour: datetime, *layers: Mapping[datetime, float]) -> float:
        quarters = self._consumption(hour, *layers)
        consumed = sum(kwh for _, kwh in quarters)
        produced = self._hour_production.get(hour, 0.0)
        if consumed <= produced:
            return -(produced - consumed) * self.sell.get(hour, 0.0)
        priced = sum(kwh * self.buy.get(slot, 0.0) for slot, kwh in quarters)
        return (consumed - produced) / consumed * priced

    def delta(self, planned: Mapping[datetime, float], added: Mapping[datetime, float],
              extra: Mapping[datetime, float] = EMPTY) -> float:
        """O ile wzrośnie rachunek, gdy do zużycia `planned` (+ `extra`) dojdzie `added`."""
        hours = {hour_of(slot) for slot, kwh in added.items() if kwh}
        return sum(self.hour_bill(hour, planned, extra, added) - self.hour_bill(hour, planned, extra) for hour in hours)

    def effective_prices(self, prices: Mapping[datetime, float], slot_kwh: float) -> dict[datetime, float]:
        """Cena kwadransu dla urządzenia, które bierze `slot_kwh` w kwadransie, przy samej reszcie domu: w godzinie,
        w której nadwyżka paneli to pokryje, kosztuje tyle, ile dom traci na oddaniu. Przybliżenie dla bojlera,
        który plan układa przed resztą; koszt i tak liczymy potem dokładnie."""
        result = dict(prices)
        for slot, price in prices.items():
            hour = hour_of(slot)
            produced = self._hour_production.get(hour, 0.0)
            if not produced:
                continue
            consumed = sum(kwh for _, kwh in self._consumption(hour))
            if produced - consumed >= slot_kwh:
                result[slot] = self.sell.get(hour, 0.0)
        return result

    def allocate(self, items: Iterable[tuple[str, datetime, list[float]]]) -> tuple[dict[str, float | None], float]:
        """Koszt urządzeń z planu: zmiana rachunku domu w każdej godzinie, podzielona między urządzenia według
        zużycia razy cena kwadransu (bez PV to dokładnie zużycie × cena). Zwraca koszt każdej pozycji (None, gdy
        brakuje ceny kwadransu z energią) i sumę."""
        items = list(items)
        planned: dict[datetime, float] = defaultdict(float)
        weights: dict[str, dict[datetime, float]] = {}
        missing: set[str] = set()
        for item_id, start, profile in items:
            item_weights = defaultdict(float)
            for index, kwh in enumerate(profile):
                if not kwh:
                    continue
                slot = start + index * SLOT
                if slot not in self.buy:
                    missing.add(item_id)
                planned[slot] += kwh
                item_weights[slot] += kwh
            weights[item_id] = item_weights
        hours = {hour_of(slot) for slot in planned}
        change = {hour: self.hour_bill(hour, planned) - self.hour_bill(hour) for hour in hours}
        hour_weight: dict[datetime, float] = defaultdict(float)
        hour_energy: dict[datetime, float] = defaultdict(float)
        for slot, kwh in planned.items():
            hour_weight[hour_of(slot)] += kwh * self.buy.get(slot, 0.0)
            hour_energy[hour_of(slot)] += kwh
        costs: dict[str, float | None] = {}
        for item_id, item_weights in weights.items():
            if item_id in missing:
                costs[item_id] = None
                continue
            total = 0.0
            for slot, kwh in item_weights.items():
                hour = hour_of(slot)
                if hour_weight[hour] > 0:
                    total += change[hour] * kwh * self.buy.get(slot, 0.0) / hour_weight[hour]
                elif hour_energy[hour] > 0:
                    total += change[hour] * kwh / hour_energy[hour]
            costs[item_id] = total
        return costs, sum(cost for cost in costs.values() if cost is not None)

    def summary(self, planned: Mapping[datetime, float]) -> Summary:
        """Prąd z paneli w dobie: autokonsumpcja, oddanie i pobór (w godzinach), część paneli zużyta przez plan
        (w proporcji do zużycia w godzinie) i wartość oddania."""
        hours = {hour_of(slot) for slot in (*self.base, *planned, *self.production)}
        result = Summary()
        for hour in sorted(hours):
            quarters = self._consumption(hour, planned)
            consumed = sum(kwh for _, kwh in quarters)
            plan_kwh = sum(planned.get(hour + index * SLOT, 0.0) for index in range(4))
            produced = self._hour_production.get(hour, 0.0)
            own = min(consumed, produced)
            result.consumption_kwh += consumed
            result.production_kwh += produced
            result.self_kwh += own
            result.export_kwh += produced - own
            result.import_kwh += consumed - own
            result.export_pln += (produced - own) * self.sell.get(hour, 0.0)
            if consumed > 0:
                result.plan_from_pv_kwh += own * plan_kwh / consumed
        return result

    def hours(self, planned: Mapping[datetime, float]) -> list["HourBalance"]:
        """Godziny z produkcją: produkcja, zużycie reszty domu i urządzeń z planu oraz oddanie do sieci."""
        result = []
        for hour in sorted(self._hour_production):
            produced = self._hour_production[hour]
            rest = sum(kwh for _, kwh in self._consumption(hour))
            plan = sum(planned.get(hour + index * SLOT, 0.0) for index in range(4))
            result.append(HourBalance(hour, produced, rest, plan, max(produced - rest - plan, 0.0)))
        return result

    def from_pv(self, items: Iterable[tuple[str, datetime, list[float]]]) -> dict[str, float]:
        """Ile prądu z paneli bierze każda pozycja planu: w godzinie panele dzielą się po równo na każdą kWh zużycia
        (jak `plan_from_pv_kwh` w `summary`)."""
        items = list(items)
        planned = by_slot((start, profile) for _, start, profile in items)
        share: dict[datetime, float] = {}
        for hour in {hour_of(slot) for slot in planned}:
            consumed = sum(kwh for _, kwh in self._consumption(hour, planned))
            produced = self._hour_production.get(hour, 0.0)
            share[hour] = min(consumed, produced) / consumed if consumed > 0 else 0.0
        return {
            item_id: sum(kwh * share[hour_of(start + index * SLOT)] for index, kwh in enumerate(profile) if kwh)
            for item_id, start, profile in items
        }

    def to_json(self) -> dict:
        def pairs(values: Mapping[datetime, float]) -> list:
            return [[slot.isoformat(), round(kwh, 6)] for slot, kwh in sorted(values.items()) if kwh]

        return {"base": pairs(self.base), "production": pairs(self.production), "sell": pairs(self.sell)}

    @classmethod
    def from_json(cls, data: dict, buy: Mapping[datetime, float]) -> "HouseBalance":
        def values(key: str) -> dict[datetime, float]:
            return {datetime.fromisoformat(slot): kwh for slot, kwh in data.get(key, [])}

        return cls(values("base"), values("production"), buy, values("sell"))


def by_slot(profiles: Iterable[tuple[datetime, list[float]]]) -> dict[datetime, float]:
    result: dict[datetime, float] = defaultdict(float)
    for start, profile in profiles:
        for index, kwh in enumerate(profile):
            if kwh:
                result[start + index * SLOT] += kwh
    return dict(result)
