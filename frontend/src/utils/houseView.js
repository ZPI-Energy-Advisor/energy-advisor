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

/** Urządzenie pracuje w przebiegu z pozycji planu (przebieg z historii dnia referencyjnego ma `ref`). */
export const isPlanControlled = (device) => Boolean(device.run && !device.run.ref);

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
