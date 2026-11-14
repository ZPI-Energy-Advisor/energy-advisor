// Daty jako napisy RRRR-MM-DD liczone w UTC: strefa przeglądarki nie przesuwa dnia.

const DAY_MS = 24 * 60 * 60 * 1000;

const toDate = (isoDate) => new Date(`${isoDate}T00:00:00Z`);
const toIso = (date) => date.toISOString().slice(0, 10);

export const MONTH_NAMES = [
  "styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec",
  "lipiec", "sierpień", "wrzesień", "październik", "listopad", "grudzień",
];
export const WEEKDAY_SHORT = ["Pn", "Wt", "Śr", "Cz", "Pt", "Sb", "Nd"];
const WEEKDAY_NAMES = ["niedziela", "poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota"];

export const addDays = (isoDate, days) => toIso(new Date(toDate(isoDate).getTime() + days * DAY_MS));

export const daysBetween = (from, to) => Math.round((toDate(to) - toDate(from)) / DAY_MS) + 1;

export const monthOf = (isoDate) => isoDate.slice(0, 7);

export const addMonths = (month, count) => {
  const date = toDate(`${month}-01`);
  date.setUTCMonth(date.getUTCMonth() + count);
  return toIso(date).slice(0, 7);
};

export const monthTitle = (month) => `${MONTH_NAMES[Number(month.slice(5, 7)) - 1]} ${month.slice(0, 4)}`;

/** Tygodnie miesiąca od poniedziałku: dni spoza miesiąca to null. */
export const monthWeeks = (month) => {
  const first = toDate(`${month}-01`);
  const offset = (first.getUTCDay() + 6) % 7;
  const days = [...Array(offset).fill(null)];
  for (let day = first; toIso(day).startsWith(month); day = new Date(day.getTime() + DAY_MS)) {
    days.push(toIso(day));
  }
  while (days.length % 7) days.push(null);
  const weeks = [];
  for (let index = 0; index < days.length; index += 7) weeks.push(days.slice(index, index + 7));
  return weeks;
};

/** Losowy dzień z zakresu (włącznie); `random` jak Math.random, do testów. */
export const randomDay = (min, max, random = Math.random) =>
  addDays(min, Math.floor(random() * daysBetween(min, max)));

const shortDate = (isoDate) => `${isoDate.slice(8, 10)}.${isoDate.slice(5, 7)}`;

export const weekdayName = (isoDate) => WEEKDAY_NAMES[toDate(isoDate).getUTCDay()];

/** „19.10–25.10 (7 dni)” albo „19.10 (1 dzień)”. */
export const rangeText = (from, to) => {
  const count = daysBetween(from, to);
  const days = count === 1 ? "1 dzień" : `${count} dni`;
  return from === to ? `${shortDate(from)}, ${weekdayName(from)} (${days})` : `${shortDate(from)}–${shortDate(to)} (${days})`;
};
