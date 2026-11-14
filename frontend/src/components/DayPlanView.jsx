import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { FiAlertTriangle, FiCheckCircle, FiDroplet, FiEdit2, FiRefreshCw } from "react-icons/fi";
import Dialog from "./Dialog";
import ScheduleDayChart from "./ScheduleDayChart";
import WaterTemperatureChart from "./WaterTemperatureChart";
import { beforeRanges, localTomorrow, momentRange, nextDay, planRows, weekdayDate } from "../utils/dayPlan";
import { afterRanges, clockOf, conflictText, formatPln, isConflict } from "../utils/schedule";

const CARD = "bg-white border border-gray-200 rounded-lg p-4 md:p-5 shadow-sm";
const SECONDARY_BUTTON =
  "w-full sm:w-auto inline-flex items-center justify-center gap-2 rounded-md border border-gray-300 bg-white px-5 py-3 font-semibold text-gray-700 hover:bg-gray-50 disabled:opacity-50";

function Amount({ label, value, hint = null, accent = false }) {
  return (
    <div className={CARD}>
      <p className="text-xs text-gray-500">{label}</p>
      <p className={`mt-1 text-xl font-bold ${accent ? "text-emerald-700" : "text-gray-900"}`}>{formatPln(value)}</p>
      {hint && <p className="mt-1 text-xs text-gray-500">{hint}</p>}
    </div>
  );
}

// Jak na ekranie optymalizacji: oszczędność w procentach kosztu bez planu.
const savingPercent = (plan) =>
  plan.cost_before > 0 ? `${((plan.saving / plan.cost_before) * 100).toFixed(1).replace(".", ",")}%` : null;

export function FlatTariffNote() {
  return (
    <p className="p-3 text-sm text-amber-900 bg-amber-50 rounded-lg">
      Masz taryfę ze stałą ceną przez całą dobę, więc przesuwanie urządzeń prawie nie obniży rachunku.{" "}
      <Link to="/results" className="font-semibold underline">Sprawdź w Analizie taryf</Link>, ile dałaby taryfa
      G12 albo dynamiczna.
    </p>
  );
}

// Plan pracy urządzeń na dzień (ZP-112): koszt i ostrzeżenia, oś doby na tle cen, tabela przydziałów,
// przyciski, a na końcu uwagi; temperatura wody w okienku.
function DayPlanView({ plan, flatTariff, onApprove, onEdit, onReplan, isApproving, isReplanning, approveError }) {
  const [waterHeater, setWaterHeater] = useState(null);
  const closeWaterHeater = useCallback(() => setWaterHeater(null), []);
  const approved = plan.status === "approved";
  const outdated = plan.plan_date < localTomorrow();
  const rows = planRows(plan.items);
  const conflicts = plan.items.filter(isConflict);
  const heaters = plan.water_heaters ?? [];
  const warnings = plan.warnings ?? [];

  return (
    <div className="space-y-4">
      {outdated && (
        <div className="flex flex-col gap-3 p-3 text-sm text-amber-900 bg-amber-50 rounded-lg sm:flex-row sm:items-center sm:justify-between" role="status">
          <p>To plan na {weekdayDate(plan.plan_date)}, czyli nie na jutro.</p>
          <button type="button" className={SECONDARY_BUTTON} onClick={onReplan} disabled={isReplanning}>
            <FiRefreshCw aria-hidden="true" /> {isReplanning ? "Układanie planu..." : "Ułóż plan na jutro"}
          </button>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-gray-900">Plan na {weekdayDate(plan.plan_date)}</h3>
          <p className="text-xs text-gray-500">Ceny: {plan.pricing}</p>
        </div>
        <span
          className={`rounded-full px-3 py-1 text-xs font-semibold ${
            approved ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"
          }`}
        >
          {approved ? "Zatwierdzony" : "Szkic"}
        </span>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <Amount label="Bez planu (tak jak zwykle)" value={plan.cost_before} />
        <Amount label="Według planu" value={plan.cost_after} />
        <Amount label="Oszczędność" value={plan.saving} hint={savingPercent(plan)} accent />
      </div>

      {flatTariff && <FlatTariffNote />}

      {warnings.length > 0 && (
        <ul className="p-3 text-sm text-amber-900 bg-amber-50 rounded-lg space-y-1" role="alert">
          {warnings.map((warning) => (
            <li key={warning} className="flex gap-2">
              <FiAlertTriangle aria-hidden="true" className="mt-0.5 shrink-0" /> {warning}
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap gap-4 pt-2 text-xs text-gray-600">
        <span className="flex items-center gap-1.5"><i className="w-4 h-2.5 rounded-sm bg-gray-300" /> bez planu</span>
        <span className="flex items-center gap-1.5"><i className="w-4 h-2.5 rounded-sm bg-emerald-500" /> plan, przesunięte</span>
        <span className="flex items-center gap-1.5"><i className="w-4 h-2.5 rounded-sm bg-gray-400" /> plan, bez zmian</span>
      </div>
      <ScheduleDayChart day={plan.plan_date} actions={plan.items} prices={plan.prices} />
      <ScheduleDayChart
        day={nextDay(plan.plan_date)}
        actions={plan.items}
        prices={plan.prices}
        subtitle={plan.approximate_from ? "do 6:00, ceny przybliżone" : "do 6:00"}
      />

      <section className="bg-white rounded-lg shadow-sm border border-gray-100 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-gray-500 border-b border-gray-100">
            <tr>
              <th className="p-3 font-medium">Urządzenie</th>
              <th className="p-3 font-medium">Bez planu</th>
              <th className="p-3 font-medium">Według planu</th>
              <th className="p-3 font-medium text-right">Koszt bez planu</th>
              <th className="p-3 font-medium text-right">Koszt według planu</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((item) => (
              <tr key={item.action_id} className="border-b border-gray-50 last:border-0">
                <td className="p-3">
                  {item.device_name}
                  {item.program_name && <span className="text-gray-500"> · {item.program_name}</span>}
                </td>
                <td className="p-3">{beforeRanges(item)}</td>
                <td className="p-3">
                  {afterRanges(item, { withDay: true })}
                  {item.status === "unchanged" && <span className="text-gray-500"> (bez zmian)</span>}
                </td>
                <td className="p-3 text-right whitespace-nowrap">{formatPln(item.cost_before)}</td>
                <td className="p-3 text-right whitespace-nowrap">{formatPln(item.cost_after)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {conflicts.length > 0 && (
        <ul className="p-3 text-sm text-amber-900 bg-amber-50 rounded-lg space-y-1">
          {conflicts.map((item) => (
            <li key={item.action_id}>
              <span className="font-medium">{item.device_name} ({momentRange(item.original_start, item.original_end)}):</span>{" "}
              {conflictText(item, plan.max_grid_kw)}; zostaje na początku przedziału.
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
        {!approved && (
          <div>
            <button
              type="button"
              className="w-full sm:w-auto rounded-md bg-emerald-600 px-5 py-3 font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
              onClick={onApprove}
              disabled={isApproving}
            >
              {isApproving ? "Zatwierdzanie..." : "Zatwierdź plan"}
            </button>
            <p className="mt-1 text-xs text-gray-500">Na razie zapamiętamy, że plan Ci pasuje. Wkrótce wyślemy go do domu.</p>
          </div>
        )}
        {approved && (
          <p className="flex items-center gap-1.5 py-3 text-sm font-medium text-emerald-700" role="status">
            <FiCheckCircle aria-hidden="true" /> Plan zatwierdzony o {clockOf(plan.approved_at)}.
          </p>
        )}
        <button type="button" className={SECONDARY_BUTTON} onClick={onEdit}>
          <FiEdit2 aria-hidden="true" /> Edytuj ustawienia
        </button>
        {heaters.map((heater) => (
          <button key={heater.device_id} type="button" className={SECONDARY_BUTTON} onClick={() => setWaterHeater(heater)}>
            <FiDroplet aria-hidden="true" /> Temperatura wody
          </button>
        ))}
        {approveError && <p className="text-sm text-red-600" role="alert">{approveError}</p>}
      </div>


      {plan.notes.length > 0 && (
        <section>
          <h4 className="text-sm font-medium text-gray-700">Jak ułożyliśmy plan</h4>
          <ul className="mt-2 p-3 text-sm text-gray-700 bg-gray-50 rounded-lg space-y-1 list-disc pl-6">
            {plan.notes.map((note) => <li key={note}>{note}</li>)}
          </ul>
        </section>
      )}

      {waterHeater && (
        <Dialog title={`Temperatura wody: ${waterHeater.device_name}`} onClose={closeWaterHeater}>
          <WaterTemperatureChart heater={waterHeater} />
        </Dialog>
      )}
    </div>
  );
}

export default DayPlanView;
