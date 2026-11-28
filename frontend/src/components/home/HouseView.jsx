import { useEffect, useId, useState } from "react";
import { createPortal } from "react-dom";
import { LuArrowLeft, LuArrowRight, LuCalendarCheck, LuZap } from "react-icons/lu";
import {
  GROUND_Y,
  HOUSE_HEIGHT,
  HOUSE_TOP,
  HOUSE_WIDTH,
  deviceAppearance,
  evCharge,
  gridFlow,
  houseRooms,
  isProducingPv,
  isRoomLit,
  layoutRoom,
  placeDevicesInRooms,
  planBadgeColor,
  roomLabel,
} from "../../utils/houseView";
import HouseDevicePopover from "./HouseDevicePopover";
import HouseRooms from "./HouseRooms";
import LiveIndicators from "./LiveIndicators";
import HouseTimeline from "./HouseTimeline";
import { DEVICE_ICONS, STATE_GLYPHS } from "./houseIcons";
import { CARD } from "./styles";
import { formatKw } from "../../utils/format";
import { useIsPhone } from "../../hooks/useMediaQuery";

// Paleta przekroju: chłodne szarości jak w reszcie aplikacji, kolor tylko tam, gdzie coś się dzieje.
const WALL = "#e2e8f0";
const ROOM_FILL = "#ffffff";
const LIT_FILL = "#fffbeb";
const LIT_STROKE = "#fde68a";
const LABEL = "#94a3b8";
const TEXT = "#334155";

// Bryła: ściany kondygnacji, garaż i dach spadzisty z panelami PV na prawej połaci.
const BODY = { x: 132, y: 110, w: 756, h: GROUND_Y - 110 };
const GARAGE_BODY = { x: 892, y: 322, w: 176, h: GROUND_Y - 322 };
const ROOF = { left: 112, right: 908, apexX: 510, apexY: HOUSE_TOP + 8, eaveY: 112 };
const SLOPE_DX = ROOF.right - ROOF.apexX;
const SLOPE_DY = ROOF.eaveY - ROOF.apexY;
const SLOPE_ANGLE = (Math.atan2(SLOPE_DY, SLOPE_DX) * 180) / Math.PI;
const SLOPE_LENGTH = Math.hypot(SLOPE_DX, SLOPE_DY);
// Panele wzdłuż połaci, w układzie obróconym o kąt dachu (x wzdłuż połaci, y w głąb dachu).
// `inset` trzyma odstęp od konturu połaci (obrys ma 8, czyli 4 do środka), a ostatni panel kończy się tam,
// gdzie dach jest jeszcze dość głęboki, żeby podstawa trójkąta nie przecięła panelu.
const PANEL = { w: 50, h: 22, gap: 8, inset: 14, count: 4 };
const ROOF_STROKE = 8;
const PANEL_CLEARANCE = 10;
const panelsEnd =
  SLOPE_LENGTH - (PANEL.inset + PANEL.h + ROOF_STROKE / 2 + PANEL_CLEARANCE) / Math.sin((SLOPE_ANGLE * Math.PI) / 180);
const PV_PANELS = Array.from(
  { length: PANEL.count },
  (_, index) => panelsEnd - PANEL.count * PANEL.w - (PANEL.count - 1) * PANEL.gap + index * (PANEL.w + PANEL.gap),
);

// Licznik przy wejściu: karta po lewej i krótkie przyłącze do drzwi.
const METER = { x: 8, y: 352, w: 104, h: 96 };
const DOOR = { x: 132, y: 388, w: 8, h: 70 };

const FLOW_COLORS = { import: "#d97706", export: "#10b981", none: "#cbd5e1" };

const shortPower = (kw) => `${formatKw(Math.abs(kw))}`;

function Roof({ producing }) {
  return (
    <g aria-hidden="true">
      <polygon
        points={`${ROOF.left},${ROOF.eaveY} ${ROOF.apexX},${ROOF.apexY} ${ROOF.right},${ROOF.eaveY}`}
        fill={WALL}
        stroke="#cbd5e1"
        strokeWidth={ROOF_STROKE}
        strokeLinejoin="round"
      />
      <g transform={`translate(${ROOF.apexX} ${ROOF.apexY}) rotate(${SLOPE_ANGLE})`}>
        {PV_PANELS.map((x) => (
          <g key={x}>
            <rect
              x={x}
              y={PANEL.inset}
              width={PANEL.w}
              height={PANEL.h}
              rx="4"
              fill={producing ? "#1e40af" : "#f1f5f9"}
              stroke={producing ? "#3b82f6" : "#cbd5e1"}
              strokeWidth="1.5"
            />
            <line
              x1={x + PANEL.w / 2}
              y1={PANEL.inset + 3}
              x2={x + PANEL.w / 2}
              y2={PANEL.inset + PANEL.h - 3}
              stroke={producing ? "#3b82f6" : "#cbd5e1"}
              strokeWidth="1"
            />
          </g>
        ))}
      </g>
      <text x="700" y="6" fontSize="10.5" fontWeight="600" letterSpacing="0.06em" fill={LABEL}>
        PANELE
      </text>
    </g>
  );
}

function GridMeter({ power, shadow }) {
  const flow = gridFlow(power);
  const direction = flow?.direction ?? "none";
  const color = FLOW_COLORS[direction];
  const moving = direction !== "none";
  // Kierunek ścieżki wyznacza kierunek przesuwania się kresek na przyłączu.
  const from = METER.x + METER.w;
  const to = DOOR.x;
  const y = DOOR.y + DOOR.h / 2;
  const wire = direction === "export" ? `M${to},${y} L${from},${y}` : `M${from},${y} L${to},${y}`;
  const Arrow = direction === "export" ? LuArrowLeft : LuArrowRight;
  const short = { import: "Z sieci", export: "Do sieci", none: "Bilans" }[direction];
  const label = flow ? `Licznik: ${flow.label} ${formatKw(flow.kw)}` : "Licznik: brak danych o mocy";
  const cx = METER.x + METER.w / 2;

  return (
    <g role="img" aria-label={label}>
      <title>{label}</title>
      <path d={wire} stroke={color} strokeWidth="3" strokeLinecap="round" fill="none" className={moving ? "house-wire-flow" : undefined} />
      <rect x={METER.x} y={METER.y} width={METER.w} height={METER.h} rx="16" fill="#ffffff" filter={shadow} />
      <circle cx={cx} cy={METER.y + 22} r="12" fill={moving ? color : "#f1f5f9"} />
      <LuZap x={cx - 7} y={METER.y + 15} size="14" color={moving ? "#ffffff" : LABEL} aria-hidden="true" />
      <g aria-hidden="true">
        {moving && <Arrow x={cx - 38} y={METER.y + 42} size="13" color={color} />}
        <text x={moving ? cx + 7 : cx} y={METER.y + 53} textAnchor="middle" fontSize="11" fontWeight="600" fill={moving ? color : LABEL}>
          {short}
        </text>
        <text x={cx} y={METER.y + 78} textAnchor="middle" fontSize="16" fontWeight="700" fill="#0f172a">
          {flow ? `${formatKw(flow.kw)}` : "—"}
        </text>
      </g>
    </g>
  );
}

function EvBar({ charge, x, y, w }) {
  return (
    <g aria-hidden="true">
      <rect x={x} y={y} width={w} height="4" rx="2" fill="#ede9fe" />
      {charge.fraction == null ? (
        <rect x={x} y={y} width={w} height="4" rx="2" fill="#8b5cf6" className="house-ev-indeterminate" />
      ) : (
        <rect x={x} y={y} width={Math.max(4, w * charge.fraction)} height="4" rx="2" fill="#8b5cf6" />
      )}
    </g>
  );
}

// `plan`: znaczek pozycji planu z `planBadges` ({ text, tone }) albo undefined dla urządzenia spoza planu.
function HouseDevice({ device, plan, planRun, cell, selected, onSelect, shadow }) {
  const appearance = deviceAppearance(device);
  const Icon = DEVICE_ICONS[device.device_type] ?? DEVICE_ICONS.other;
  const Glyph = STATE_GLYPHS[appearance.glyph];
  const box = cell.icon;
  const scale = box / 34;
  const bx = cell.x + (cell.w - box) / 2;
  const by = cell.y + 2;
  const radius = box * 0.32;
  const badge = Math.max(5, box * 0.2);
  const charge = evCharge(device, planRun);
  const caption =
    device.state === "running" && device.power_kw != null && device.power_kw !== 0
      ? shortPower(device.power_kw)
      : appearance.tone === "error"
        ? appearance.label
        : null;
  const name =
    `${device.device_name}: ${appearance.label}${caption && appearance.tone !== "error" ? `, ${caption}` : ""}` +
    (plan ? `, ${plan.text}` : "");

  const onKeyDown = (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect();
    }
  };

  return (
    <g
      role="button"
      tabIndex={0}
      aria-label={name}
      aria-haspopup="dialog"
      aria-expanded={selected}
      data-device-id={device.device_id}
      data-tone={appearance.tone}
      className="cursor-pointer focus:outline-none house-device"
      onClick={onSelect}
      onKeyDown={onKeyDown}
    >
      <title>{name}</title>
      {appearance.animated && (
        <rect
          x={bx - 4}
          y={by - 4}
          width={box + 8}
          height={box + 8}
          rx={radius + 4}
          fill={appearance.fill}
          className="house-device-halo"
          aria-hidden="true"
        />
      )}
      {selected && (
        <rect
          x={bx - 4}
          y={by - 4}
          width={box + 8}
          height={box + 8}
          rx={radius + 4}
          fill="none"
          stroke="#0f172a"
          strokeWidth="2"
          aria-hidden="true"
        />
      )}
      <rect
        x={bx}
        y={by}
        width={box}
        height={box}
        rx={radius}
        fill={appearance.fill}
        stroke={appearance.tone === "active" ? "none" : appearance.stroke}
        strokeWidth="1.5"
        className="house-device-tile"
      />
      <Icon x={bx + box * 0.22} y={by + box * 0.22} size={box * 0.56} color={appearance.icon} aria-hidden="true" />
      <g aria-hidden="true">
        <circle cx={bx + box - 1} cy={by + box - 1} r={badge} fill="#ffffff" filter={shadow} />
        <Glyph
          x={bx + box - 1 - badge * 0.62}
          y={by + box - 1 - badge * 0.62}
          size={badge * 1.24}
          color={appearance.tone === "off" ? LABEL : appearance.tone === "error" ? "#dc2626" : appearance.stroke}
        />
      </g>
      {plan && (
        <g aria-hidden="true" data-plan-tone={plan.tone}>
          <circle cx={bx + 1} cy={by + 1} r={badge} fill={planBadgeColor(plan)} />
          <LuCalendarCheck x={bx + 1 - badge * 0.6} y={by + 1 - badge * 0.6} size={badge * 1.2} color="#ffffff" />
        </g>
      )}
      {caption && (
        <text
          x={cell.x + cell.w / 2}
          y={by + box + 14 * scale}
          textAnchor="middle"
          fontSize={10 * scale}
          fontWeight="600"
          fill={appearance.tone === "error" ? "#dc2626" : TEXT}
          className="tabular-nums"
          aria-hidden="true"
        >
          {caption}
        </text>
      )}
      {charge && <EvBar charge={charge} x={cell.x + 6} y={by + box + 19 * scale} w={cell.w - 12} />}
    </g>
  );
}

function Room({ room, devices, cells, planBadges, planRun, selectedId, onSelect, shadow }) {
  const lit = isRoomLit(devices);
  const label = roomLabel(room.id);
  return (
    <g role="group" aria-label={lit ? `${label}, światło włączone` : label} data-room={room.id} data-lit={lit}>
      {room.id !== "roof" && (
        <rect
          x={room.x}
          y={room.y}
          width={room.w}
          height={room.h}
          rx="12"
          fill={lit ? LIT_FILL : ROOM_FILL}
          stroke={lit ? LIT_STROKE : "none"}
          strokeWidth="1.5"
          filter={shadow}
          className="house-room"
        />
      )}
      <text
        x={room.x + 12}
        y={room.y + 19}
        fontSize="10.5"
        fontWeight="600"
        letterSpacing="0.06em"
        fill={lit ? "#b45309" : LABEL}
        aria-hidden="true"
      >
        {label.toUpperCase()}
      </text>
      {devices.map((device, index) => (
        <HouseDevice
          key={device.device_id}
          device={device}
          plan={planBadges[device.device_id]}
          planRun={planRun}
          cell={cells[index]}
          selected={selectedId === device.device_id}
          onSelect={() => onSelect(device.device_id)}
          shadow={shadow}
        />
      ))}
    </g>
  );
}

const LEGEND = [
  { glyph: "off", label: "Wyłączone", fill: "#f1f5f9", stroke: "#e2e8f0" },
  { glyph: "ready", label: "Gotowe", fill: "#ffffff", stroke: "#3b82f6" },
  { glyph: "running", label: "Pracuje", fill: "#3b82f6", stroke: "#3b82f6" },
  { glyph: "error", label: "Awaria / brak połączenia", fill: "#fef2f2", stroke: "#ef4444" },
];

function Legend() {
  const chip = "inline-flex items-center gap-1.5 rounded-full bg-slate-50 px-2.5 py-1 ring-1 ring-slate-200/70";
  return (
    <ul className="flex flex-wrap gap-2 text-xs text-slate-600" aria-label="Legenda">
      {LEGEND.map((item) => {
        const Glyph = STATE_GLYPHS[item.glyph];
        return (
          <li key={item.glyph} className={chip}>
            <span className="inline-block h-3 w-3 rounded" style={{ background: item.fill, border: `1.5px solid ${item.stroke}` }} />
            <Glyph className="text-slate-400" aria-hidden="true" />
            {item.label}
          </li>
        );
      })}
      <li className={chip}>
        <LuCalendarCheck className="text-emerald-500" aria-hidden="true" />
        Według planu
      </li>
      <li className={chip}>
        <span className="inline-block h-3 w-3 rounded" style={{ background: LIT_FILL, border: `1.5px solid ${LIT_STROKE}` }} />
        Światło włączone
      </li>
    </ul>
  );
}

// Pozycja dymku nad przekrojem w procentach, żeby zgadzała się przy każdej szerokości SVG.
const popoverStyle = (cell) => {
  const centerX = ((cell.x + cell.w / 2) / HOUSE_WIDTH) * 100;
  const left = `${Math.min(80, Math.max(20, centerX))}%`;
  const height = HOUSE_HEIGHT - HOUSE_TOP;
  const top = (y) => (y - HOUSE_TOP) / height;
  const below = top(cell.y + cell.h) < 0.55;
  return below
    ? { left, top: `${top(cell.y + cell.h) * 100}%`, transform: "translateX(-50%)" }
    : { left, bottom: `${(1 - top(cell.y)) * 100}%`, transform: "translateX(-50%)" };
};

/**
 * Przekrój domu: urządzenia w swoich pomieszczeniach, licznik przy wejściu i dymek po kliknięciu.
 * Stan przychodzi z GET /home/state co 1–2 s, więc dymek czyta urządzenie po `device_id` przy każdym renderze.
 */
// `planBadges` (device_id -> { text, tone }): pozycje trwającego przebiegu planu, te same co w widoku listy.

// `planRun`: przebieg planu tej symulacji (GET /home/plan-runs/latest) do paska czasu i wskaźników; null bez niego.
// `live`: statystyki na żywo przebiegu (ZP-153), `weather`: pogoda doby symulacji; obie do wskaźników w rogu.
function HouseView({
  devices, power, simTime, disabled = false, onCommand, planBadges = {}, planRun = null, live = null, weather = null,
}) {
  const [selectedId, setSelectedId] = useState(null);
  const [pending, setPending] = useState(() => new Set());
  const isPhone = useIsPhone();
  const shadowId = `house-shadow-${useId().replace(/:/g, "")}`;
  const shadow = `url(#${shadowId})`;

  const rooms = placeDevicesInRooms(devices);
  const shownRooms = houseRooms(rooms);
  const cells = new Map();
  for (const room of shownRooms) {
    const roomDevices = rooms.get(room.id);
    layoutRoom(room, roomDevices.length).forEach((cell, index) => cells.set(roomDevices[index].device_id, cell));
  }
  const selected = devices.find((device) => device.device_id === selectedId);
  const producing = devices.some(isProducingPv);

  useEffect(() => {
    if (!selectedId) return undefined;
    const onKeyDown = (event) => {
      if (event.key === "Escape") setSelectedId(null);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [selectedId]);

  const send = async (device, command) => {
    setPending((current) => new Set(current).add(device.device_id));
    try {
      await onCommand(device, command);
    } finally {
      setPending((current) => {
        const next = new Set(current);
        next.delete(device.device_id);
        return next;
      });
    }
  };

  if (!devices.length) {
    return (
      <section className={`${CARD} text-sm text-gray-600`} aria-label="Dom">
        Hub nie ma jeszcze uruchomionych urządzeń. Zaimportuj plik urządzeń, a rejestr trafi do huba.
      </section>
    );
  }

  // Na telefonie pokoje jako kafelki jeden pod drugim, ze sterowaniem urządzeniami; przekrój tylko od `md`.
  if (isPhone) {
    return (
      <section className={`${CARD} space-y-3`} aria-label="Dom">
        <HouseTimeline run={planRun} simTime={simTime} />
        <LiveIndicators run={planRun} live={live} weather={weather} simTime={simTime} />
        <HouseRooms
          devices={devices}
          power={power}
          planBadges={planBadges}
          selectedId={selectedId}
          onSelect={(id) => setSelectedId((current) => (current === id ? null : id))}
        />
        {selected &&
          // Panel urządzenia od dołu ekranu, w <body> (portal), żeby odstępy kart nie przesuwały tła;
          // stuknięcie w tło albo Escape zamyka.
          createPortal(
          <div
            className="fixed inset-0 z-50 flex items-end bg-black/40"
            onClick={(event) => {
              if (event.target === event.currentTarget) setSelectedId(null);
            }}
          >
            <HouseDevicePopover
              sheet
              device={selected}
              plan={planBadges[selected.device_id]}
              planRun={planRun}
              disabled={disabled || pending.has(selected.device_id)}
              onCommand={(command) => send(selected, command)}
              onClose={() => setSelectedId(null)}
            />
          </div>,
          document.body,
          )}
      </section>
    );
  }

  return (
    <section className={`${CARD} space-y-4`} aria-label="Dom">
      <HouseTimeline run={planRun} simTime={simTime} />
      {/* Przewijanie w bok tylko na wąskim ekranie. `overflow-x: auto` przewija też w pionie, więc dymek
          wystający poniżej przekroju dodawał pasek przewijania i przesuwał widok; od `md` dymek może wystawać. */}
      <div className="overflow-x-auto -mx-4 px-4 md:overflow-visible md:mx-0 md:px-0">
        <div className="relative min-w-[720px] rounded-xl bg-slate-50 p-3 md:p-4">
          <div className="relative">
            <LiveIndicators run={planRun} live={live} weather={weather} simTime={simTime} side="home" />
            <LiveIndicators run={planRun} live={live} weather={weather} simTime={simTime} side="outside" />
            <svg
              viewBox={`0 ${HOUSE_TOP} ${HOUSE_WIDTH} ${HOUSE_HEIGHT - HOUSE_TOP}`}
              className="block w-full h-auto select-none"
              role="group"
              aria-label="Przekrój domu"
            >
              <defs>
                <filter id={shadowId} x="-10%" y="-10%" width="120%" height="130%">
                  <feDropShadow dx="0" dy="1" stdDeviation="1.5" floodColor="#0f172a" floodOpacity="0.08" />
                </filter>
              </defs>
              <line x1="0" y1={GROUND_Y} x2={HOUSE_WIDTH} y2={GROUND_Y} stroke={WALL} strokeWidth="2" strokeLinecap="round" aria-hidden="true" />
              <rect x={BODY.x} y={BODY.y} width={BODY.w} height={BODY.h} rx="16" fill={WALL} aria-hidden="true" />
              <rect x={GARAGE_BODY.x} y={GARAGE_BODY.y} width={GARAGE_BODY.w} height={GARAGE_BODY.h} rx="16" fill={WALL} aria-hidden="true" />
              <Roof producing={producing} />
              {/* Drzwi wejściowe w ścianie pomieszczenia „Inne”. */}
              <rect x={DOOR.x} y={DOOR.y} width={DOOR.w} height={DOOR.h} rx="3" fill="#94a3b8" aria-hidden="true" />
              <GridMeter power={power} shadow={shadow} />
              {shownRooms.map((room) => (
                <Room
                  key={room.id}
                  room={room}
                  devices={rooms.get(room.id)}
                  cells={rooms.get(room.id).map((device) => cells.get(device.device_id))}
                  planBadges={planBadges}
                  planRun={planRun}
                  selectedId={selectedId}
                  onSelect={(id) => setSelectedId((current) => (current === id ? null : id))}
                  shadow={shadow}
                />
              ))}
            </svg>

            {selected && (
              <HouseDevicePopover
                device={selected}
                plan={planBadges[selected.device_id]}
                planRun={planRun}
                disabled={disabled || pending.has(selected.device_id)}
                onCommand={(command) => send(selected, command)}
                onClose={() => setSelectedId(null)}
                style={popoverStyle(cells.get(selected.device_id))}
              />
            )}
          </div>
        </div>
      </div>
      <Legend />
    </section>
  );
}

export default HouseView;
