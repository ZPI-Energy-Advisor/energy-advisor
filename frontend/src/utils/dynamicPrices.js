import { countDays, formatDate } from "./energyFiles";

// Limity zgodne z backendem (MAX_HISTORY_DAYS) 
export const PRICE_RESOLUTIONS = [
  { value: "15min", label: "15 min", maxDays: 31 },
  { value: "hour", label: "1 godz", maxDays: 92 },
  { value: "day", label: "Dni", maxDays: null },
];


export const QUARTER_HOUR_PRICES_SINCE = "2025-10-01";

export const isResolutionAllowed = (resolution, range) => {
  const option = PRICE_RESOLUTIONS.find((item) => item.value === resolution);
  return !option?.maxDays || countDays(range) <= option.maxDays;
};

export const resolveResolution = (preferred, range) =>
  isResolutionAllowed(preferred, range)
    ? preferred
    : PRICE_RESOLUTIONS.find((item) => isResolutionAllowed(item.value, range)).value;

const shiftDate = (isoDate, days) => {
  const date = new Date(`${isoDate}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
};

const QUICK_RANGE_DAYS = [
  { label: "7 dni", days: 7 },
  { label: "30 dni", days: 30 },
  { label: "90 dni", days: 90 },
  { label: "Rok", days: 365 },
];

export const buildPriceQuickRanges = (bounds) => {
  const ranges = QUICK_RANGE_DAYS.map(({ label, days }) => {
    const from = shiftDate(bounds.to, -(days - 1));
    return { label, from: from < bounds.from ? bounds.from : from, to: bounds.to };
  }).filter((range) => range.from !== bounds.from);
  return [...ranges, { label: "Cały okres", ...bounds }];
};

const priceFormatter = new Intl.NumberFormat("pl-PL", { minimumFractionDigits: 3, maximumFractionDigits: 3 });
const axisFormatter = new Intl.NumberFormat("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const formatPrice = (value) => (value == null ? "—" : `${priceFormatter.format(value)} zł/kWh`);
export const formatAxisPrice = (value) => axisFormatter.format(value);

const percentFormatter = new Intl.NumberFormat("pl-PL", { style: "percent", maximumFractionDigits: 1 });
export const formatPercent = (value) => percentFormatter.format(value);

export const describeTariffPrice = (history) =>
  `Rynkowa cena energii (RCE) + narzut ${formatPrice(history.markup_pln_kwh)} netto + VAT ${formatPercent(history.vat_rate)}`;

export const pointDate = (start) => start.slice(0, 10);
const pointTime = (start) => start.slice(11, 16);

const MAX_DAY_TICKS = 10;

export const buildAxisTicks = (points, resolution) => {
  if (resolution === "day" || points.length === 0) return { ticks: undefined, singleDay: false };
  const singleDay = pointDate(points[0].start) === pointDate(points.at(-1).start);
  if (singleDay) {
    return { ticks: points.filter((p) => /^(00|03|06|09|12|15|18|21):00$/.test(pointTime(p.start))).map((p) => p.start), singleDay };
  }
  const dayStarts = points.filter((p, i) => i === 0 || pointDate(p.start) !== pointDate(points[i - 1].start));
  const stride = Math.ceil(dayStarts.length / MAX_DAY_TICKS);
  return { ticks: dayStarts.filter((_, i) => i % stride === 0).map((p) => p.start), singleDay };
};

export const formatPointTick = (start, { singleDay, multiYear }) => {
  if (singleDay) return pointTime(start);
  const date = formatDate(pointDate(start));
  return multiYear ? `${date.slice(0, 6)}${date.slice(8)}` : date.slice(0, 5);
};

export const buildStatusAreas = (points, days) => {
  const statusByDay = new Map([
    ...days.incomplete.map((day) => [day, "incomplete"]),
    ...days.missing.map((day) => [day, "missing"]),
  ]);
  const areas = [];
  points.forEach((point, index) => {
    const status = statusByDay.get(pointDate(point.start));
    const last = areas.at(-1);
    if (status && last?.status === status && last.endIndex === index - 1) {
      last.endIndex = index;
    } else if (status) {
      areas.push({ status, startIndex: index, endIndex: index });
    }
  });
  return areas.map(({ status, startIndex, endIndex }) => ({
    status,
    x1: points[startIndex].start,
    x2: points[Math.min(endIndex + 1, points.length - 1)].start,
  }));
};

export const groupConsecutiveDays = (days) => {
  const groups = [];
  for (const day of days) {
    const last = groups.at(-1);
    if (last && shiftDate(last.to, 1) === day) {
      last.to = day;
      last.count += 1;
    } else {
      groups.push({ from: day, to: day, count: 1 });
    }
  }
  return groups;
};

export const formatDayGroup = ({ from, to, count }) => {
  if (count === 1) return formatDate(from);
  const sameYear = from.slice(0, 4) === to.slice(0, 4);
  return `${formatDate(from).slice(0, sameYear ? 5 : 10)}–${formatDate(to)} · ${formatDaysCount(count)}`;
};

export const formatPointLabel = (start, resolution) => {
  const date = formatDate(pointDate(start));
  if (resolution === "day") return date;
  const zone = start.endsWith("+02:00") ? "CEST" : "CET";
  return `${date}, ${pointTime(start)} (${zone})`;
};

export const formatDateTime = (isoDateTime) =>
  isoDateTime
    ? new Date(isoDateTime).toLocaleString("pl-PL", {
        timeZone: "Europe/Warsaw",
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";

export const formatDaysCount = (count) => `${count} ${count === 1 ? "dzień" : "dni"}`;
