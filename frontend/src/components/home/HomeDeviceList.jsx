import { useState } from "react";
import { FiPower } from "react-icons/fi";
import {
  DEVICE_TYPE_LABELS,
  FLEXIBILITY_LABELS,
  deviceStateLabel,
  deviceStateTone,
  durationLabel,
  formatKw,
  formatKwh,
  formatSimTime,
  groupDevicesByCategory,
  hasControls,
  runLabel,
  isControllable,
  programName,
} from "../../utils/home";
import { CARD, PRIMARY_BUTTON, SECONDARY_BUTTON } from "./styles";

// Plakietka planu (ZP-114): obrys zamiast wypełnienia, żeby nie mylić jej ze stanem urządzenia.
const PLAN_BADGE = {
  active: "border-emerald-300 text-emerald-800",
  ready: "border-sky-300 text-sky-800",
  error: "border-red-300 text-red-700",
  neutral: "border-gray-300 text-gray-600",
};

const STATE_BADGE = {
  active: "bg-emerald-100 text-emerald-800",
  ready: "bg-sky-100 text-sky-800",
  error: "bg-red-100 text-red-700",
  neutral: "bg-gray-100 text-gray-600",
};

// Program wybrany w liście; domyślnie pierwszy. Wybór spoza aktualnych programów (np. po ponownym
// imporcie pliku urządzeń) wraca do pierwszego, żeby nie wysłać komendy z nieistniejącym programem.
// Lista, „Uruchom” i (dla czekającego urządzenia) wyłączenie stoją w jednym rzędzie.
function ProgramControls({ device, disabled, onCommand, children = null }) {
  const [selected, setSelected] = useState(null);
  const programId = device.programs.some((program) => program.program_id === selected)
    ? selected
    : device.programs[0].program_id;
  return (
    <div className="flex items-center gap-2">
      <select
        aria-label={`Program: ${device.device_name}`}
        className="min-w-0 flex-1 lg:flex-none lg:w-44 border border-gray-300 rounded px-2 py-2 text-sm bg-white disabled:bg-gray-50"
        value={programId}
        disabled={disabled}
        onChange={(event) => setSelected(event.target.value)}
      >
        {device.programs.map((program) => (
          <option key={program.program_id} value={program.program_id}>
            {program.program_name} ({durationLabel(program.duration_min)})
          </option>
        ))}
      </select>
      <button
        type="button"
        className={PRIMARY_BUTTON}
        disabled={disabled}
        aria-label={`Uruchom program: ${device.device_name}`}
        onClick={() => onCommand({ command: "start_program", program_id: programId })}
      >
        Uruchom
      </button>
      {children}
    </div>
  );
}

function DeviceControls({ device, disabled, onCommand }) {
  // Produkcji PV nie włącza się ręcznie: o pracy instalacji decyduje słońce, nie przycisk.
  if (!hasControls(device)) return null;
  const running = device.state === "running";
  const off = (label) => (
    <button
      type="button"
      className={SECONDARY_BUTTON}
      disabled={disabled}
      aria-label={`${label}: ${device.device_name}`}
      onClick={() => onCommand({ command: "off" })}
    >
      {label}
    </button>
  );

  if (!device.programs.length) {
    return running ? (
      off("Wyłącz")
    ) : (
      <button
        type="button"
        className={PRIMARY_BUTTON}
        disabled={disabled}
        aria-label={`Włącz: ${device.device_name}`}
        onClick={() => onCommand({ command: "on" })}
      >
        Włącz
      </button>
    );
  }
  if (running) return off("Przerwij program");
  return (
    <ProgramControls device={device} disabled={disabled} onCommand={onCommand}>
      {device.state === "idle" && (
        // Wyłączenie czekającego urządzenia to rzadkie polecenie: sama ikona, żeby rząd się nie łamał.
        <button
          type="button"
          className={`${SECONDARY_BUTTON} px-2.5`}
          disabled={disabled}
          aria-label={`Wyłącz: ${device.device_name}`}
          title="Wyłącz"
          onClick={() => onCommand({ command: "off" })}
        >
          <FiPower aria-hidden="true" />
        </button>
      )}
    </ProgramControls>
  );
}

function DeviceRow({ device, plan, disabled, onCommand }) {
  const flexibility = FLEXIBILITY_LABELS[device.flexibility_mode];
  const typeLabel = DEVICE_TYPE_LABELS[device.device_type];
  const program = device.state === "running" && device.program_id;

  return (
    <li className="py-3 flex flex-col lg:flex-row lg:items-center gap-3" aria-label={device.device_name}>
      <div className="min-w-0 lg:flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-gray-900 break-words">{device.device_name}</span>
          <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${STATE_BADGE[deviceStateTone(device.state)]}`}>
            {deviceStateLabel(device)}
          </span>
          {plan && (
            <span className={`px-2 py-0.5 rounded-full border text-xs font-medium ${PLAN_BADGE[plan.tone]}`}>
              {plan.text}
            </span>
          )}
        </div>
        <p className="mt-0.5 text-xs text-gray-500">
          {typeLabel && <span>{typeLabel}</span>}
          {typeLabel && flexibility && <span aria-hidden="true"> · </span>}
          {flexibility && <span title={flexibility.hint}>{flexibility.label}</span>}
          {program && (
            <span className="block text-gray-600">
              {programName(device, device.program_id)}
              {device.program_ends_at && `, koniec ${formatSimTime(device.program_ends_at)}`}
            </span>
          )}
          {device.run?.ends_at && !plan && (
            <span className="block text-gray-600">
              {runLabel(device.run)}, koniec {formatSimTime(device.run.ends_at)}
            </span>
          )}
        </p>
      </div>

      <dl className="grid grid-cols-2 gap-4 text-sm lg:w-56 shrink-0">
        <div>
          <dt className="text-xs text-gray-500">Moc</dt>
          <dd className="font-medium tabular-nums">{formatKw(device.power_kw)}</dd>
        </div>
        <div>
          <dt className="text-xs text-gray-500">Dziś</dt>
          <dd className="font-medium tabular-nums">{formatKwh(device.energy_today_kwh)}</dd>
        </div>
      </dl>

      <div className="lg:w-80 shrink-0 lg:flex lg:justify-end">
        <DeviceControls device={device} disabled={disabled || !isControllable(device)} onCommand={onCommand} />
      </div>
    </li>
  );
}

// Urządzenia domu pogrupowane po kategorii. Polecenie blokuje przyciski tylko swojego urządzenia.
// `planBadges` (device_id -> { text, tone }): przy urządzeniach z planu i z historii w trakcie przebiegu planu.
function HomeDeviceList({ devices, disabled = false, onCommand, planBadges = {} }) {
  const [pending, setPending] = useState(() => new Set());

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
      <section className={`${CARD} text-sm text-gray-600`} aria-label="Urządzenia">
        Hub nie ma jeszcze uruchomionych urządzeń. Zaimportuj plik urządzeń, a rejestr trafi do huba.
      </section>
    );
  }

  return (
    <section className="space-y-4" aria-label="Urządzenia">
      {groupDevicesByCategory(devices).map(({ category, devices: items }) => (
        <div key={category} className={CARD}>
          <h3 className="text-sm font-bold uppercase tracking-wide text-gray-500">
            {category} <span className="font-normal normal-case text-gray-400">({items.length})</span>
          </h3>
          <ul className="divide-y divide-gray-100">
            {items.map((device) => (
              <DeviceRow
                key={device.device_id}
                device={device}
                plan={planBadges[device.device_id]}
                disabled={disabled || pending.has(device.device_id)}
                onCommand={(command) => send(device, command)}
              />
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}

export default HomeDeviceList;
