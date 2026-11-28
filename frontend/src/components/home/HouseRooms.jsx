import { LuArrowLeft, LuArrowRight, LuCalendarCheck, LuLightbulb, LuZap } from "react-icons/lu";
import {
  deviceAppearance,
  gridFlow,
  houseRooms,
  isRoomLit,
  placeDevicesInRooms,
  planBadgeColor,
} from "../../utils/houseView";
import { ROOM_LABELS } from "../../utils/home";
import { formatKw } from "../../utils/format";
import { DEVICE_ICONS, STATE_GLYPHS } from "./houseIcons";

const FLOW_TONES = {
  import: "bg-rose-50 text-rose-800 ring-rose-100",
  export: "bg-emerald-50 text-emerald-800 ring-emerald-100",
  none: "bg-slate-50 text-slate-700 ring-slate-100",
};

// Licznik domu nad pokojami: kierunek przepływu i moc, jak licznik przy wejściu w przekroju.
function MeterTile({ power }) {
  const flow = gridFlow(power);
  const direction = flow?.direction ?? "none";
  const Arrow = direction === "export" ? LuArrowLeft : LuArrowRight;
  return (
    <div className={`flex items-center gap-3 rounded-xl px-4 py-3 ring-1 ${FLOW_TONES[direction]}`} role="status">
      <LuZap aria-hidden="true" className="shrink-0 text-lg" />
      <p className="text-sm">
        <span className="font-semibold">Licznik: </span>
        {flow ? (
          <>
            {flow.label} {direction !== "none" && <Arrow aria-hidden="true" className="inline" />}{" "}
            <span className="font-semibold tabular-nums">{formatKw(flow.kw)}</span>
          </>
        ) : (
          "brak danych o mocy"
        )}
      </p>
    </div>
  );
}

// Kafelek urządzenia jak w przekroju domu: kwadrat z ikoną w kolorze stanu, znak stanu w rogu i znaczek planu.
// Szczegóły i sterowanie otwiera stuknięcie (panel od dołu ekranu w HouseView).
function DeviceTile({ device, plan, selected, onSelect }) {
  const look = deviceAppearance(device);
  const Icon = DEVICE_ICONS[device.device_type] ?? DEVICE_ICONS.other;
  const Glyph = STATE_GLYPHS[look.glyph];
  const running = device.state === "running" && device.power_kw != null && device.power_kw !== 0;
  const name = `${device.device_name}: ${look.label}${running ? `, ${formatKw(Math.abs(device.power_kw))}` : ""}${plan ? `, ${plan.text}` : ""}`;
  return (
    <li className="flex flex-col items-center">
      <button
        type="button"
        aria-label={name}
        aria-haspopup="dialog"
        aria-expanded={selected}
        onClick={onSelect}
        className={`relative flex aspect-square w-full max-w-[4.5rem] items-center justify-center rounded-2xl border-[1.5px] transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 ${
          selected ? "ring-2 ring-slate-900" : ""
        } ${look.animated ? "shadow-[0_0_0_4px_rgba(16,185,129,0.15)]" : ""}`}
        style={{ background: look.fill, borderColor: look.tone === "active" ? look.fill : look.stroke, color: look.icon }}
      >
        <Icon aria-hidden="true" className="h-[55%] w-[55%]" />
        <span
          aria-hidden="true"
          className="absolute -bottom-1.5 -right-1.5 flex h-6 w-6 items-center justify-center rounded-full bg-white shadow"
          style={{ color: look.tone === "off" ? "#94a3b8" : look.tone === "error" ? "#dc2626" : look.stroke }}
        >
          <Glyph className="h-3.5 w-3.5" />
        </span>
        {plan && (
          <span
            aria-hidden="true"
            className="absolute -left-1.5 -top-1.5 flex h-6 w-6 items-center justify-center rounded-full text-white"
            style={{ background: planBadgeColor(plan) }}
          >
            <LuCalendarCheck className="h-3.5 w-3.5" />
          </span>
        )}
      </button>
      <span aria-hidden="true" className="mt-2 h-4 text-[11px] font-semibold tabular-nums text-slate-700">
        {running ? formatKw(Math.abs(device.power_kw)) : look.tone === "error" ? look.label : ""}
      </span>
    </li>
  );
}

/**
 * Mój dom na telefonie: pomieszczenia jako karty jedna pod drugą, w każdej kafelki urządzeń z ikonami jak
 * w przekroju domu (który na wąskim ekranie trzeba by przesuwać w bok). Pokoje bez urządzeń są pominięte.
 */
function HouseRooms({ devices, power, planBadges, selectedId, onSelect }) {
  const rooms = placeDevicesInRooms(devices);
  const shown = houseRooms(rooms).filter((room) => rooms.get(room.id).length);
  return (
    <div className="space-y-3">
      <MeterTile power={power} />
      {shown.map((room) => {
        const items = rooms.get(room.id);
        const lit = isRoomLit(items);
        const name = ROOM_LABELS[room.id] ?? room.id;
        return (
          <section
            key={room.id}
            aria-label={name}
            className={`rounded-2xl border px-4 pb-2 pt-3 ${lit ? "border-amber-200 bg-amber-50" : "border-slate-200 bg-white"}`}
          >
            <h3 className="mb-3 flex items-center justify-between gap-2 text-xs font-bold uppercase tracking-wide text-slate-400">
              {name}
              {lit && (
                <span className="flex items-center gap-1 font-medium normal-case tracking-normal text-amber-700">
                  <LuLightbulb aria-hidden="true" /> światło włączone
                </span>
              )}
            </h3>
            <ul className="grid grid-cols-4 gap-x-3 gap-y-1">
              {items.map((device) => (
                <DeviceTile
                  key={device.device_id}
                  device={device}
                  plan={planBadges[device.device_id]}
                  selected={selectedId === device.device_id}
                  onSelect={() => onSelect(device.device_id)}
                />
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

export default HouseRooms;
