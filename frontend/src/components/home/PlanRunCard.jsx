import { FiAlertTriangle } from "react-icons/fi";
import { formatKwh, formatSimTime, fullDay } from "../../utils/home";
import PlanRunCost, { DeviationList } from "./PlanRunCost";

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
        {sameDay ? `Pracują same, tak jak ${fullDay(devices[0].history_day)}:` : "Pracują same, tak jak w dniu referencyjnym:"}
      </p>
      <ul className="mt-1 space-y-0.5 text-sm text-gray-600">
        {devices.map((device) => (
          <li key={device.device_id}>
            {device.device_name}
            {!sameDay && ` (jak ${fullDay(device.history_day)})`}: {historyEnergy(device)}
          </li>
        ))}
      </ul>
    </section>
  );
}

// Raport przebiegu planu w zakładce „Raporty” (ZP-114). Data i status są w wierszu listy, więc tu na wierzchu
// jest rachunek bez planu i z planem, a energia urządzeń (z planu i z historii) pod „Energia urządzeń”.
// Przebieg w trakcie nie ma jeszcze rachunku: liczyłby się co chwilę od nowa, więc pokazujemy postęp
// i odchylenia. Sterowanie przebiegiem („Zakończ”) jest w karcie zegara na zakładce „Symulacja”.
function PlanRunCard({ run }) {
  const running = run.status === "running";

  return (
    <section aria-label="Raport przebiegu">
      {run.status === "superseded" && (
        <p className="mb-3 text-sm text-amber-800">
          Symulacja zaczęła inną dobę, więc ten przebieg się zakończył. Uruchom plan ponownie na stronie planu.
        </p>
      )}

      {run.cost && !running && <PlanRunCost cost={run.cost} />}
      {running && (
        <p className="text-sm text-gray-600">
          Plan trwa: urządzenia z planu zużyły {formatKwh(run.actual_kwh)} z {formatKwh(run.planned_kwh)}. Rachunek bez
          planu i z planem pojawi się po zakończeniu.
        </p>
      )}

      {run.cost && running && run.cost.deviations.length > 0 && (
        <div className="mt-3 p-3 rounded border border-amber-200 bg-amber-50 text-amber-900" role="alert">
          <p className="flex items-center gap-1.5 text-sm font-semibold">
            <FiAlertTriangle aria-hidden="true" /> Odchylenia od planu
          </p>
          <div className="mt-1">
            <DeviationList deviations={run.cost.deviations} />
          </div>
        </div>
      )}

      {!run.cost && run.errors.length > 0 && (
        <div className="mt-3 p-3 rounded border border-red-200 bg-red-50" role="alert">
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
        </div>
      )}

      <details className="mt-3 text-sm" open={!run.cost}>
        <summary className="cursor-pointer text-gray-600 hover:text-gray-900">
          Energia urządzeń: {formatKwh(run.actual_kwh)} z {formatKwh(run.planned_kwh)} według planu
        </summary>
        <ul className="mt-2 divide-y divide-gray-100 border-y border-gray-100">
          {run.devices.map((device) => (
            <li key={device.device_id} className="py-2" aria-label={device.device_name}>
              <div className="flex justify-between gap-3">
                <span className="font-medium text-gray-900">{device.device_name}</span>
                <span className="tabular-nums text-gray-700">
                  {formatKwh(device.actual_kwh)} / {formatKwh(device.planned_kwh)}
                </span>
              </div>
              {device.actions.map((action) => (
                <p key={action.action_id} className={action.status === "rejected" ? "text-red-700" : "text-gray-500"}>
                  {action.label ? `${action.label}: ` : ""}
                  {actionText(action)}
                </p>
              ))}
            </li>
          ))}
        </ul>
        <HistoryDevices run={run} />
      </details>
    </section>
  );
}

export default PlanRunCard;
