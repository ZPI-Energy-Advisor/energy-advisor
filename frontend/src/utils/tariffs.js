export const PRICE_PARTS = [
  { key: "energy", label: "energia" },
  { key: "distribution", label: "dystrybucja" },
  { key: "fees", label: "opłaty za kWh" },
  { key: "vat", label: "VAT" },
];

export const describeBreakdown = (breakdown, format) =>
  breakdown ? PRICE_PARTS.map(({ key, label }) => `${label} ${format(breakdown[key])}`).join(" · ") : null;

const plnFormatter = new Intl.NumberFormat("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const formatPln = (value) => (value == null ? "—" : `${plnFormatter.format(value)} zł`);

// Taryfy z kosztów pliku w kolejności z backendu; `pricing.tariff_key` to taryfa kosztów (z profilu albo zastępcza).
export const tariffEntries = (results) =>
  Object.entries(results?.tariffs ?? {}).map(([key, tariff]) => ({ ...tariff, key: tariff.key ?? key }));
