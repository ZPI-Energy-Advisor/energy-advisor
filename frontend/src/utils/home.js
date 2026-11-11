// Ekran „Mój dom”: etykiety i formatowanie stanu domu z GET /home/state (kontrakt: docs/smart-home-api.md).

export const HOME_TIMEZONE = "Europe/Warsaw";

// Kolejność i nazwy kategorii jak w docs/devices-file-format.md.
export const CATEGORY_ORDER = ["OZE", "AGD", "Ogrzewanie", "Pojazd elektryczny", "Oświetlenie", "RTV/IT", "Inne"];
const UNKNOWN_CATEGORY = "Pozostałe";

export const DEVICE_TYPE_LABELS = {
  washing_machine: "Pralka",
  tumble_dryer: "Suszarka do ubrań",
  dishwasher: "Zmywarka",
  fridge: "Lodówka",
  freezer: "Zamrażarka",
  induction_hob: "Płyta indukcyjna",
  oven: "Piekarnik",
  microwave: "Kuchenka mikrofalowa",
  kettle: "Czajnik",
  coffee_machine: "Ekspres do kawy",
  vacuum_cleaner: "Odkurzacz",
  heat_pump: "Pompa ciepła",
  electric_heater: "Grzejnik elektryczny",
  water_heater: "Podgrzewacz wody",
  ventilation: "Rekuperator / wentylacja",
  pv_inverter: "Instalacja PV",
  light: "Oświetlenie",
  tv: "Telewizor",
  computer: "Komputer",
  router: "Router",
  ev_charger: "Ładowarka EV",
  hair_dryer: "Suszarka do włosów",
  other: "Inne urządzenie",
};

export const FLEXIBILITY_LABELS = {
  fixed: { label: "Stały", hint: "O pracy decyduje domownik albo słońce" },
  shiftable: { label: "Przesuwalny", hint: "Optymalizacja może przesunąć start" },
  interruptible: { label: "Przerywalny", hint: "Optymalizacja może rozłożyć pracę na kwadranse" },
};

// Tempo zegara huba: sekundy symulacji na sekundę rzeczywistą.
export const SPEED_OPTIONS = [
  { value: 60, label: "1 h w minutę" },
  { value: 288, label: "Doba w 5 min" },
  { value: 1440, label: "Doba w minutę" },
];

export const speedOptions = (current) =>
  current == null || SPEED_OPTIONS.some((option) => option.value === current)
    ? SPEED_OPTIONS
    : [...SPEED_OPTIONS, { value: current, label: `${formatNumber(current, 0)}× szybciej` }].sort((a, b) => a.value - b.value);

const isProducing = (device) => device.power_kw != null && device.power_kw < 0;

export const deviceStateLabel = (device) => {
  switch (device.state) {
    case "running":
      if (isProducing(device)) return "Produkuje";
      return device.program_id ? "Program w toku" : "Pracuje";
    case "idle":
      return "Gotowe";
    case "off":
      return "Wyłączone";
    case "error":
      return "Awaria";
    case "unreachable":
      return "Brak połączenia";
    default:
      return device.state;
  }
};

export const deviceStateTone = (state) =>
  ({ running: "active", idle: "ready", error: "error", unreachable: "error" })[state] ?? "neutral";

export const isControllable = (device) => device.state !== "error" && device.state !== "unreachable";

export const programName = (device, programId) =>
  device.programs?.find((program) => program.program_id === programId)?.program_name ?? programId;

/** Urządzenia pogrupowane po kategorii w stałej kolejności, w grupie po nazwie. */
export const groupDevicesByCategory = (devices) => {
  const groups = new Map();
  for (const device of devices) {
    const category = device.device_category ?? UNKNOWN_CATEGORY;
    if (!groups.has(category)) groups.set(category, []);
    groups.get(category).push(device);
  }
  const rank = (category) => {
    const index = CATEGORY_ORDER.indexOf(category);
    return index === -1 ? CATEGORY_ORDER.length : index;
  };
  return [...groups.entries()]
    .sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b, "pl"))
    .map(([category, items]) => ({
      category,
      devices: [...items].sort((a, b) => a.device_name.localeCompare(b.device_name, "pl")),
    }));
};

const numberFormats = new Map();

export const formatNumber = (value, digits = 2) => {
  if (!numberFormats.has(digits)) {
    numberFormats.set(digits, new Intl.NumberFormat("pl-PL", { minimumFractionDigits: digits, maximumFractionDigits: digits }));
  }
  // + 0 zamienia -0 na 0, żeby nie pokazywać „-0,00”.
  return numberFormats.get(digits).format(value + 0);
};

export const formatKw = (value) => (value == null ? "—" : `${formatNumber(value)} kW`);
export const formatKwh = (value) => (value == null ? "—" : `${formatNumber(value)} kWh`);
export const formatPln = (value) => (value == null ? "—" : `${formatNumber(value)} zł`);

const timeFormat = new Intl.DateTimeFormat("pl-PL", { timeZone: HOME_TIMEZONE, hour: "2-digit", minute: "2-digit" });
const dateFormat = new Intl.DateTimeFormat("pl-PL", {
  timeZone: HOME_TIMEZONE,
  weekday: "long",
  day: "numeric",
  month: "long",
  year: "numeric",
});
const isoDateFormat = new Intl.DateTimeFormat("en-CA", { timeZone: HOME_TIMEZONE });

export const formatSimTime = (iso) => timeFormat.format(new Date(iso));
export const formatSimDate = (iso) => dateFormat.format(new Date(iso));
/** Doba symulacji jako RRRR-MM-DD w strefie domu (wartość pola daty). */
export const simDay = (iso) => isoDateFormat.format(new Date(iso));

export const durationLabel = (minutes) => {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (!hours) return `${rest} min`;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
};
