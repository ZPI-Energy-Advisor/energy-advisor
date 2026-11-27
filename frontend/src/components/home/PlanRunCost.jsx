import { formatKwh, formatNumber, formatPln, formatSimTime, periodLabel } from "../../utils/home";
import MoreInfo from "../MoreInfo";

const DEVIATION_LABELS = {
  rejected: "Odrzucona komenda",
  device_error: "Awaria",
  interrupted: "Wyłączone ręcznie",
  manual_start: "Włączone ręcznie",
  energy_mismatch: "Inne zużycie",
  grid_limit: "Limit przyłącza",
};

const names = (devices) => devices.map((device) => device.device_name).join(", ");

const deviationTime = (deviation) => {
  if (!deviation.sim_time) return "";
  return deviation.end
    ? `${formatSimTime(deviation.sim_time)}–${formatSimTime(deviation.end)} `
    : `${formatSimTime(deviation.sim_time)} `;
};

// Odchylenia od planu: w karcie przebiegu na żywo i w szczegółach rachunku.
export function DeviationList({ deviations }) {
  return (
    <ul className="space-y-0.5 text-sm" aria-label="Odchylenia od planu">
      {deviations.map((deviation, index) => (
        // Indeks w kluczu: lista jest tylko do odczytu, a to samo odchylenie może się powtórzyć.
        <li key={`${index}-${deviation.kind}-${deviation.device_id}`}>
          {deviationTime(deviation)}
          <strong>{DEVIATION_LABELS[deviation.kind] ?? deviation.kind}</strong>
          {deviation.device_name ? ` – ${deviation.device_name}` : ""}: {deviation.message}
          {deviation.excluded ? " (poza porównaniem)" : ""}
        </li>
      ))}
    </ul>
  );
}

// „(12% ich zużycia)”: jaka część energii urządzeń z planu poszła prosto z paneli.
const pvShare = (pv) =>
  pv.plan_kwh > 0 ? ` (${formatNumber((pv.plan_from_pv_kwh / pv.plan_kwh) * 100, 0)}% ich zużycia)` : "";

// Koszt według planu tylko wtedy, gdy różni się od zmierzonego (o co najmniej grosz): przy planie wykonanym
// co do kWh to ta sama kwota drugi raz.
const plannedHint = (cost) =>
  Math.abs(cost.cost_after - cost.planned_cost) >= 0.01 ? `według planu ${formatPln(cost.planned_cost)}` : null;

function Amount({ label, value, hint, accent = false }) {
  return (
    <div className={`p-3 rounded border ${accent ? "border-emerald-200 bg-emerald-50" : "border-gray-200 bg-gray-50"}`}>
      <p className="text-xs text-gray-600">{label}</p>
      <p className={`text-lg font-semibold tabular-nums ${accent ? "text-emerald-800" : "text-gray-900"}`}>{value}</p>
      {hint && <p className="text-xs text-gray-600">{hint}</p>}
    </div>
  );
}

function Fact({ label, children }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-gray-600">{label}</dt>
      <dd className="text-right text-gray-900">{children}</dd>
    </div>
  );
}

// Rachunek przed i po planie (ZP-114) po zakończeniu przebiegu: urządzenia z planu bez planu (start bazowy
// z planu) i z planem (zmierzone w symulacji), tymi samymi cenami. Urządzenia stałe i PV są poza oszczędnością:
// na wierzchu tylko ich sumy, a szczegóły i odchylenia pod „Więcej”.
function PlanRunCost({ cost, horizonStart = null }) {
  const percent = cost.saving_percent == null ? null : `${formatNumber(cost.saving_percent, 1)}% kosztu bez planu`;
  const hasDetails = cost.manual.length > 0 || cost.pv || cost.deviations.length > 0;
  const outsideHouse = cost.manual.length > 0 || cost.pv;
  return (
    <section className="mt-4" aria-label="Rachunek przed i po">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <h4 className="text-sm font-semibold text-gray-900">Koszt zaplanowanych urządzeń</h4>
        {!cost.complete && (
          <span
            className="inline-flex px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-800"
            title={`Porównane są urządzenia, które skończyły pracę do ${formatSimTime(cost.until)}.`}
          >
            niepełny
          </span>
        )}
        {horizonStart && (
          <p className="ml-auto text-xs text-gray-500 tabular-nums">{periodLabel({ day_start: horizonStart, until: cost.until })}</p>
        )}
      </div>

      <MoreInfo className="mt-1">
        <p>
          Liczymy tylko te urządzenia: pracę o zwykłych godzinach z historii i o godzinach z harmonogramu, zmierzoną
          w symulacji. Te same ceny kwadransów taryfy, bez opłat stałych i bez odliczenia energii z PV.
        </p>
      </MoreInfo>

      <div className="mt-2 grid grid-cols-1 sm:grid-cols-3 gap-2">
        <Amount label="Bez planu" value={formatPln(cost.cost_before)} />
        <Amount label="Z planem" value={formatPln(cost.cost_after)} hint={plannedHint(cost)} />
        <Amount label="Oszczędność" value={formatPln(cost.saving)} hint={percent} accent />
      </div>

      {cost.devices.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-600 border-b border-gray-200">
                <th className="py-1.5 pr-2 font-medium">Urządzenie</th>
                <th className="py-1.5 px-2 font-medium text-right">Bez planu</th>
                <th className="py-1.5 px-2 font-medium text-right">Z planem</th>
                <th className="py-1.5 pl-2 font-medium text-right">Oszczędność</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {cost.devices.map((device) => (
                <tr key={device.device_id}>
                  <td className="py-1.5 pr-2 text-gray-900">{device.device_name}</td>
                  <td className="py-1.5 px-2 text-right tabular-nums text-gray-700">{formatPln(device.cost_before)}</td>
                  <td className="py-1.5 px-2 text-right tabular-nums text-gray-700">{formatPln(device.cost_after)}</td>
                  <td className="py-1.5 pl-2 text-right tabular-nums font-medium text-gray-900">{formatPln(device.saving)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <dl className="mt-3 space-y-1 text-sm" aria-label="Poza porównaniem">
        {cost.excluded.length > 0 && <Fact label="Poza porównaniem">{names(cost.excluded)}</Fact>}
        {cost.pending.length > 0 && <Fact label="Nie skończyły pracy">{names(cost.pending)}</Fact>}
        {cost.deviations.length > 0 && <Fact label="Odchylenia">{cost.deviations.length}</Fact>}
      </dl>

      {outsideHouse && (
        <div className="mt-3 rounded border border-dashed border-gray-300 p-3 text-sm" role="group" aria-label="Reszta domu">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
            Reszta domu <span className="font-normal normal-case tracking-normal">· nie wchodzi do oszczędności</span>
          </p>
          <dl className="mt-1 space-y-1">
            {cost.manual.length > 0 && <Fact label="Włączone ręcznie">{formatPln(cost.manual_cost)}</Fact>}
            {cost.pv && (
              <Fact label="PV">
                {formatKwh(cost.pv.production_kwh)}, z tego plan {formatKwh(cost.pv.plan_from_pv_kwh)}
              </Fact>
            )}
          </dl>
        </div>
      )}

      {hasDetails && (
        <details className="mt-2 text-sm text-gray-700">
          <summary className="cursor-pointer text-gray-600 hover:text-gray-900">Więcej</summary>
          <div className="mt-2 space-y-2">
            {cost.manual.length > 0 && (
              <p>
                Włączone ręcznie:{" "}
                {cost.manual.map((device) => `${device.device_name} ${formatKwh(device.energy_kwh)} (${formatPln(device.cost)})`).join(", ")}.
              </p>
            )}
            {cost.pv && (
              <p>
                PV wyprodukowało {formatKwh(cost.pv.production_kwh)}. Od razu w domu zużyto{" "}
                {formatKwh(cost.pv.self_consumption_kwh)}, z czego {formatKwh(cost.pv.plan_from_pv_kwh)} wzięły
                urządzenia z planu{pvShare(cost.pv)}.
              </p>
            )}
            {cost.deviations.length > 0 && <DeviationList deviations={cost.deviations} />}
          </div>
        </details>
      )}
    </section>
  );
}

export default PlanRunCost;
