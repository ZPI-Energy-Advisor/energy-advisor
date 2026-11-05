import { ALL_DEVICE_FILES_ID, ALL_FILES_ID, SOURCE_TYPE_DEVICES } from "./energyFiles";

// Stała paleta kategorii z docs/devices-file-format.md: ten sam kolor kategorii na każdym wykresie.
export const CATEGORY_COLORS = {
  AGD: "#3b82f6",
  Ogrzewanie: "#ef4444",
  Oświetlenie: "#f59e0b",
  "Pojazd elektryczny": "#8b5cf6",
  "RTV/IT": "#06b6d4",
  OZE: "#22c55e",
  Inne: "#ec4899",
};
export const REST_OF_HOUSE_KEY = "rest_of_house";
export const REST_OF_HOUSE_COLOR = "#cbd5e1";
export const PRODUCTION_KEY = "production";
export const PRODUCTION_COLOR = CATEGORY_COLORS.OZE;
const FALLBACK_COLOR = "#94a3b8";
// Po wejściu w kategorię typy i urządzenia dostają wyraźnie różne kolory, a nie odcienie jednej barwy.
export const DRILL_COLORS = [
  "#2563eb", "#f97316", "#16a34a", "#dc2626", "#9333ea", "#0891b2",
  "#ca8a04", "#db2777", "#4f46e5", "#65a30d", "#0d9488", "#b45309",
];

export const UNAVAILABLE_NO_DEVICE_FILES = "no-device-files";
export const UNAVAILABLE_NO_COMMON_DAYS = "no-common-days";

/**
 * Skąd brać dane urządzeń dla wybranego źródła Dashboardu.
 * Plik urządzeń pokazuje własne urządzenia, a plik licznika (lub „Wszystkie pliki”) urządzenia ze
 * „Wszystkich plików urządzeń” w dniach wspólnych obu źródeł, z grupą „Reszta domu”.
 */
export const deviceUsageSource = ({ selectedFile, dateRange, devicesAggregate }) => {
  if (!selectedFile || !dateRange) return null;
  if (selectedFile.source_type === SOURCE_TYPE_DEVICES) {
    return { sourceId: selectedFile.id, meter: null, range: dateRange };
  }
  if (!devicesAggregate?.data_start || !devicesAggregate?.data_end) {
    return { unavailable: UNAVAILABLE_NO_DEVICE_FILES };
  }
  // Daty to napisy RRRR-MM-DD, więc porównanie leksykograficzne wystarcza.
  const from = dateRange.from > devicesAggregate.data_start ? dateRange.from : devicesAggregate.data_start;
  const to = dateRange.to < devicesAggregate.data_end ? dateRange.to : devicesAggregate.data_end;
  if (from > to) return { unavailable: UNAVAILABLE_NO_COMMON_DAYS };
  return {
    sourceId: ALL_DEVICE_FILES_ID,
    meter: selectedFile.id === ALL_FILES_ID ? ALL_FILES_ID : selectedFile.id,
    range: { from, to },
  };
};

// Drill-down: [] → [kategoria] → [kategoria, typ] → [kategoria, typ, urządzenie]; elementy to { key, label }.
export const usageQuery = (path, { flexibleOnly = false } = {}) => {
  const [category, deviceType] = path;
  const flexible = flexibleOnly ? { flexible: true } : {};
  if (!category) return { group_by: "category", ...flexible };
  if (!deviceType) return { group_by: "type", category: category.key, ...flexible };
  return { group_by: "instance", category: category.key, type: deviceType.key, ...flexible };
};

export const canDrillDown = (path) => path.length < 3;

export const breadcrumbs = (path) => [
  { label: "Wszystkie", depth: 0 },
  ...path.map((item, index) => ({ label: item.label, depth: index + 1 })),
];

/**
 * Serie wykresu na obecnym poziomie. Na poziomie urządzenia zostaje tylko ono. „Reszta domu”
 * i produkcja PV są tylko w widoku wszystkich urządzeń, bo nie należą do żadnej kategorii.
 */
export const buildSeries = (response, path, { flexibleOnly = false } = {}) => {
  if (!response) return [];
  const device = path[2]?.key;
  const groups = device ? response.groups.filter((group) => group.key === device) : response.groups;
  const series = groups.map((group, index) => {
    return {
      key: group.key,
      label: group.label,
      color:
        path.length === 0 ? CATEGORY_COLORS[group.key] ?? FALLBACK_COLOR : DRILL_COLORS[index % DRILL_COLORS.length],
      flexibleCount: group.flexible_devices_count ?? 0,
      flexibilityMode: group.flexibility_mode ?? null,
      kwh: group.kwh,
      cost: group.cost_pln,
      totalKwh: group.total_kwh,
      totalCost: group.total_cost_pln,
      devicesCount: group.devices_count ?? 0,
      clickable: canDrillDown(path),
    };
  });
  const rest = response.rest_of_house;
  // Reszta domu nie jest urządzeniem, więc przy filtrze urządzeń przesuwalnych jej nie pokazujemy.
  if (path.length === 0 && !flexibleOnly && rest && rest.common_days.length > 0) {
    series.push({
      key: REST_OF_HOUSE_KEY,
      label: "Reszta domu",
      color: REST_OF_HOUSE_COLOR,
      kwh: rest.kwh,
      cost: rest.cost_pln,
      totalKwh: rest.total_kwh,
      totalCost: rest.total_cost_pln,
      devicesCount: 0,
      flexibleCount: 0,
      flexibilityMode: null,
      clickable: false,
    });
  }
  return series;
};

export const productionSeries = (response, path) =>
  path.length === 0 && response?.production ? response.production : null;

/**
 * Wartości na osi wykresu, jak w widoku „Łącznie”: dla 15 min i godzin średni profil doby
 * (suma z dni podzielona przez liczbę dni), a dla dni kolejne doby.
 */
export const profileAxis = (periods, resolution) => {
  if (resolution === "1d") {
    const labels = periods.map((period) => period.slice(0, 10));
    return { labels, positions: labels.map((_, index) => index), divisor: 1 };
  }
  const times = periods.map((period) => period.slice(11, 16));
  const labels = [...new Set(times)].sort();
  const index = new Map(labels.map((label, position) => [label, position]));
  const days = new Set(periods.map((period) => period.slice(0, 10))).size;
  return { labels, positions: times.map((time) => index.get(time)), divisor: Math.max(days, 1) };
};

const project = (values, axis) => {
  const result = new Array(axis.labels.length).fill(0);
  values.forEach((value, period) => {
    result[axis.positions[period]] += value;
  });
  return result.map((value) => value / axis.divisor);
};

/**
 * Wiersze dla wykresu skumulowanego: dla każdej serii kWh i zł (klucze `${key}__kwh`, `${key}__pln`),
 * a produkcja PV jako wartości ujemne, żeby słupki szły pod oś.
 */
export const buildChartRows = (periods, series, production, resolution) => {
  const axis = profileAxis(periods, resolution);
  const rows = axis.labels.map((label) => ({ label }));
  for (const item of series) {
    const kwh = project(item.kwh, axis);
    const cost = project(item.cost, axis);
    rows.forEach((row, position) => {
      row[`${item.key}__kwh`] = kwh[position];
      row[`${item.key}__pln`] = cost[position];
    });
  }
  if (production) {
    const kwh = project(production.kwh, axis);
    rows.forEach((row, position) => {
      row[`${PRODUCTION_KEY}__kwh`] = -kwh[position];
    });
  }
  return rows;
};

// Udziały serii w zużyciu i koszcie wybranego okresu, od największego zużycia.
export const ranking = (series) => {
  const totalKwh = series.reduce((sum, item) => sum + item.totalKwh, 0);
  const totalCost = series.reduce((sum, item) => sum + item.totalCost, 0);
  return [...series]
    .sort((a, b) => b.totalKwh - a.totalKwh)
    .map((item) => ({
      ...item,
      kwhShare: totalKwh > 0 ? item.totalKwh / totalKwh : 0,
      costShare: totalCost > 0 ? item.totalCost / totalCost : 0,
    }));
};

export const totals = (series) => ({
  kwh: series.reduce((sum, item) => sum + item.totalKwh, 0),
  cost: series.reduce((sum, item) => sum + item.totalCost, 0),
  devices: series.reduce((sum, item) => sum + item.devicesCount, 0),
});

export const formatKwh = (value) =>
  `${value.toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} kWh`;

export const formatPln = (value) =>
  `${value.toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} zł`;

export const formatShare = (value) => `${(value * 100).toLocaleString("pl-PL", { maximumFractionDigits: 1 })}%`;
