import { useState } from "react";
import { FiAlertTriangle, FiSquare } from "react-icons/fi";
import { formatKwh, formatSimDate, formatSimTime } from "../../utils/home";
import PlanRunCost, { DeviationList } from "./PlanRunCost";
import { CARD, SECONDARY_BUTTON } from "./styles";

const STATUS = {
  running: { label: "Plan w trakcie", tone: "bg-emerald-100 text-emerald-800" },
  completed: { label: "Plan wykonany", tone: "bg-sky-100 text-sky-800" },
  ended: { label: "Zakończony", tone: "bg-gray-100 text-gray-700" },
  superseded: { label: "Przerwany", tone: "bg-amber-100 text-amber-800" },
};

// Doba RRRR-MM-DD słowami; południe UTC to ten sam dzień w strefie domu.
const dayText = (day) => formatSimDate(`${day}T12:00:00Z`);
// Data bez dnia tygodnia: po „jak” nazwa dnia wymagałaby odmiany („w niedzielę”), której Intl nie daje.
const historyDayFormat = new Intl.DateTimeFormat("pl-PL", {
  day: "numeric", month: "long", year: "numeric", timeZone: "Europe/Warsaw",
});
const historyDayText = (day) => historyDayFormat.format(new Date(`${day}T12:00:00Z`));

const actionText = (action) => {
  if (action.status === "rejected") return `Odrzucone: ${action.detail || action.code}`;
  const window = `${formatSimTime(action.start)}–${formatSimTime(action.end)}`;
  return action.status === "accepted" ? `Uruchomione, ${window}` : `Zaplanowane na ${window}`;
};

// Produkcja PV ma znak ujemny; na ekranie pokazujemy ją jako dodatnią z dopiskiem „produkcji”.
// Math.abs, a nie minus: przed pierwszą produkcją -0 wyświetliłoby się jako „-0,00”.
const historyEnergy = (device) =>
  device.history_kwh < 0
    ? `${formatKwh(Math.abs(device.actual_kwh))} z ${formatKwh(Math.abs(device.history_kwh))} produkcji`
    : `${formatKwh(device.actual_kwh)} z ${formatKwh(device.history_kwh)}`;

// PV oraz pompa ciepła i bojler spoza planu pracują same, jak w dniu referencyjnym. Dzień liczymy dla każdego
// urządzenia osobno (jak plan); zwykle jest wspólny, więc wtedy podajemy go raz, w nagłówku.
function HistoryDevices({ run }) {
  const devices = run.replayed_devices;
  if (!devices.length) return null;
  const sameDay = devices.every((device) => device.history_day === devices[0].history_day);
  return (
    <section className="mt-4" aria-label="Z dnia referencyjnego">
      <p className="text-sm text-gray-700">
        {sameDay ? `Pracują same, tak jak ${historyDayText(devices[0].history_day)}:` : "Pracują same, tak jak w dniu referencyjnym:"}
      </p>
      <ul className="mt-1 space-y-0.5 text-sm text-gray-600">
        {devices.map((device) => (
          <li key={device.device_id}>
            {device.device_name}
            {!sameDay && ` (jak ${historyDayText(device.history_day)})`}: {historyEnergy(device)}
          </li>
        ))}
      </ul>
    </section>
  );
}

// Przebieg zatwierdzonego planu w symulacji (ZP-113): postęp, energia urządzeń z planu i awarie. Od ZP-114
// w trakcie przebiegu na żywo odchylenia od planu (awarie są wśród nich), a po zakończeniu rachunek bez planu
// i z planem: w trakcie liczyłby się co chwilę od nowa i tylko zaśmiecał kartę.
// „Zakończ” kasuje zaplanowane komendy przebiegu (plan i historię), zatrzymuje zegar i zamyka przebieg;
// do chwilowej przerwy służy Pauza. Bez `onEnd` (przebieg z historii) karta jest tylko do odczytu.
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
            Plan dnia: {dayText(run.plan_date)}
          </h3>
          <p className="text-sm text-gray-600">
            {run.sim_time ? `Czas symulacji ${formatSimTime(run.sim_time)}` : "Czas symulacji nieznany"}
            {` · plan do ${formatSimTime(run.horizon_end)} następnego dnia`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className={`inline-flex px-2.5 py-1 rounded-full text-xs font-semibold ${status.tone}`}>{status.label}</span>
          {running && onEnd && (
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

      {run.cost && !running && <PlanRunCost cost={run.cost} />}
      {run.cost && running && (
        <p className="mt-3 text-sm text-gray-600">Rachunek bez planu i z planem pojawi się po zakończeniu planu.</p>
      )}

      <HistoryDevices run={run} />

      {running && (
        <p className="mt-3 text-xs text-gray-500">
          Urządzenia stałe (światło, czajnik, TV…) włącza się ręcznie na liście niżej: widać wtedy, jak razem
          z planem obciążają przyłącze.
        </p>
      )}

      {run.cost && running && run.cost.deviations.length > 0 && (
        <div className="mt-4 p-3 rounded border border-amber-200 bg-amber-50 text-amber-900" role="alert">
          <p className="flex items-center gap-1.5 text-sm font-semibold">
            <FiAlertTriangle aria-hidden="true" /> Odchylenia od planu
          </p>
          <div className="mt-1">
            <DeviationList deviations={run.cost.deviations} />
          </div>
        </div>
      )}

      {!run.cost && run.errors.length > 0 && (
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
