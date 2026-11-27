// Plan pracy urządzeń na dzień (ZP-112): daty, godziny i podział pozycji planu.
import { afterRanges, clockRange, dayOf, formatDayMonth } from "./schedule";

const WEEKDAYS = ["niedziela", "poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota"];

// Daty to napisy RRRR-MM-DD: liczymy w UTC, żeby strefa przeglądarki nie zmieniła dnia.
export const nextDay = (isoDate) => {
  const day = new Date(`${isoDate}T12:00:00Z`);
  day.setUTCDate(day.getUTCDate() + 1);
  return day.toISOString().slice(0, 10);
};

const ON_WEEKDAYS = ["w niedzielę", "w poniedziałek", "we wtorek", "w środę", "w czwartek", "w piątek", "w sobotę"];
const MONTHS = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia", "września",
  "października", "listopada", "grudnia"];

// „w piątek 6 listopada”: dzień słowami, bez skrótów i zer.
export const onDay = (isoDate) => {
  const day = new Date(`${isoDate}T12:00:00Z`);
  return `${ON_WEEKDAYS[day.getUTCDay()]} ${day.getUTCDate()} ${MONTHS[day.getUTCMonth()]}`;
};

export const weekdayDate = (isoDate) =>
  `${WEEKDAYS[new Date(`${isoDate}T12:00:00Z`).getUTCDay()]} ${formatDayMonth(isoDate)}`;

// Godziny z datą, np. 12.10 07:00–07:45.
export const momentRange = (start, end) => `${formatDayMonth(dayOf(start))} ${clockRange(start, end)}`;

export const PLAN_KIND_ORDER = { program: 0, ev: 1, water_heater: 2, heat_pump: 3 };

// Pozycje planu do tabeli: urządzenia z ustawień po kolei, a w urządzeniu według godziny.
export const planRows = (items) =>
  [...items].sort((first, second) =>
    (PLAN_KIND_ORDER[first.kind] - PLAN_KIND_ORDER[second.kind])
    || first.device_name.localeCompare(second.device_name, "pl")
    || first.original_start.localeCompare(second.original_start));

// Kod błędu braku cen na dzień planu (409 z backendu) z ostatnim dniem z cenami do planu demo.
export const noPricesFrom = (error) => {
  const detail = error?.response?.data?.detail;
  return error?.response?.status === 409 && detail?.code === "no_prices" ? detail : null;
};

// Godziny pracy bez planu, z przerwami jak w planie (np. termostat bojlera grzeje porcjami).
export const beforeRanges = (item) =>
  afterRanges({ charging: item.original_charging, start: item.original_start, end: item.original_end }, { withDay: true });

const shortDate = (isoDate) => `${isoDate.slice(8, 10)}.${isoDate.slice(5, 7)}.${isoDate.slice(0, 4)}`;

// Okresy plików urządzeń, np. „05.10.2026–30.10.2026, 01.12.2026”.
export const periodsText = (periods) =>
  periods
    .map(({ first_day: first, last_day: last }) => (first === last ? shortDate(first) : `${shortDate(first)}–${shortDate(last)}`))
    .join(", ");

export const inPeriods = (day, periods) =>
  Boolean(day) && periods.some(({ first_day: first, last_day: last }) => first <= day && day <= last);

// Jutro według zegara użytkownika (RRRR-MM-DD): plan na wcześniejszy dzień jest już nieaktualny.
export const localTomorrow = (now = new Date()) => {
  const day = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
  return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
};
