// Wspólne klasy interfejsu (ZP-125): przyciski, karty, komunikaty i tabele wyglądają tak samo na każdym ekranie.
// Klasy stosujemy wprost na elementach (<button>, <Link> wyglądający jak przycisk, <div> karty).

const BUTTON_BASE =
  "inline-flex items-center justify-center gap-2 rounded-md font-semibold transition-colors " +
  "focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 focus-visible:ring-offset-1 " +
  "disabled:cursor-not-allowed disabled:opacity-50";

const BUTTON_VARIANTS = {
  primary: "bg-emerald-600 text-white hover:bg-emerald-700 active:bg-emerald-800",
  secondary: "border border-gray-300 bg-white text-gray-700 hover:bg-gray-50",
  danger: "bg-red-600 text-white hover:bg-red-700",
  dangerOutline: "border border-red-200 bg-white text-red-600 hover:bg-red-50",
};

const BUTTON_SIZES = {
  sm: "px-3 py-1.5 text-sm",
  md: "px-4 py-2 text-sm",
  lg: "px-5 py-3 text-base",
};

/** Klasy przycisku: `buttonClass("secondary", "lg")`. */
export const buttonClass = (variant = "primary", size = "md") =>
  `${BUTTON_BASE} ${BUTTON_VARIANTS[variant]} ${BUTTON_SIZES[size]}`;

export const PRIMARY_BUTTON = buttonClass("primary");
export const SECONDARY_BUTTON = buttonClass("secondary");
// Przycisk z samą ikoną (strzałki poprzedni / następny dzień); opis podaje aria-label.
export const ICON_BUTTON =
  "inline-flex items-center justify-center rounded-md border border-gray-300 bg-white p-2 text-gray-700 " +
  "hover:bg-gray-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 disabled:cursor-not-allowed disabled:opacity-40";

// Link tekstowy w kolorze akcji (np. „Porównaj taryfy”, „Dodaj przedział”).
export const LINK_BUTTON =
  "inline-flex items-center gap-1 text-sm font-medium text-emerald-700 hover:text-emerald-800 hover:underline " +
  "disabled:opacity-40 disabled:no-underline";

export const CARD = "rounded-lg border border-gray-200 bg-white p-4 shadow-sm md:p-6";
// Karta bez odstępu w środku: tabela albo lista przy krawędziach karty.
export const CARD_FLUSH = "rounded-lg border border-gray-200 bg-white shadow-sm";
// Kafelek z kwotą lub liczbą i kolorowym paskiem u góry i dołu; kolor paska podaje ekran (np. border-y-emerald-500).
export const STAT_CARD = "rounded-lg border-x border-x-gray-200 border-y-4 bg-white p-5 shadow-sm md:p-6";
// Pusty stan ekranu: brak pliku, brak danych w okresie.
export const EMPTY_CARD = "rounded-lg border border-emerald-100 bg-white p-8 text-center shadow-sm md:p-10";

const ALERT_TONES = {
  error: "border-red-200 bg-red-50 text-red-700",
  warning: "border-amber-200 bg-amber-50 text-amber-900",
  info: "border-gray-200 bg-gray-50 text-gray-700",
  success: "border-emerald-200 bg-emerald-50 text-emerald-800",
};

export const alertClass = (tone = "error") => `rounded-lg border p-3 text-sm ${ALERT_TONES[tone]}`;

// Tabela: przewijana w poziomie na telefonie, z jednakowym nagłówkiem i komórkami; liczby i kwoty do prawej.
export const TABLE_WRAPPER = "overflow-x-auto";
export const TABLE = "min-w-full divide-y divide-gray-200 text-sm";
// Tabela z długimi godzinami (plan, optymalizacja): na telefonie przewija się w poziomie zamiast łamać kolumny.
export const WIDE_TABLE = `${TABLE} min-w-[44rem]`;
export const TABLE_HEAD = "bg-gray-50";
export const TABLE_BODY = "divide-y divide-gray-100 bg-white";
export const TH = "whitespace-nowrap px-3 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500 md:px-4";
export const TH_NUMBER = `${TH} text-right`;
export const TD = "px-3 py-3 text-gray-700 md:px-4";
export const TD_NUMBER = `${TD} whitespace-nowrap text-right tabular-nums`;
