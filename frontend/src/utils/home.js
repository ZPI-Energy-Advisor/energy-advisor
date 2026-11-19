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

// Pomieszczenia (`room`) jak w docs/devices-file-format.md; backend podaje pomieszczenie z pliku albo domyślne.
export const ROOM_LABELS = {
  kitchen: "Kuchnia",
  living_room: "Salon",
  bedroom: "Sypialnia",
  bathroom: "Łazienka",
  laundry: "Pralnia",
  office: "Gabinet",
  technical: "Pomieszczenie techniczne",
  garage: "Garaż",
  roof: "Dach",
  other: "Inne",
};

export const FLEXIBILITY_LABELS = {
  fixed: { label: "Stały", hint: "O pracy decyduje domownik albo słońce" },
  shiftable: { label: "Przesuwalny", hint: "Optymalizacja może przesunąć start" },
  interruptible: { label: "Przerywalny", hint: "Optymalizacja może rozłożyć pracę na kwadranse" },
};

// Tempo zegara huba: sekundy symulacji na sekundę rzeczywistą. Progi suwaka od wolnego (oglądanie jednego
// programu) do „doba w minutę”; szybciej kwadrans symulacji trwałby dla huba ułamek sekundy.
export const SPEED_STEPS = [
  { value: 15, label: "kwadrans w minutę" },
  { value: 30, label: "pół godziny w minutę" },
  { value: 60, label: "godzina w minutę" },
  { value: 120, label: "doba w 12 min" },
  { value: 288, label: "doba w 5 min" },
  { value: 480, label: "doba w 3 min" },
  { value: 720, label: "doba w 2 min" },
  { value: 1440, label: "doba w minutę" },
];

/** Próg suwaka najbliższy tempu (w skali logarytmicznej), także dla tempa ustawionego poza ekranem. */
export const nearestSpeedStep = (speed) => {
  if (speed == null || speed <= 0) return SPEED_STEPS.findIndex((step) => step.value === 288);
  let best = 0;
  SPEED_STEPS.forEach((step, index) => {
    if (Math.abs(Math.log(step.value / speed)) < Math.abs(Math.log(SPEED_STEPS[best].value / speed))) best = index;
  });
  return best;
};

/** Podpis tempa: nazwa progu albo, dla tempa spoza progów, „doba w X min”. */
export const speedLabel = (speed) => {
  const step = SPEED_STEPS.find((item) => item.value === speed);
  if (step) return step.label;
  const seconds = 86400 / speed;
  return seconds < 60 ? `doba w ${Math.round(seconds)} s` : `doba w ${formatNumber(seconds / 60, 0)} min`;
};

/** Czas rzeczywisty jako „ok. 40 s”, „ok. 6 min” albo „ok. 1 h 10 min”. */
export const realDuration = (seconds) => {
  if (seconds < 60) return `ok. ${Math.max(1, Math.round(seconds))} s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `ok. ${minutes} min`;
  const rest = minutes % 60;
  return `ok. ${Math.floor(minutes / 60)} h${rest ? ` ${rest} min` : ""}`;
};

const isProducing = (device) => device.power_kw != null && device.power_kw < 0;

/**
 * Przebieg z własnym profilem (`run`): akcja z historii dnia referencyjnego ma `ref` (action_id z pliku),
 * np. PV albo pompa ciepła odznaczona w planie, a pozycja planu idzie bez `ref`.
 */
export const runLabel = (run) => (run.ref ? "Jak w historii" : "Według planu");

export const deviceStateLabel = (device) => {
  switch (device.state) {
    case "running":
      if (isProducing(device)) return "Produkuje";
      if (device.run) return runLabel(device.run);
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

// Urządzenia bez przycisków na ekranie: instalacja PV pracuje według słońca.
const UNCONTROLLED_TYPES = new Set(["pv_inverter"]);
export const hasControls = (device) => !UNCONTROLLED_TYPES.has(device.device_type);

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

export const formatSimTime = (iso) => timeFormat.format(new Date(iso));
export const formatSimDate = (iso) => dateFormat.format(new Date(iso));

export const durationLabel = (minutes) => {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (!hours) return `${rest} min`;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
};

// Doba RRRR-MM-DD (doba planu, dzień referencyjny) słowami; południe UTC to ten sam dzień w strefie domu.
// Bez dnia tygodnia tam, gdzie po „na” / „jak” wymagałby odmiany („w niedzielę”), której Intl nie daje.
const noon = (day) => new Date(`${day}T12:00:00Z`);
const shortDayFormat = new Intl.DateTimeFormat("pl-PL", { timeZone: HOME_TIMEZONE, day: "numeric", month: "long" });
const fullDayFormat = new Intl.DateTimeFormat("pl-PL", {
  timeZone: HOME_TIMEZONE, day: "numeric", month: "long", year: "numeric",
});
/** „19 października” */
export const shortDay = (day) => shortDayFormat.format(noon(day));
/** „19 października 2026” */
export const fullDay = (day) => fullDayFormat.format(noon(day));
/** „niedziela, 19 października 2026” */
export const weekdayDay = (day) => dateFormat.format(noon(day));

/**
 * Oszczędność przebiegu planu, jednakowo w pasku zegara i na liście raportów: „oszczędność 7,22 zł (43,4%)”,
 * z dopiskiem „niepełny” dla raportu sprzed końca planu. Przyjmuje rachunek albo wiersz historii.
 */
export const savingSummary = ({ saving, saving_percent: percent, complete }) =>
  `oszczędność ${formatPln(saving)}${percent == null ? "" : ` (${formatNumber(percent, 1)}%)`}${complete ? "" : ", niepełny"}`;

const planWindow = (actions) => actions.map((action) => `${formatSimTime(action.start)}–${formatSimTime(action.end)}`).join(", ");

/** Stan pozycji planu względem czasu symulacji; `actions` bez odrzuconych (te się nie wykonają). */
const planState = (actions, now) => {
  if (!now) return { state: "zaplanowane", tone: "neutral" };
  // „wykonane”, a nie „gotowe”: „Gotowe” to już stan urządzenia czekającego na program.
  if (actions.every((action) => new Date(action.end) <= now)) return { state: "wykonane", tone: "ready" };
  if (actions.some((action) => new Date(action.start) <= now && now < new Date(action.end))) {
    return { state: "w trakcie", tone: "active" };
  }
  return { state: "czeka", tone: "neutral" };
};

/**
 * Urządzenia z planu, które przestały go wykonywać: device_id -> „awaria” albo „przerwane ręcznie”. Z odchyleń
 * rachunku, a w przebiegu bez rachunku z awarii urządzeń. Awaria ma pierwszeństwo przed ręcznym wyłączeniem.
 */
const stoppedDevices = (run) => {
  const stopped = {};
  const deviations = run.cost?.deviations ?? (run.errors ?? []).map((error) => ({ ...error, kind: "device_error" }));
  for (const deviation of deviations) {
    if (deviation.kind === "device_error") stopped[deviation.device_id] = "awaria";
    else if (deviation.kind === "interrupted" && !stopped[deviation.device_id]) {
      stopped[deviation.device_id] = "przerwane ręcznie";
    }
  }
  return stopped;
};

/**
 * Plakietki przy urządzeniach z planu w trakcie przebiegu (ZP-114): device_id -> { text, tone }.
 * Godziny i stan („czeka”, „w trakcie”, „wykonane”) liczymy z akcji, które hub przyjął; urządzenie z samymi
 * odrzuconymi komendami dostaje „odrzucone”, a po awarii lub ręcznym wyłączeniu „awaria” / „przerwane ręcznie”
 * zamiast stanu z zegara. Urządzenia z historii (PV, pompa spoza planu) plakietki nie mają:
 * ich stan („Jak w historii”, „Produkuje”) jest już na liście, a dzień referencyjny w raporcie.
 */
export const planBadges = (run) => {
  if (!run || run.status !== "running") return {};
  const now = run.sim_time ? new Date(run.sim_time) : null;
  const stopped = stoppedDevices(run);
  const badges = {};
  for (const device of run.devices) {
    if (!device.actions.length) continue;
    const accepted = device.actions.filter((action) => action.status !== "rejected");
    if (!accepted.length) {
      badges[device.device_id] = { text: `Plan ${planWindow(device.actions)} · odrzucone`, tone: "error" };
      continue;
    }
    if (stopped[device.device_id]) {
      badges[device.device_id] = { text: `Plan ${planWindow(accepted)} · ${stopped[device.device_id]}`, tone: "error" };
      continue;
    }
    const { state, tone } = planState(accepted, now);
    badges[device.device_id] = { text: `Plan ${planWindow(accepted)} · ${state}`, tone };
  }
  return badges;
};

// Doba chwili symulacji jako RRRR-MM-DD w strefie domu.
const isoDayFormat = new Intl.DateTimeFormat("en-CA", { timeZone: HOME_TIMEZONE });
const simDay = (iso) => isoDayFormat.format(new Date(iso));

/**
 * Okres bilansu z `today` (GET /home/state): w zwykłej dobie od północy, w przebiegu planu od jego początku.
 * Ta sama doba: „20 listopada, 00:00–19:00”; przebieg przez północ: „20 listopada 00:00 – 21 listopada 06:00”.
 */
export const periodLabel = (today) => {
  const startDay = simDay(today.day_start);
  const endDay = simDay(today.until);
  if (startDay === endDay) return `${shortDay(startDay)}, ${formatSimTime(today.day_start)}–${formatSimTime(today.until)}`;
  return `${shortDay(startDay)} ${formatSimTime(today.day_start)} – ${shortDay(endDay)} ${formatSimTime(today.until)}`;
};
