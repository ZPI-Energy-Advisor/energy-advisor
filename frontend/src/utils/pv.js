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

// Błąd prognozy w zdaniu: MAPE z kalibracji (np. 0,04) jako „średnio o 4%”.
export const describeAccuracy = (calibration) => {
  if (calibration.source !== "history") {
    return "Prognoza nie jest jeszcze dopasowana do Twojej instalacji: zakładamy typowe straty (sprawność 0,8).";
  }
  const days = calibration.days === 1 ? "dniu" : "dniach";
  return `Prognoza dopasowana do produkcji z Twoich plików (${calibration.days} ${days}); dzienną produkcję myli średnio o ${formatPercent(calibration.mape)}.`;
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
