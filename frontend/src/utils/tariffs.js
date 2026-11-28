export const PRICE_PARTS = [
  { key: "energy", label: "energia" },
  { key: "distribution", label: "dystrybucja" },
  { key: "fees", label: "opłaty za kWh" },
  { key: "vat", label: "VAT" },
];

export const describeBreakdown = (breakdown, format) =>
  breakdown ? PRICE_PARTS.map(({ key, label }) => `${label} ${format(breakdown[key])}`).join(" · ") : null;

export { formatPln } from "./format";
