const MINUTES_IN_DAY = 24 * 60;

// Backend zwraca czas lokalny z przesunięciem strefy, np. 2026-10-19T17:00:00+02:00,
// więc datę i godzinę czytamy wprost z tekstu, niezależnie od strefy przeglądarki.
export const dayOf = (isoTime) => isoTime.slice(0, 10);
export const clockOf = (isoTime) => isoTime.slice(11, 16);
export const minutesOf = (isoTime) => Number(isoTime.slice(11, 13)) * 60 + Number(isoTime.slice(14, 16));

export const formatPln = (value) =>
  value == null
    ? "–"
    : `${value.toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} zł`;

export const formatDayMonth = (isoDate) => `${isoDate.slice(8, 10)}.${isoDate.slice(5, 7)}`;

export const listDays = (dateFrom, dateTo) => {
  const days = [];
  const end = new Date(`${dateTo}T00:00:00Z`);
  for (let day = new Date(`${dateFrom}T00:00:00Z`); day <= end; day.setUTCDate(day.getUTCDate() + 1)) {
    days.push(day.toISOString().slice(0, 10));
  }
  return days;
};

// Doby na wykresie: wybrany zakres i doba, w której kończy się akcja wystająca poza niego.
export const visibleDays = (dateFrom, dateTo, actions) => {
  const lastDay = actions
    .flatMap((action) => [action.original_end, action.end])
    .filter((end) => minutesOf(end) > 0)
    .map(dayOf)
    .reduce((latest, day) => (day > latest ? day : latest), dateTo);
  return listDays(dateFrom, lastDay);
};

// Fragment akcji w danej dobie jako pozycja na osi 0-100%; null, gdy akcja nie dotyka tej doby.
export const daySegment = (start, end, day) => {
  if (day < dayOf(start) || day > dayOf(end)) return null;
  const from = dayOf(start) === day ? minutesOf(start) : 0;
  const to = dayOf(end) === day ? minutesOf(end) : MINUTES_IN_DAY;
  if (to <= from) return null;
  return { left: (from / MINUTES_IN_DAY) * 100, width: ((to - from) / MINUTES_IN_DAY) * 100 };
};

// Wiersze osi czasu dla doby: urządzenia z ich akcjami przed i po optymalizacji.
export const dayRows = (actions, day) => {
  const rows = new Map();
  for (const action of actions) {
    const before = daySegment(action.original_start, action.original_end, day);
    // Ładowanie EV po optymalizacji może mieć przerwy: każdy okres ładowania to osobny fragment.
    const after = (action.charging ?? [{ start: action.start, end: action.end }])
      .map((period) => daySegment(period.start, period.end, day))
      .filter(Boolean);
    if (!before && !after.length) continue;
    if (!rows.has(action.device_id)) {
      rows.set(action.device_id, { deviceId: action.device_id, name: action.device_name, before: [], after: [] });
    }
    const row = rows.get(action.device_id);
    if (before) row.before.push({ ...before, action });
    row.after.push(...after.map((segment) => ({ ...segment, action })));
  }
  return [...rows.values()].sort((first, second) => first.name.localeCompare(second.name, "pl"));
};

export const clockRange = (start, end) => `${clockOf(start)}–${clockOf(end)}`;

// Godziny akcji po optymalizacji; ładowanie EV z przerwami jako lista okresów.
export const afterRanges = (action) =>
  (action.charging ?? [{ start: action.start, end: action.end }])
    .map((period) => clockRange(period.start, period.end))
    .join(", ");

// Opis akcji w dymku: godziny przed → po i koszt.
export const actionSummary = (action) => {
  const program = action.program_name ? ` (${action.program_name})` : "";
  return (
    `${action.device_name}${program}: ${clockRange(action.original_start, action.original_end)} → ${afterRanges(action)}, ` +
    `${formatPln(action.cost_before)} → ${formatPln(action.cost_after)}`
  );
};

export const dayPrices = (prices, day) =>
  prices
    .filter((point) => dayOf(point.start) === day)
    .map((point) => ({ minute: minutesOf(point.start), price: point.price_pln_kwh }));

const CONFLICT_REASONS = {
  outside_window: "poza dozwolonym oknem godzin",
  missing_prices: "brak cen dla tego okresu",
  grid_limit: "przekroczony limit przyłącza",
};

export const describeReason = (reason) => CONFLICT_REASONS[reason] ?? reason;

// Powód konfliktu; przy limicie przyłącza z jego wartością z profilu.
export const conflictText = (action, maxGridKw) =>
  action.reason === "grid_limit" && maxGridKw
    ? `${describeReason(action.reason)} (${String(maxGridKw).replace(".", ",")} kW, moc umowna z profilu)`
    : describeReason(action.reason);

export const isConflict = (action) => action.status === "conflict" && action.reason !== "missing_prices";

export const missingPricesNote = (count, days) => {
  if (!count) return null;
  const listedDays = days.map(formatDayMonth).join(", ");
  return (
    `Brak cen dynamicznych dla ${count} akcji (${listedDays}). ` +
    "Te akcje zostają na swoim miejscu i nie wchodzą do kosztów ani oszczędności."
  );
};
