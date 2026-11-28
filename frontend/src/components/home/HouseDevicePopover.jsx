import { LuCalendarCheck, LuX } from "react-icons/lu";
import {
  DEVICE_TYPE_LABELS,
  formatKw,
  formatKwh,
  formatSimTime,
  hasControls,
  isControllable,
  programName,
  runLabel,
} from "../../utils/home";
import { deviceAppearance, evCharge, isProducingPv, planBadgeColor, roomLabel, roomOf } from "../../utils/houseView";
import { DeviceControls } from "./HomeDeviceList";
import { STATE_GLYPHS } from "./houseIcons";
import { PRIMARY_BUTTON, SECONDARY_BUTTON } from "./styles";
import { formatPercent } from "../../utils/format";

function Fact({ label, children }) {
  return (
    <div>
      <dt className="text-xs text-gray-500">{label}</dt>
      <dd className="font-medium tabular-nums">{children}</dd>
    </div>
  );
}

// Włącz i wyłącz tylko dla urządzeń stałych (komendy on/off z ZP-97). Programy i przebiegi
// urządzeń przesuwalnych zostają w widoku listy, gdzie jest wybór programu.
function PopoverControls({ device, disabled, onCommand }) {
  if (!hasControls(device)) {
    return <p className="text-xs text-gray-500">Instalacja pracuje według słońca, nie włącza się jej ręcznie.</p>;
  }
  if (device.flexibility_mode !== "fixed") {
    return <p className="text-xs text-gray-500">Programy i przebiegi tego urządzenia uruchomisz w widoku „Lista”.</p>;
  }
  const blocked = disabled || !isControllable(device);
  return device.state === "running" ? (
    <button
      type="button"
      className={SECONDARY_BUTTON}
      disabled={blocked}
      aria-label={`Wyłącz: ${device.device_name}`}
      onClick={() => onCommand({ command: "off" })}
    >
      Wyłącz
    </button>
  ) : (
    <button
      type="button"
      className={PRIMARY_BUTTON}
      disabled={blocked}
      aria-label={`Włącz: ${device.device_name}`}
      onClick={() => onCommand({ command: "on" })}
    >
      Włącz
    </button>
  );
}

/**
 * Dymek urządzenia z widoku domu: stan, moc, energia doby, program i sterowanie. `sheet`: panel od dołu ekranu
 * na telefonie, z pełnym sterowaniem jak na liście (także programy pralki czy zmywarki).
 */
function HouseDevicePopover({ device, plan, planRun, disabled, onCommand, onClose, style, sheet = false }) {
  const appearance = deviceAppearance(device);
  const Glyph = STATE_GLYPHS[appearance.glyph];
  const typeLabel = DEVICE_TYPE_LABELS[device.device_type];
  const charge = evCharge(device, planRun);
  const producing = isProducingPv(device);

  return (
    <div
      role="dialog"
      aria-label={device.device_name}
      className={
        sheet
          ? "w-full max-h-[85dvh] overflow-y-auto rounded-t-2xl bg-white p-4 pb-[max(1rem,env(safe-area-inset-bottom))] text-sm shadow-xl space-y-3"
          : "absolute z-10 w-64 max-w-[calc(100%-1rem)] rounded-2xl bg-white p-4 text-sm shadow-xl ring-1 ring-slate-900/5 space-y-3"
      }
      style={style}
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-gray-900 break-words">{device.device_name}</p>
          <p className="text-xs text-gray-500">
            {[typeLabel, roomLabel(roomOf(device))].filter(Boolean).join(" · ")}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className={`rounded-full text-slate-400 hover:bg-slate-100 hover:text-slate-700 ${sheet ? "p-2.5" : "p-1.5"}`}
          aria-label="Zamknij"
        >
          <LuX aria-hidden="true" />
        </button>
      </div>

      <p
        className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold"
        style={{
          color: appearance.tone === "off" ? "#475569" : appearance.tone === "error" ? "#dc2626" : appearance.stroke,
          background: appearance.tone === "off" ? "#f1f5f9" : `${appearance.stroke}1a`,
        }}
      >
        <Glyph aria-hidden="true" />
        {appearance.label}
      </p>
      {plan && (
        <p className="flex items-center gap-1.5 text-xs font-medium" style={{ color: planBadgeColor(plan) }}>
          <LuCalendarCheck aria-hidden="true" />
          {plan.text}
        </p>
      )}

      <dl className="grid grid-cols-2 gap-3 rounded-xl bg-slate-50 p-3">
        <Fact label={producing ? "Produkcja" : "Moc"}>{formatKw(producing ? -device.power_kw : device.power_kw)}</Fact>
        <Fact label="Energia">{formatKwh(device.energy_today_kwh == null ? null : Math.abs(device.energy_today_kwh))}</Fact>
      </dl>

      {device.state === "running" && device.program_id && (
        <p className="text-xs text-gray-600">
          Program: {programName(device, device.program_id)}
          {device.program_ends_at && `, koniec ${formatSimTime(device.program_ends_at)}`}
        </p>
      )}
      {device.state === "running" && device.run?.ends_at && (
        <p className="text-xs text-gray-600">
          {runLabel(device.run)}, koniec {formatSimTime(device.run.ends_at)}
        </p>
      )}
      {charge && (
        <p className="text-xs text-gray-600">
          {charge.fraction == null
            ? "Ładowanie poza planem, bez ustalonej energii."
            : `Naładowano ${formatPercent(charge.fraction)} energii z planu ` +
              `(${formatKwh(charge.deliveredKwh)} z ${formatKwh(charge.plannedKwh)})`}
        </p>
      )}

      {sheet ? (
        <div className="[&>div]:flex-wrap [&_button]:min-h-[2.75rem] [&_select]:min-h-[2.75rem] [&_select]:basis-full">
          {hasControls(device) ? (
            <DeviceControls device={device} disabled={disabled || !isControllable(device)} onCommand={onCommand} />
          ) : (
            <p className="text-xs text-gray-500">Instalacja pracuje według słońca, nie włącza się jej ręcznie.</p>
          )}
        </div>
      ) : (
        <PopoverControls device={device} disabled={disabled} onCommand={onCommand} />
      )}
    </div>
  );
}

export default HouseDevicePopover;
