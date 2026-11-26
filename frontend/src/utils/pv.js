import { formatNumber } from "./format";

const TIME_ZONE = "Europe/Warsaw";
const timeFormatter = new Intl.DateTimeFormat("pl-PL", { timeZone: TIME_ZONE, hour: "2-digit", minute: "2-digit" });
const weekdayFormatter = new Intl.DateTimeFormat("pl-PL", { timeZone: "UTC", weekday: "long" });
const dayMonthFormatter = new Intl.DateTimeFormat("pl-PL", { timeZone: "UTC", day: "numeric", month: "long" });

export const formatKwh = (value, digits = 1) => (value == null ? "—" : `${formatNumber(value, digits)} kWh`);
export const formatPln = (value) => (value == null ? "—" : `${formatNumber(value, 2)} zł`);
export const formatPercent = (share) => (share == null ? "—" : `${formatNumber(share * 100, 0)}%`);
export const formatClock = (iso) => timeFormatter.format(new Date(iso));
const roundDegrees = (value) => formatNumber(Math.round(value) + 0, 0);

export const formatTemperatureRange = (low, high) => {
  if (low == null || high == null) return null;
  if (Math.round(low) === Math.round(high)) return `${roundDegrees(low)}°C`;
  return `od ${roundDegrees(low)} do ${roundDegrees(high)}°C`;
};

const atNoon = (isoDate) => new Date(`${isoDate}T12:00:00Z`);

export const addDays = (isoDate, days) => {
  const moment = atNoon(isoDate);
  moment.setUTCDate(moment.getUTCDate() + days);
  return moment.toISOString().slice(0, 10);
};

export const formatDayLong = (isoDate) => `${weekdayFormatter.format(atNoon(isoDate))}, ${dayMonthFormatter.format(atNoon(isoDate))}`;

export const dayName = (isoDate, today) => {
  if (isoDate === today) return "Dziś";
  if (isoDate === addDays(today, 1)) return "Jutro";
  if (isoDate === addDays(today, 2)) return "Pojutrze";
  if (isoDate === addDays(today, -1)) return "Wczoraj";
  return null;
};

export const describeSettlement = (installation) => {
  if (installation.settlement === "net_billing") return `net-billing, oddanie po ${installation.price_type}`;
  return `net-metering, opust ${formatNumber(installation.k_factor, 1)}`;
};

const DIRECTIONS = { 0: "południe", "-90": "wschód", 90: "zachód", 180: "północ", "-45": "południowy wschód", 45: "południowy zachód" };
export const describeArray = (array) =>
  `${formatNumber(array.kwp, 2)} kWp, ${DIRECTIONS[array.azimuth] ?? `azymut ${array.azimuth}°`}, ${array.tilt}°`;

// Jedna grupa paneli: „6,00 kWp, południe, 35°”; kilka: suma i grupy w nawiasie.
export const describePanels = (installation) =>
  installation.arrays.length === 1
    ? describeArray(installation.arrays[0])
    : `${formatNumber(installation.total_kwp, 2)} kWp (${installation.arrays.map(describeArray).join("; ")})`;

const formatShortDate = (isoDate) => `${isoDate.slice(8, 10)}.${isoDate.slice(5, 7)}.${isoDate.slice(0, 4)}`;
const MAX_LISTED_PERIODS = 4;

// Okresy z plików: „13.06.2025–08.08.2025, 01.10.2026–12.11.2026”; przy wielu tylko najnowsze.
export const describePeriods = (periods) => {
  const listed = periods.slice(-MAX_LISTED_PERIODS).map((period) =>
    period.first_day === period.last_day
      ? formatShortDate(period.first_day)
      : `${formatShortDate(period.first_day)}–${formatShortDate(period.last_day)}`);
  const hidden = periods.length - listed.length;
  return hidden > 0 ? `${listed.join(", ")} (i ${hidden} wcześniejszych okresów)` : listed.join(", ");
};

const daysWord = (count) => (count === 1 ? "dnia" : "dni");

// Opis dopasowania: z ilu dni z produkcją skorzystaliśmy, ile pominęliśmy i o ile prognoza myli dzienną produkcję
// (MAPE z kalibracji, np. 0,04 jako „o 4%”). Pominięte to dni, w których produkcja nie pasowała do pogody.
export const describeAccuracy = (calibration) => {
  if (calibration.source !== "history") {
    return "Prognoza nie jest jeszcze dopasowana do Twojej instalacji: zakładamy typowe straty (sprawność 0,8).";
  }
  const error = `dzienną produkcję myli średnio o ${formatPercent(calibration.mape)}`;
  const skipped = (calibration.candidate_days ?? 0) - calibration.days;
  if (skipped > 0) {
    return `Prognoza dopasowana do ${calibration.days} z ${calibration.candidate_days} dni z produkcją z Twoich plików. `
      + `${skipped} ${skipped === 1 ? "dzień" : "dni"} pominęliśmy, bo produkcja nie pasowała do pogody (np. śnieg, awaria, błąd w pliku). `
      + `Na pozostałych ${error}.`;
  }
  return `Prognoza dopasowana do produkcji z ${calibration.days} ${daysWord(calibration.days)} z Twoich plików; ${error}.`;
};

const dayMonthNumeric = new Intl.DateTimeFormat("pl-PL", { timeZone: "UTC", day: "2-digit", month: "2-digit" });
const formatDayMonth = (isoDate) => dayMonthNumeric.format(atNoon(isoDate));

const TYPICAL_KINDS = {
  workday: ["dnia roboczego", "dni roboczych"],
  weekend: ["dnia weekendowego", "dni weekendowych"],
  all: ["dnia", "dni"],
};

export const describeTypical = (typical) => {
  const [one, many] = TYPICAL_KINDS[typical.kind] ?? TYPICAL_KINDS.all;
  const days = typical.days === 1 ? `1 ${one}` : `${typical.days} ${many}`;
  return `średnia z ${days} z plików (${formatDayMonth(typical.first_day)}–${formatDayMonth(typical.last_day)})`;
};

export const describeConsumption = (detail) => {
  if (detail.consumption_source === "devices") return "z pliku urządzeń";
  if (detail.consumption_source === "meter") return "z licznika i produkcji z modelu";
  if (detail.consumption_source === "meter_without_pv") return "pobór z licznika, dom jeszcze bez paneli";
  if (detail.consumption_source === "typical" && detail.typical) return `szacunek: ${describeTypical(detail.typical)}`;
  return null;
};

export const describeWeatherSource = (detail) => {
  if (detail.kind !== "past") return "prognoza pogody";
  if (detail.weather_source === "archive") return "pogoda z archiwum";
  if (detail.weather_source === "forecast") return "pogoda z prognozy";
  if (detail.weather_source === "mixed") return "pogoda z archiwum i prognozy";
  return null;
};

// Punkty wykresu doby: moc średnia w kwadransie (kW = kWh × 4), zużycie i zachmurzenie.
export const chartPoints = (intervals) =>
  intervals.map((interval) => ({
    start: interval.start,
    label: formatClock(interval.start),
    model: interval.model_kwh == null ? null : interval.model_kwh * 4,
    actual: interval.actual_kwh == null ? null : interval.actual_kwh * 4,
    consumption: interval.consumption_kwh == null ? null : interval.consumption_kwh * 4,
    cloud: interval.cloud_cover_pct,
    temperature: interval.temperature_c,
  }));

export const selfShare = (balance) => (balance && balance.production_kwh > 0 ? balance.self_kwh / balance.production_kwh : null);
