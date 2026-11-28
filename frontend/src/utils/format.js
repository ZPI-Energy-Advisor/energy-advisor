// Wspólne formaty całej aplikacji (ZP-125): liczby pl-PL (przecinek dziesiętny, spacja tysięcy także w liczbach
// czterocyfrowych: „1 234,56”, bo domyślnie pl-PL pisze „1234,56”), kwoty, ceny,
// energia, procenty i daty. Ekrany nie formatują liczb ani dat same, tylko przez te funkcje.
const formatters = new Map();

const formatter = (minimumFractionDigits, maximumFractionDigits) => {
  const key = `${minimumFractionDigits}:${maximumFractionDigits}`;
  if (!formatters.has(key)) {
    formatters.set(key, new Intl.NumberFormat("pl-PL", { minimumFractionDigits, maximumFractionDigits, useGrouping: "always" }));
  }
  return formatters.get(key);
};

const MISSING = "—";
const isMissing = (value) => value == null || Number.isNaN(Number(value));

// Wartość, która przy `digits` miejscach i tak pokaże się jako zero (np. -0,001), jest zerem: bez „-0,00”.
// Resztę zaokrągla Intl (połówki w górę od zapisu dziesiętnego), a nie toFixed, które 0,615 daje jako 0,61.
const rounded = (value, digits) => {
  const number = Number(value);
  return Math.abs(number) < 0.5 / 10 ** digits ? 0 : number;
};

export const formatNumber = (value, digits = 2) =>
  isMissing(value) ? MISSING : formatter(digits, digits).format(rounded(value, digits));

// Podziałka osi: bez zbędnych zer (1,5 zamiast 1,50), z przecinkiem.
export const formatAxis = (value) => formatter(0, 2).format(value);

// Podpis jednostki na osi Y, jak na wykresie cen.
export const axisUnitLabel = (unit) => ({
  value: unit, angle: -90, position: "insideLeft", offset: 8, fontSize: 11, fill: "#94a3b8",
});

const withUnit = (value, digits, unit) => (isMissing(value) ? MISSING : `${formatNumber(value, digits)} ${unit}`);

/** Kwota: „1 234,56 zł”. */
export const formatPln = (value) => withUnit(value, 2, "zł");

/** Pełna cena kWh: „0,40 zł/kWh”. */
export const formatPrice = (value) => withUnit(value, 2, "zł/kWh");

/** Składnik ceny kWh (energia, dystrybucja, opłaty, VAT): „0,089 zł”; małe stawki potrzebują trzeciego miejsca. */
export const formatRate = (value) => withUnit(value, 3, "zł");

/** Energia: „12,34 kWh”. */
export const formatKwh = (value) => withUnit(value, 2, "kWh");

/** Moc: „2,50 kW”. */
export const formatKw = (value) => withUnit(value, 2, "kW");

/** Moc instalacji PV: „6,00 kWp”. */
export const formatKwp = (value) => withUnit(value, 2, "kWp");

/** Udział (0,123) jako procent: „12,3%”; całe procenty bez przecinka („4%”). */
export const formatPercent = (fraction) =>
  isMissing(fraction) ? MISSING : `${formatter(0, 1).format(rounded(Number(fraction) * 100, 1))}%`;

/** Temperatura: „21°C”, z `digits` miejscami: „21,5°C”. */
export const formatDegrees = (value, digits = 0) =>
  isMissing(value) ? MISSING : `${formatNumber(digits ? value : Math.round(value), digits)}°C`;

// ---- Daty i godziny ----
// Daty bez godziny (RRRR-MM-DD) czytamy wprost z tekstu, a momenty (ISO z godziną) pokazujemy w czasie polskim,
// niezależnie od strefy przeglądarki.
export const TIME_ZONE = "Europe/Warsaw";

const noon = (isoDate) => new Date(`${isoDate.slice(0, 10)}T12:00:00Z`);
const dateParts = (isoDate) => isoDate.slice(0, 10).split("-");

/** „27.11.2026” */
export const formatDate = (isoDate) => {
  if (!isoDate) return "";
  const [year, month, day] = dateParts(isoDate);
  return `${day}.${month}.${year}`;
};

/** „27.11” */
export const formatDayMonth = (isoDate) => {
  const [, month, day] = dateParts(isoDate);
  return `${day}.${month}`;
};

const dayWordsFormat = new Intl.DateTimeFormat("pl-PL", { timeZone: TIME_ZONE, day: "numeric", month: "long" });
const dayWordsYearFormat = new Intl.DateTimeFormat("pl-PL", {
  timeZone: TIME_ZONE, day: "numeric", month: "long", year: "numeric",
});
const weekdayFormat = new Intl.DateTimeFormat("pl-PL", { timeZone: TIME_ZONE, weekday: "long" });

/** „27 listopada” */
export const formatDayWords = (isoDate) => dayWordsFormat.format(noon(isoDate));
/** „27 listopada 2026” */
export const formatDayWordsYear = (isoDate) => dayWordsYearFormat.format(noon(isoDate));
/** „piątek, 27 listopada” */
export const formatWeekdayDay = (isoDate) => `${weekdayFormat.format(noon(isoDate))}, ${formatDayWords(isoDate)}`;
/** „piątek, 27 listopada 2026” */
export const formatWeekdayDayYear = (isoDate) => `${weekdayFormat.format(noon(isoDate))}, ${formatDayWordsYear(isoDate)}`;

const timeFormat = new Intl.DateTimeFormat("pl-PL", { timeZone: TIME_ZONE, hour: "2-digit", minute: "2-digit" });
const dateTimeFormat = new Intl.DateTimeFormat("pl-PL", {
  timeZone: TIME_ZONE, day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
});

// Backend zapisuje część momentów w UTC bez strefy (np. data wgrania pliku); dopisujemy wtedy „Z”.
const moment = (iso) => new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);

/** Godzina momentu w czasie polskim: „14:30”. */
export const formatTime = (iso) => timeFormat.format(moment(iso));

/** Data i godzina momentu w czasie polskim: „27.11.2026, 14:30”. */
export const formatDateTime = (iso) => (iso ? dateTimeFormat.format(moment(iso)) : MISSING);

/** Rozmiar pliku: „1,25 MB”. */
export const formatMegabytes = (bytes) => withUnit(bytes / 1024 / 1024, 2, "MB");
