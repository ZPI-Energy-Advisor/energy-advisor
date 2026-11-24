// Wspólne formaty liczb (pl-PL: przecinek dziesiętny, spacja tysięcy), żeby kwoty i osie wykresów
// wyglądały tak samo na każdym ekranie.
const formatters = new Map();

const formatter = (minimumFractionDigits, maximumFractionDigits) => {
  const key = `${minimumFractionDigits}:${maximumFractionDigits}`;
  if (!formatters.has(key)) {
    formatters.set(key, new Intl.NumberFormat("pl-PL", { minimumFractionDigits, maximumFractionDigits }));
  }
  return formatters.get(key);
};

export const formatNumber = (value, digits = 2) =>
  value == null || Number.isNaN(Number(value)) ? "—" : formatter(digits, digits).format(Number(value));

// Podziałka osi: bez zbędnych zer (1,5 zamiast 1,50), z przecinkiem.
export const formatAxis = (value) => formatter(0, 2).format(value);

// Podpis jednostki na osi Y, jak na wykresie cen.
export const axisUnitLabel = (unit) => ({
  value: unit, angle: -90, position: "insideLeft", offset: 8, fontSize: 11, fill: "#94a3b8",
});
