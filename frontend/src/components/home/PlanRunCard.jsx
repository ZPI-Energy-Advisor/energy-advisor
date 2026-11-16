import { useState } from "react";
import { FiAlertTriangle, FiSquare } from "react-icons/fi";
import { formatKwh, formatSimDate, formatSimTime } from "../../utils/home";
import { CARD, SECONDARY_BUTTON } from "./styles";

const STATUS = {
  running: { label: "Plan w trakcie", tone: "bg-emerald-100 text-emerald-800" },
  completed: { label: "Plan wykonany", tone: "bg-sky-100 text-sky-800" },
  ended: { label: "Zakończony", tone: "bg-gray-100 text-gray-700" },
  superseded: { label: "Przerwany", tone: "bg-amber-100 text-amber-800" },
};

// Doba RRRR-MM-DD słowami; południe UTC to ten sam dzień w strefie domu.
const dayText = (day) => formatSimDate(`${day}T12:00:00Z`);

const actionText = (action) => {
  if (action.status === "rejected") return `Odrzucone: ${action.detail || action.code}`;
  const window = `${formatSimTime(action.start)}–${formatSimTime(action.end)}`;
  return action.status === "accepted" ? `Uruchomione, ${window}` : `Zaplanowane na ${window}`;
};

// Produkcja PV ma znak ujemny; na ekranie pokazujemy ją jako dodatnią z dopiskiem „produkcji”.
const historyEnergy = (device) =>
  device.history_kwh < 0
    ? `${formatKwh(-device.actual_kwh)} z ${formatKwh(-device.history_kwh)} produkcji`
    : `${formatKwh(device.actual_kwh)} z ${formatKwh(device.history_kwh)}`;

// PV oraz pompa ciepła i bojler spoza planu pracują same, jak w dniu referencyjnym.
function HistoryDevices({ run }) {
  if (!run.history_day || !run.replayed_devices.length) return null;
  return (
    <section className="mt-4" aria-label="Z dnia referencyjnego">
      <p className="text-sm text-gray-700">Pracują same, jak w {dayText(run.history_day)}:</p>
      <ul className="mt-1 space-y-0.5 text-sm text-gray-600">
        {run.replayed_devices.map((device) => (
          <li key={device.device_id}>
            {device.device_name}: {historyEnergy(device)}
          </li>
        ))}
      </ul>
    </section>
  );
}

// Przebieg zatwierdzonego planu w symulacji (ZP-113): postęp, energia urządzeń z planu i awarie.
// „Zakończ” zatrzymuje zegar, kasuje resztę planu w hubie i zamyka przebieg; do chwilowej przerwy służy Pauza.
function PlanRunCard({ run, disabled, onEnd }) {
  const [isEnding, setIsEnding] = useState(false);
  const status = STATUS[run.status] ?? STATUS.ended;
  const running = run.status === "running";

  const end = async () => {
    setIsEnding(true);
    try {
      await onEnd(run);
    } finally {
      setIsEnding(false);
    }
  };

  return (
    <section className={CARD} aria-label="Przebieg planu">
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-gray-900">
            Plan na {dayText(run.plan_date)}
          </h3>
          <p className="text-sm text-gray-600">
            {run.sim_time ? `Czas symulacji ${formatSimTime(run.sim_time)}` : "Czas symulacji nieznany"}
            {` · plan do ${formatSimTime(run.horizon_end)} następnego dnia`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className={`inline-flex px-2.5 py-1 rounded-full text-xs font-semibold ${status.tone}`}>{status.label}</span>
          {running && (
            <button type="button" className={SECONDARY_BUTTON} disabled={disabled || isEnding} onClick={end}>
              <FiSquare aria-hidden="true" /> {isEnding ? "Kończenie..." : "Zakończ"}
            </button>
          )}
        </div>
      </div>

      {run.status === "superseded" && (
        <p className="mt-3 text-sm text-amber-800">
          Symulacja zaczęła inną dobę, więc ten przebieg się zakończył. Uruchom plan ponownie na stronie planu.
        </p>
      )}

      <p className="mt-4 text-sm text-gray-700">
        Urządzenia z planu zużyły <strong>{formatKwh(run.actual_kwh)}</strong> z {formatKwh(run.planned_kwh)} według planu.
      </p>

      <ul className="mt-3 divide-y divide-gray-100 border-y border-gray-100">
        {run.devices.map((device) => (
          <li key={device.device_id} className="py-2 text-sm" aria-label={device.device_name}>
            <div className="flex justify-between gap-3">
              <span className="font-medium text-gray-900">{device.device_name}</span>
              <span className="tabular-nums text-gray-700">
                {formatKwh(device.actual_kwh)} / {formatKwh(device.planned_kwh)}
              </span>
            </div>
            {device.actions.map((action) => (
              <p
                key={action.action_id}
                className={action.status === "rejected" ? "text-red-700" : "text-gray-500"}
              >
                {action.label ? `${action.label}: ` : ""}
                {actionText(action)}
              </p>
            ))}
          </li>
        ))}
      </ul>

      <HistoryDevices run={run} />

      {running && (
        <p className="mt-3 text-xs text-gray-500">
          Urządzenia stałe (światło, czajnik, TV…) włącza się ręcznie na liście niżej: widać wtedy, jak razem
          z planem obciążają przyłącze.
        </p>
      )}

      {run.errors.length > 0 && (
        <div className="mt-4 p-3 rounded border border-red-200 bg-red-50" role="alert">
          <p className="flex items-center gap-1.5 text-sm font-semibold text-red-800">
            <FiAlertTriangle aria-hidden="true" /> Awarie urządzeń
          </p>
          <ul className="mt-1 space-y-0.5 text-sm text-red-700">
            {run.errors.map((error, index) => (
              // Indeks w kluczu: lista jest tylko do odczytu, a ten sam błąd może wrócić dwa razy w kwadransie.
              <li key={`${index}-${error.device_id}-${error.sim_time}`}>
                {formatSimTime(error.sim_time)} {error.device_name}: {error.message || error.code}
              </li>
            ))}
          </ul>
          <p className="mt-1 text-xs text-red-700">Pozostałe urządzenia pracują dalej.</p>
        </div>
      )}
    </section>
  );
}

export default PlanRunCard;
