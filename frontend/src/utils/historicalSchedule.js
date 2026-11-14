// Optymalizacja historyczna: podział akcji na urządzenia stałe i przesuwalne oraz podsumowanie dni.
import { dayOf, listDays } from "./schedule";

export const isFixed = (action) => action.flexibility_mode === "fixed";

/** Akcje, które optymalizacja może przesunąć; urządzeń stałych nie pokazujemy na wykresach i w tabelach. */
export const flexibleActions = (actions) => actions.filter((action) => !isFixed(action));

/** Urządzenia stałe z liczbą kWh w okresie, po nazwie. */
export const fixedDevices = (actions) => {
  const devices = new Map();
  for (const action of actions.filter(isFixed)) {
    const device = devices.get(action.device_id) ?? { deviceId: action.device_id, name: action.device_name, energy: 0 };
    device.energy += action.energy_kwh;
    devices.set(action.device_id, device);
  }
  return [...devices.values()].sort((first, second) => first.name.localeCompare(second.name, "pl"));
};

/** Doby okresu z kosztem urządzeń przesuwalnych przed i po (akcja należy do doby swojego startu przed). */
export const daySummaries = (actions, dateFrom, dateTo) => {
  const days = new Map(listDays(dateFrom, dateTo).map((day) => [day, { day, moved: 0, before: 0, after: 0 }]));
  for (const action of flexibleActions(actions)) {
    const summary = days.get(dayOf(action.original_start));
    if (!summary || action.cost_before == null || action.cost_after == null) continue;
    summary.before += action.cost_before;
    summary.after += action.cost_after;
    if (action.status === "moved") summary.moved += 1;
  }
  return [...days.values()].map((summary) => ({ ...summary, saving: summary.before - summary.after }));
};
