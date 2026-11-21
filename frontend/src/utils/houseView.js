// Widok domu na ekranie „Mój dom”: rozmieszczenie urządzeń w przekroju budynku i wygląd ich stanu.
// Czyste funkcje bez Reacta, żeby dało się je testować bez renderowania SVG.
import { ROOM_LABELS, deviceStateLabel } from "./home";

/**
 * Rozmiar przekroju w jednostkach viewBox SVG. Kalenica dachu spadzistego wystaje ponad pomieszczenia,
 * więc widok zaczyna się od `HOUSE_TOP` (ujemnego), a pomieszczenia zostają w swoich współrzędnych.
 */
export const HOUSE_TOP = -56;
export const HOUSE_WIDTH = 1080;
export const HOUSE_HEIGHT = 486;
export const GROUND_Y = 466;

/** Pomieszczenie, do którego trafia urządzenie bez pomieszczenia albo z pomieszczeniem spoza słownika. */
export const FALLBACK_ROOM = "other";

/**
 * Pomieszczenia ze słownika `room` (docs/devices-file-format.md) jako prostokąty przekroju.
 * Dom z dachem spadzistym: dwie kondygnacje, dach z PV i garaż obok. Między pomieszczeniami
 * zostaje szczelina, która rysuje się jako ściana. „Inne” stoi przy wejściu (przedpokój, ogród).
 */
export const HOUSE_ROOMS = [
  { id: "roof", x: 420, y: 6, w: 140, h: 92, floor: "roof" },
  { id: "bedroom", x: 140, y: 118, w: 246, h: 150, floor: 1 },
  { id: "bathroom", x: 392, y: 118, w: 242, h: 150, floor: 1 },
  { id: "office", x: 640, y: 118, w: 240, h: 150, floor: 1 },
  { id: "other", x: 140, y: 274, w: 128, h: 184, floor: 0 },
  { id: "living_room", x: 274, y: 274, w: 196, h: 184, floor: 0 },
  { id: "kitchen", x: 476, y: 274, w: 210, h: 184, floor: 0 },
  { id: "laundry", x: 692, y: 274, w: 72, h: 184, floor: 0 },
  { id: "technical", x: 770, y: 274, w: 110, h: 184, floor: 0 },
  { id: "garage", x: 900, y: 330, w: 160, h: 128, floor: 0 },
];

const ROOM_IDS = new Set(HOUSE_ROOMS.map((room) => room.id));

/**
 * Pomieszczenia do narysowania. Pralnia bez urządzeń znika, a pomieszczenie techniczne zajmuje jej miejsce:
 * pralka i suszarka bez pola `room` stoją w łazience (ZP-109), więc w zwykłym pliku pralnia byłaby pusta.
 */
export const houseRooms = (placed) => {
  if (placed.get("laundry")?.length) return HOUSE_ROOMS;
  const laundry = HOUSE_ROOMS.find((room) => room.id === "laundry");
  return HOUSE_ROOMS.filter((room) => room.id !== "laundry").map((room) =>
    room.id === "technical" ? { ...room, x: laundry.x, w: room.x + room.w - laundry.x } : room,
  );
};

// Słownik backendu nazywa pomieszczenie techniczne pełną nazwą, w przekroju brakuje na nią miejsca.
const SHORT_ROOM_LABELS = { technical: "Techniczne" };
export const roomLabel = (roomId) => SHORT_ROOM_LABELS[roomId] ?? ROOM_LABELS[roomId] ?? roomId;

export const roomOf = (device) => (ROOM_IDS.has(device.room) ? device.room : FALLBACK_ROOM);

/** Urządzenia według pomieszczeń przekroju, w pomieszczeniu po nazwie; puste pomieszczenia mają pustą listę. */
export const placeDevicesInRooms = (devices) => {
  const rooms = new Map(HOUSE_ROOMS.map((room) => [room.id, []]));
  for (const device of devices) rooms.get(roomOf(device)).push(device);
  for (const items of rooms.values()) items.sort((a, b) => a.device_name.localeCompare(b.device_name, "pl"));
  return rooms;
};

// Komórka urządzenia: ikona z podpisem pod nią. Pomieszczenie zmniejsza komórki, gdy urządzeń jest dużo.
export const CELL = { w: 48, h: 60, icon: 34 };
const ROOM_LABEL_H = 26;
const ROOM_PADDING = 6;

/**
 * Pozycje urządzeń w pomieszczeniu: siatka komórek wyśrodkowana pod nazwą pomieszczenia.
 * Skala maleje do połowy, aż wszystkie komórki się zmieszczą.
 */
export const layoutRoom = (room, count) => {
  if (!count) return [];
  const width = room.w - 2 * ROOM_PADDING;
  const height = room.h - ROOM_LABEL_H - ROOM_PADDING;
  let scale = 1;
  let cols = 1;
  for (; scale > 0.5; scale = Math.round((scale - 0.05) * 100) / 100) {
    cols = Math.max(1, Math.min(count, Math.floor(width / (CELL.w * scale))));
    if (Math.ceil(count / cols) * CELL.h * scale <= height) break;
  }
  const cellW = CELL.w * scale;
  const cellH = CELL.h * scale;
  const left = room.x + (room.w - cols * cellW) / 2;
  const top = room.y + ROOM_LABEL_H;
  return Array.from({ length: count }, (_, index) => ({
    x: left + (index % cols) * cellW,
    y: top + Math.floor(index / cols) * cellH,
    w: cellW,
    h: cellH,
    icon: CELL.icon * scale,
  }));
};

/** Kolor kategorii z pliku urządzeń; nieznana kategoria dostaje szary. */
export const CATEGORY_COLORS = {
  OZE: "#10b981",
  AGD: "#3b82f6",
  Ogrzewanie: "#f97316",
  "Pojazd elektryczny": "#8b5cf6",
  Oświetlenie: "#f59e0b",
  "RTV/IT": "#06b6d4",
  Inne: "#64748b",
};
const UNKNOWN_COLOR = "#64748b";
export const categoryColor = (category) => CATEGORY_COLORS[category] ?? UNKNOWN_COLOR;

const ERROR_COLOR = "#ef4444";

/**
 * Wygląd urządzenia według stanu. Kolor nie jest jedynym nośnikiem: `glyph` to ikona stanu w rogu,
 * a `label` to tekst stanu (w podpisie dla czytników ekranu, w dymku i w legendzie).
 *
 * - wyłączone: jasnoszare, bez koloru kategorii,
 * - gotowe: białe z obrysem w kolorze kategorii,
 * - pracujące: wypełnione kolorem kategorii z pulsującą poświatą,
 * - awaria i brak połączenia: czerwone.
 */
export const deviceAppearance = (device) => {
  const color = categoryColor(device.device_category);
  const label = deviceStateLabel(device);
  switch (device.state) {
    case "running":
      return { tone: "active", glyph: "running", label, fill: color, stroke: color, icon: "#ffffff", animated: true };
    case "idle":
      return { tone: "ready", glyph: "ready", label, fill: "#ffffff", stroke: color, icon: color, animated: false };
    case "error":
      return { tone: "error", glyph: "error", label, fill: "#fef2f2", stroke: ERROR_COLOR, icon: "#dc2626", animated: false };
    case "unreachable":
      return { tone: "error", glyph: "unreachable", label, fill: "#fef2f2", stroke: ERROR_COLOR, icon: "#dc2626", animated: false };
    default:
      return { tone: "off", glyph: "off", label, fill: "#f1f5f9", stroke: "#e2e8f0", icon: "#94a3b8", animated: false };
  }
};

/**
 * Kolor znaczka „według planu” ze stanu pozycji planu (`planBadges` z utils/home): w trakcie zielony,
 * wykonane niebieskie, czeka szary, odrzucone, awaria albo przerwane czerwone. To samo źródło co widok listy,
 * więc znaczek mają też urządzenia z programem (pralka, zmywarka), które plan uruchamia przez start_program.
 */
export const PLAN_BADGE_COLORS = { active: "#10b981", ready: "#0ea5e9", neutral: "#94a3b8", error: "#ef4444" };
export const planBadgeColor = (badge) => PLAN_BADGE_COLORS[badge?.tone] ?? PLAN_BADGE_COLORS.neutral;

/** Pomieszczenie jest rozjaśnione, gdy świeci w nim choć jedno oświetlenie. */
export const isRoomLit = (devices) => devices.some((device) => device.device_type === "light" && device.state === "running");

export const isProducingPv = (device) => device.device_type === "pv_inverter" && device.power_kw != null && device.power_kw < 0;

// Poniżej 10 W bilans traktujemy jako zerowy, żeby strzałka nie migała przy zaokrągleniach.
const BALANCE_EPSILON_KW = 0.01;

/**
 * Licznik przy wejściu: kierunek przepływu energii z bilansu mocy (`power.net_kw`, ujemny = oddawanie).
 * `null` bez danych o mocy (hub niedostępny).
 */
export const gridFlow = (power) => {
  if (power?.net_kw == null) return null;
  const kw = Math.abs(power.net_kw);
  if (kw < BALANCE_EPSILON_KW) return { direction: "none", kw: 0, label: "Bilans zerowy" };
  return power.net_kw > 0
    ? { direction: "import", kw, label: "Pobór z sieci" }
    : { direction: "export", kw, label: "Oddawanie do sieci" };
};

/**
 * Sesja ładowania auta: stan baterii nie przychodzi ze stanu domu, więc pasek pokazuje postęp sesji
 * według zegara symulacji, gdy przebieg ma koniec (`run.ends_at`). Ładowanie włączone ręcznie
 * (bez końca) ma `fraction: null`, a wyłączona ładowarka nie ma sesji (`null`).
 */
export const evSession = (device, simTime) => {
  if (device.device_type !== "ev_charger" || device.state !== "running") return null;
  const start = Date.parse(device.run?.started_at);
  const end = Date.parse(device.run?.ends_at);
  const now = Date.parse(simTime);
  if (!Number.isFinite(start) || !Number.isFinite(end) || !Number.isFinite(now) || end <= start) {
    return { fraction: null, endsAt: device.run?.ends_at ?? null };
  }
  const fraction = Math.min(1, Math.max(0, (now - start) / (end - start)));
  return { fraction, endsAt: device.run.ends_at };
};

const QUARTER_MS = 15 * 60 * 1000;
const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;
// Podziałka paska czasu co 6 h (00:00, 06:00, 12:00, 18:00), także przez północ planu.
const TICK_HOURS = 6;

/**
 * Poziom ceny kwadransu względem cen całego planu, z jej pozycji wśród nich: najtańsza trzecia część to tanio,
 * najdroższa drogo. Gdy wszystkie ceny są równe (np. G11), każda jest „średnio”.
 */
export const priceLevels = (prices) => {
  const sorted = prices.map((entry) => entry.price_pln_kwh).sort((a, b) => a - b);
  if (!sorted.length || sorted[0] === sorted[sorted.length - 1]) return () => (sorted.length ? "mid" : null);
  const last = sorted.length - 1;
  return (price) => {
    const below = sorted.filter((value) => value < price).length;
    const equal = sorted.filter((value) => value === price).length;
    // Środek pozycji ceny w posortowanej liście (powtórzona cena ma jedną pozycję), od 0 do 1.
    const position = (below + Math.max(0, equal - 1) / 2) / last;
    if (position <= 1 / 3) return "cheap";
    if (position >= 2 / 3) return "expensive";
    return "mid";
  };
};

export const PRICE_LEVEL_LABELS = { cheap: "tanio", mid: "średnio", expensive: "drogo" };

/** Wpis z listy `{ start, ... }` dla kwadransu, w którym jest chwila `simTime` (ostatni o starcie nie później). */
const entryAt = (entries, simTime) => {
  const now = Date.parse(simTime);
  if (!Number.isFinite(now)) return null;
  let found = null;
  for (const entry of entries ?? []) {
    const start = Date.parse(entry.start);
    if (start <= now && now < start + QUARTER_MS) return entry;
    if (start <= now) found = entry;
  }
  return found && now < Date.parse(found.start) + QUARTER_MS ? found : null;
};

/** Ceny od tej chwili są przybliżone: noc po dniu planu dostała ceny z tych samych godzin dnia planu. */
const isApproximate = (run, ms) => {
  const from = Date.parse(run?.prices_approximate_from);
  return Number.isFinite(from) && ms >= from;
};

/** Cena kwadransu teraz z poziomem względem cen planu; null bez przebiegu planu albo poza jego zakresem. */
export const priceNow = (run, simTime) => {
  const entry = entryAt(run?.prices, simTime);
  if (!entry) return null;
  return {
    price: entry.price_pln_kwh,
    level: priceLevels(run.prices)(entry.price_pln_kwh),
    approximate: isApproximate(run, Date.parse(entry.start)),
  };
};

/**
 * Temperatura wody bojlerów według planu w chwili `simTime`: wartość z końca bieżącego kwadransu planu.
 * To przebieg zaplanowany, a nie zmierzony (hub nie liczy temperatury), więc ekran podpisuje go „wg planu”.
 */
export const waterTemperaturesNow = (run, simTime) =>
  (run?.water_heaters ?? [])
    .map((heater) => ({ deviceId: heater.device_id, name: heater.device_name, entry: entryAt(heater.temperatures, simTime) }))
    .filter((heater) => heater.entry)
    .map(({ deviceId, name, entry }) => ({ deviceId, name, tempC: entry.temp_c }));

const clockParts = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Warsaw", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});
/** Minuty od północy w strefie domu. */
const localMinutes = (ms) => {
  const parts = Object.fromEntries(clockParts.formatToParts(ms).map((part) => [part.type, part.value]));
  return Number(parts.hour) * 60 + Number(parts.minute);
};

/**
 * Pasek czasu nad przekrojem: zakres planu (doba planu i noc do 06:00) albo, bez przebiegu planu, doba zegara.
 * Pozycje są ułamkami szerokości paska (0–1): kreska „teraz”, odcinki cen planu z poziomem i starty pozycji planu.
 */
export const simTimeline = (run, simTime) => {
  const now = Date.parse(simTime);
  if (!Number.isFinite(now)) return null;
  let start = Date.parse(run?.horizon_start);
  let end = Date.parse(run?.horizon_end);
  const planned = Number.isFinite(start) && Number.isFinite(end) && end > start && now >= start && now <= end;
  if (!planned) {
    // Doba zegara od północy w strefie domu (zegar huba stoi zawsze na pełnym kwadransie).
    start = now - localMinutes(now) * 60000;
    end = start + DAY_MS;
  }
  const span = end - start;
  const at = (ms) => Math.min(1, Math.max(0, (ms - start) / span));
  const level = planned ? priceLevels(run.prices ?? []) : () => null;
  const prices = planned
    ? (run.prices ?? [])
        .map((entry) => ({ from: Date.parse(entry.start), price: entry.price_pln_kwh }))
        .filter((entry) => entry.from >= start && entry.from < end)
        .map((entry) => ({ from: at(entry.from), to: at(entry.from + QUARTER_MS), level: level(entry.price) }))
    : [];
  const markers = planned
    ? (run.devices ?? []).flatMap((device) =>
        device.actions
          .filter((action) => action.status !== "rejected")
          .map((action) => ({ at: at(Date.parse(action.start)), name: device.device_name, start: action.start })),
      )
    : [];
  const ticks = [];
  for (let ms = Math.ceil(start / HOUR_MS) * HOUR_MS; ms <= end; ms += HOUR_MS) {
    if (localMinutes(ms) % (TICK_HOURS * 60) === 0) ticks.push({ at: at(ms), time: ms });
  }
  const approximateFrom =
    planned && Number.isFinite(Date.parse(run.prices_approximate_from)) ? at(Date.parse(run.prices_approximate_from)) : null;
  return { planned, start, end, now: at(now), prices, markers, ticks, approximateFrom };
};
