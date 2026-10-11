export const FILES_TABLE_ANCHOR = "pliki";

export const formatDate = (isoDate) => {
  if (!isoDate) return "";
  const [year, month, day] = isoDate.slice(0, 10).split("-");
  return `${day}.${month}.${year}`;
};

export const formatDateRange = (file) => {
  if (!file?.data_start || !file?.data_end) return "Brak zakresu dat";
  return `${formatDate(file.data_start)} – ${formatDate(file.data_end)}`;
};

export const FILE_STATUS_LABELS = {
  completed: "Gotowy",
  processing: "Przetwarzanie",
  failed: "Błąd przetwarzania",
};

// Taryfa preferowana przez użytkownika, o ile występuje w wynikach pliku;
// w przeciwnym razie pierwsza dostępna.
export const resolveTariffName = (tariffs, preferredName) => {
  if (!tariffs) return null;
  if (preferredName && tariffs[preferredName]) return preferredName;
  return Object.keys(tariffs)[0] ?? null;
};

export const getApiErrorMessage = (error, fallback) => {
  const detail = error?.response?.data?.detail;
  return typeof detail === "string" ? detail : fallback;
};

// Daty zakresu to napisy RRRR-MM-DD, więc można je porównywać leksykograficznie.
const MONTH_NAMES = [
  "styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec",
  "lipiec", "sierpień", "wrzesień", "październik", "listopad", "grudzień",
];
const QUARTER_NAMES = ["I", "II", "III", "IV"];

const pad = (value) => String(value).padStart(2, "0");

const lastDayOfMonth = (year, month) => new Date(Date.UTC(year, month, 0)).getUTCDate();

const clampRange = (from, to, bounds) => ({
  from: from < bounds.from ? bounds.from : from,
  to: to > bounds.to ? bounds.to : to,
});

export const countDays = ({ from, to }) =>
  Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000) + 1;

export const isSameRange = (a, b) => a?.from === b?.from && a?.to === b?.to;

// Zwraca komunikat błędu albo null, gdy zakres można zatwierdzić.
export const validateDateRange = ({ from, to }, bounds) => {
  if (!from || !to) return "Podaj datę początkową i końcową.";
  if (from > to) return "Data początkowa nie może być późniejsza niż data końcowa.";
  if (from < bounds.from || to > bounds.to) {
    return `Zakres musi mieścić się w okresie dostępnych danych (${formatDate(bounds.from)} – ${formatDate(bounds.to)}).`;
  }
  return null;
};

// Miesiące i kwartały, w których są dane; skrajne okresy przycinamy do granic danych.
export const buildQuickRanges = (bounds) => {
  const [startYear, startMonth] = bounds.from.split("-").map(Number);
  const [endYear, endMonth] = bounds.to.split("-").map(Number);
  const months = [];
  const quarters = [];

  for (let year = startYear, month = startMonth; year < endYear || (year === endYear && month <= endMonth); ) {
    const from = `${year}-${pad(month)}-01`;
    const to = `${year}-${pad(month)}-${pad(lastDayOfMonth(year, month))}`;
    months.push({ label: `${MONTH_NAMES[month - 1]} ${year}`, ...clampRange(from, to, bounds) });

    const quarter = Math.floor((month - 1) / 3);
    const quarterLabel = `${QUARTER_NAMES[quarter]} kw. ${year}`;
    if (quarters.at(-1)?.label !== quarterLabel) {
      const lastMonth = quarter * 3 + 3;
      quarters.push({
        label: quarterLabel,
        ...clampRange(
          `${year}-${pad(quarter * 3 + 1)}-01`,
          `${year}-${pad(lastMonth)}-${pad(lastDayOfMonth(year, lastMonth))}`,
          bounds,
        ),
      });
    }

    month += 1;
    if (month > 12) {
      month = 1;
      year += 1;
    }
  }

  return { months, quarters };
};

// Wyniki z pustego zakresu mają statystyki z zerową liczbą dni.
export const hasDataInRange = (results) => (results?.statistics?.days_analyzed ?? 1) > 0;
