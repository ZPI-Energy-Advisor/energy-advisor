export const OPERATOR_NAMES = {
  PGE: "PGE Dystrybucja",
  TAURON: "TAURON Dystrybucja",
  ENEA: "Enea Operator",
  ENERGA: "Energa-Operator",
  STOEN: "Stoen Operator",
};

export const PV_MODE_LABELS = {
  net_metering: "Net-metering",
  net_billing: "Net-billing",
};

export const DYNAMIC_TYPE = "dynamiczna";

// Składniki netto okresu w kolejności z faktury.
export const CYCLE_COMPONENTS = [
  ["active_energy_net", "Energia czynna"],
  ["trade_fee_net", "Opłata handlowa"],
  ["excise_net", "Akcyza"],
  ["variable_network_net", "Dystrybucja zmienna"],
  ["fixed_network_net", "Opłata stała"],
  ["subscription_net", "Abonament"],
  ["quality_net", "Opłata jakościowa"],
  ["renewable_net", "Opłata OZE"],
  ["cogeneration_net", "Opłata kogeneracyjna"],
  ["capacity_net", "Opłata mocowa"],
  ["transition_net", "Opłata przejściowa"],
  ["vat", "VAT"],
];

// Kolumny skróconej tabeli okresów; razem dają kwotę brutto okresu.
export const CYCLE_GROUPS = [
  { key: "energy", label: "Energia", parts: ["active_energy_net", "trade_fee_net"] },
  { key: "distribution", label: "Dystrybucja", parts: ["variable_network_net", "fixed_network_net", "subscription_net"] },
  {
    key: "fees",
    label: "Opłaty",
    parts: ["excise_net", "quality_net", "renewable_net", "cogeneration_net", "capacity_net", "transition_net"],
  },
  { key: "vat", label: "VAT", parts: ["vat"] },
];

const COMPONENT_LABELS = Object.fromEntries(CYCLE_COMPONENTS);

export const cycleGroupTitle = (group) => group.parts.map((part) => COMPONENT_LABELS[part].toLowerCase()).join(", ");

export const cycleGroupValue = (cycle, group) =>
  Math.round(group.parts.reduce((sum, part) => sum + Number(cycle[part] ?? 0), 0) * 100) / 100;

export const isPriced = (entry) => entry?.payable_gross != null;

export const isDynamic = (entry) => entry.type === DYNAMIC_TYPE;

// Wiersz = grupa taryfowa, kolumny: zwykła umowa i ta sama grupa z ceną dynamiczną.
export const tariffMatrix = (entries) => {
  const rows = new Map();
  for (const entry of entries) {
    const row = rows.get(entry.distribution_group) ?? { group: entry.distribution_group, regular: null, dynamic: null };
    row[isDynamic(entry) ? "dynamic" : "regular"] = entry;
    rows.set(entry.distribution_group, row);
  }
  return [...rows.values()];
};

export const findEntry = (comparison, key) => comparison?.tariffs.find((entry) => entry.key === key) ?? null;

export const comparisonSummary = (comparison) => {
  const selected = findEntry(comparison, comparison?.selected_tariff);
  const cheapest = findEntry(comparison, comparison?.cheapest_tariff);
  const saving =
    isPriced(selected) && isPriced(cheapest) ? Math.round((selected.payable_gross - cheapest.payable_gross) * 100) / 100 : null;
  return { selected: isPriced(selected) ? selected : null, cheapest, saving };
};

// Taryfa pokazana w szczegółach: wybrana przez użytkownika, a domyślnie taryfa z profilu albo najtańsza.
export const detailsKey = (comparison, chosenKey) => {
  if (findEntry(comparison, chosenKey)) return chosenKey;
  const selected = findEntry(comparison, comparison?.selected_tariff);
  if (isPriced(selected)) return selected.key;
  return comparison?.cheapest_tariff ?? comparison?.tariffs[0]?.key ?? null;
};

// Linie wykresu: domyślnie Twoja, najtańsza i zaznaczona taryfa; tylko taryfy z cenami na wykresie.
export const chartTariffKeys = (comparison, chosenKey, showAll, chartKeys) => {
  const available = new Set(chartKeys);
  const ordered = (comparison?.tariffs ?? []).map((entry) => entry.key).filter((key) => available.has(key));
  if (showAll) return ordered;
  const wanted = new Set([comparison?.selected_tariff, comparison?.cheapest_tariff, chosenKey]);
  return ordered.filter((key) => wanted.has(key));
};

export const chartKeysOf = (rows) => {
  const keys = new Set();
  for (const row of rows ?? []) {
    for (const name of Object.keys(row)) {
      if (name.startsWith("price_")) keys.add(name.slice("price_".length));
    }
  }
  return [...keys];
};

export const formatDifference = (value, format) => {
  if (value == null) return null;
  if (Math.abs(value) < 0.005) return "tyle samo";
  return `${value > 0 ? "+" : "−"}${format(Math.abs(value))}`;
};
