import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { FiAlertTriangle, FiCheckCircle, FiDroplet, FiEdit2, FiHome, FiLoader, FiPlay, FiRefreshCw, FiSun } from "react-icons/fi";
import ActionCards from "./ActionCards";
import Dialog from "./Dialog";
import HeatPumpPlanCard from "./HeatPumpPlanCard";
import IndoorTemperatureChart from "./IndoorTemperatureChart";
import MoreInfo from "./MoreInfo";
import PvPlanCard from "./PvPlanCard";
import ScheduleDayChart from "./ScheduleDayChart";
import WaterTemperatureChart from "./WaterTemperatureChart";
import { beforeRanges, forWeekdayDate, localTomorrow, momentRange, nextDay, planRows } from "../utils/dayPlan";
import { afterRanges, clockOf, conflictText, formatPln, isConflict } from "../utils/schedule";
import { formatKwh, formatPercent } from "../utils/format";
import { useIsPhone } from "../hooks/useMediaQuery";
import { CARD, CARD_FLUSH, TABLE_BODY, TABLE_HEAD, TD, TD_NUMBER, TH, TH_NUMBER, WIDE_TABLE, alertClass, buttonClass } from "./uiStyles";

// Miejsce przycisku głównego: „Zatwierdź plan”, a po zatwierdzeniu „Uruchom symulację”. Stała szerokość,
// żeby po zatwierdzeniu przycisk i przyciski obok nie przeskakiwały, a podpis łamał się pod przyciskiem.
const PRIMARY_SLOT = "w-full sm:w-64 sm:shrink-0";
// Przycisk główny: wciśnięcie widać (lekkie zmniejszenie i ciemniejszy kolor), a w trakcie żądania kręci się ikona.
const PRIMARY_BUTTON =
  `${buttonClass("primary", "lg")} w-full shadow-sm transition duration-150 active:scale-[0.97] ` +
  "disabled:cursor-wait disabled:active:scale-100";
const SPINNER = <FiLoader aria-hidden="true" className="animate-spin" />;
// Przyciski obok głównego: ta sama wysokość, mniejsze odstępy i tekst bez łamania, żeby na komputerze wszystkie
// (ustawienia, woda, dom) mieściły się w jednym rzędzie z „Zatwierdź plan”.
const SECONDARY_BUTTON = `${buttonClass("secondary")} w-full sm:w-auto min-w-0 max-w-full whitespace-nowrap py-3`;

function settingLabel(label, device, devices) {
  return devices.length > 1 ? `${label}: ${device.device_name}` : label;
}

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
  plan.cost_before > 0 ? formatPercent(plan.saving / plan.cost_before) : null;

// `surplus`: plan ma nadwyżkę z paneli (ZP-121), więc przesuwanie pod słońce obniża rachunek także przy stałej cenie.
export function FlatTariffNote({ surplus = false }) {
  if (surplus) {
    return (
      <p className={alertClass("info")}>
        Masz taryfę ze stałą ceną przez całą dobę, więc plan przesuwa urządzenia tylko pod słońce: w godzinach
        nadwyżki z paneli prąd jest tańszy niż z sieci.
      </p>
    );
  }
  return (
    <p className={alertClass("warning")}>
      Masz taryfę ze stałą ceną przez całą dobę, więc przesuwanie urządzeń prawie nie obniży rachunku.{" "}
      <Link to="/tariffs" className="font-semibold underline">Sprawdź w Analizie taryf</Link>, ile dałaby taryfa
      G12 albo dynamiczna.
    </p>
  );
}

const SURPLUS_KWH = 0.05;
const hasSurplus = (pv) =>
  Boolean(pv) && Math.max(pv.before?.export_kwh ?? 0, pv.after?.export_kwh ?? 0) > SURPLUS_KWH;

const PV_REASONS = {
  no_weather: "Nie ma prognozy pogody na ten dzień, więc plan liczy się bez paneli.",
  no_forecast: "Plan nie ma prognozy produkcji z paneli, więc liczy się bez nich.",
  no_profile: "Bez profilu nie znamy paneli, więc plan liczy się bez nich.",
};

const pvNote = (plan) => {
  if (plan.pv) return plan.pv.hours?.length ? null : "Prognoza nie daje tego dnia prądu z paneli.";
  return PV_REASONS[plan.pv_reason] ?? null;
};

const fromPanels = (item) =>
  item.pv_kwh >= SURPLUS_KWH ? `${formatKwh(item.pv_kwh)} z ${formatKwh(item.energy_kwh)} z paneli` : null;

// Plan pracy urządzeń na dzień (ZP-112): koszt i ostrzeżenia, oś doby na tle cen, tabela przydziałów,
// przyciski, a na końcu uwagi; temperatura wody w okienku.
// `onRun`: uruchomienie zatwierdzonego planu w symulacji domu; null, gdy konto nie ma domu Smart Home.
function DayPlanView({
  plan, flatTariff, onApprove, onEdit, onReplan,
  replanNote = null, isApproving, isReplanning, approveError,
  onRun = null, isStartingRun = false, runError = null,
}) {
  const [waterHeater, setWaterHeater] = useState(null);
  const closeWaterHeater = useCallback(() => setWaterHeater(null), []);
  // Pompa ciepła, której temperaturę w domu pokazuje okienko (jak temperatura wody bojlera).
  const [indoorPump, setIndoorPump] = useState(null);
  const closeIndoorPump = useCallback(() => setIndoorPump(null), []);
  const indoorPumps = (plan.heat_pumps ?? []).filter((pump) => pump.mode === "indoor" && pump.temperatures?.length);
  const approved = plan.status === "approved";
  const ideal = plan.kind === "past_day";
  const outdated = !ideal && plan.plan_date < localTomorrow();
  const rows = planRows(plan.items);
  const isPhone = useIsPhone();
  const conflicts = plan.items.filter(isConflict);
  const heaters = plan.water_heaters ?? [];
  const warnings = plan.warnings ?? [];

  return (
    <div className="space-y-4">
      {outdated && (
        <div className={`${alertClass("warning")} flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between`} role="status">
          <div>
            <p>To plan na {forWeekdayDate(plan.plan_date)}, czyli nie na jutro.</p>
            {replanNote && <p className="mt-1">{replanNote}</p>}
          </div>
          <button type="button" className={SECONDARY_BUTTON} onClick={onReplan} disabled={isReplanning}>
            <FiRefreshCw aria-hidden="true" /> {isReplanning ? "Układanie planu..." : "Ułóż plan na jutro"}
          </button>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-gray-900">
            {ideal ? "Plan idealny na" : "Plan na"} {forWeekdayDate(plan.plan_date)}
          </h3>
          <p className="text-xs text-gray-500">Ceny: {plan.pricing}</p>
          {ideal && (
            <p className="text-xs text-gray-500">
              Pogoda z archiwum · bez planu:{" "}
              {plan.day_source === "files" ? "tak, jak tego dnia w plikach urządzeń" : "z ustawień i historii"}
            </p>
          )}
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

      {flatTariff && <FlatTariffNote surplus={hasSurplus(plan.pv)} />}

      {warnings.length > 0 && (
        <ul className={`${alertClass("warning")} space-y-1`} role="alert">
          {warnings.map((warning) => (
            <li key={warning} className="flex gap-2">
              <FiAlertTriangle aria-hidden="true" className="mt-0.5 shrink-0" /> {warning}
            </li>
          ))}
        </ul>
      )}

      {plan.pv && <PvPlanCard pv={plan.pv} weather={plan.weather} />}
      {(plan.heat_pumps ?? []).map((pump) => <HeatPumpPlanCard key={pump.device_id} pump={pump} planDate={plan.plan_date} />)}

      <div className="flex flex-wrap gap-4 pt-2 text-xs text-gray-600">
        <span className="flex items-center gap-1.5"><i className="w-4 h-2.5 rounded-sm bg-gray-300" /> bez planu</span>
        <span className="flex items-center gap-1.5"><i className="w-4 h-2.5 rounded-sm bg-emerald-500" /> plan, przesunięte</span>
        <span className="flex items-center gap-1.5"><i className="w-4 h-2.5 rounded-sm bg-gray-400" /> plan, bez zmian</span>
        {plan.pv?.hours?.some((hour) => hour.surplus_kwh >= SURPLUS_KWH) && (
          <span className="flex items-center gap-1.5"><i className="w-4 h-2.5 rounded-sm bg-amber-100 border border-amber-200" /> nadwyżka z paneli</span>
        )}
      </div>
      <ScheduleDayChart
        day={plan.plan_date}
        actions={plan.items}
        prices={plan.prices}
        weather={plan.weather}
        pv={plan.pv}
        pvNote={pvNote(plan)}
      />
      <ScheduleDayChart
        day={nextDay(plan.plan_date)}
        actions={plan.items}
        prices={plan.prices}
        subtitle={plan.approximate_from ? "do 6:00, ceny przybliżone" : "do 6:00"}
      />

      {isPhone ? (
        <ActionCards
          ariaLabel="Urządzenia w planie"
          labels={{ before: "Bez planu", after: "Według planu" }}
          items={rows.map((item) => ({
            key: item.action_id,
            name: item.device_name,
            program: item.program_name,
            before: beforeRanges(item),
            after: afterRanges(item, { withDay: true }),
            afterNote: item.status === "unchanged" ? "(bez zmian)" : null,
            extra: fromPanels(item),
            costBefore: item.cost_before,
            costAfter: item.cost_after,
          }))}
        />
      ) : (
        <section className={`${CARD_FLUSH} overflow-x-auto`}>
          <table className={WIDE_TABLE}>
            <thead className={TABLE_HEAD}>
              <tr>
                <th scope="col" className={TH}>Urządzenie</th>
                <th scope="col" className={TH}>Bez planu</th>
                <th scope="col" className={TH}>Według planu</th>
                <th scope="col" className={TH_NUMBER}>Koszt bez planu</th>
                <th scope="col" className={TH_NUMBER}>Koszt według planu</th>
              </tr>
            </thead>
            <tbody className={TABLE_BODY}>
              {rows.map((item) => (
                <tr key={item.action_id}>
                  <td className={TD}>
                    {item.device_name}
                    {item.program_name && <span className="text-gray-500"> · {item.program_name}</span>}
                  </td>
                  <td className={TD}>{beforeRanges(item)}</td>
                  <td className={TD}>
                    {afterRanges(item, { withDay: true })}
                    {item.status === "unchanged" && <span className="text-gray-500"> (bez zmian)</span>}
                    {fromPanels(item) && (
                      <span className="mt-0.5 flex items-center gap-1 text-xs text-amber-700">
                        <FiSun aria-hidden="true" className="shrink-0" /> {fromPanels(item)}
                      </span>
                    )}
                  </td>
                  <td className={TD_NUMBER}>{formatPln(item.cost_before)}</td>
                  <td className={TD_NUMBER}>{formatPln(item.cost_after)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {conflicts.length > 0 && (
        <ul className={`${alertClass("warning")} space-y-1`}>
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
          <div className={PRIMARY_SLOT}>
            <button
              type="button"
              className={PRIMARY_BUTTON}
              onClick={onApprove}
              disabled={isApproving}
            >
              {isApproving ? <>{SPINNER} Zatwierdzanie...</> : "Zatwierdź plan"}
            </button>
            <p className="mt-1 text-xs text-gray-500">
              {onRun
                ? "Zatwierdzony plan możesz uruchomić w symulacji domu."
                : "Zapamiętamy, że plan Ci pasuje."}
            </p>
          </div>
        )}
        {/* Przycisk główny zostaje w tym samym miejscu: „Zatwierdź plan”, a po zatwierdzeniu „Uruchom symulację”
            z godziną zatwierdzenia pod spodem. */}
        {approved && !onRun && (
          <p className={`${PRIMARY_SLOT} flex items-center gap-1.5 py-3 text-sm font-medium text-emerald-700`} role="status">
            <FiCheckCircle aria-hidden="true" /> Plan zatwierdzony o {clockOf(plan.approved_at)}.
          </p>
        )}
        {approved && onRun && (
          <div className={`${PRIMARY_SLOT} animate-fade-in`}>
            <button
              type="button"
              className={PRIMARY_BUTTON}
              onClick={onRun}
              disabled={isStartingRun}
            >
              {isStartingRun ? <>{SPINNER} Uruchamianie...</> : <><FiPlay aria-hidden="true" /> Uruchom symulację</>}
            </button>
            <p className="mt-1 text-xs text-gray-500" role="status">
              <FiCheckCircle aria-hidden="true" className="inline mr-1 -mt-0.5 text-emerald-700" />
              Plan zatwierdzony o {clockOf(plan.approved_at)}. Symulacja zacznie dobę planu od północy w „Mój dom”.
            </p>
          </div>
        )}
        <div className="flex flex-col gap-3 sm:flex-1 sm:flex-row sm:flex-wrap xl:flex-nowrap" role="group" aria-label="Ustawienia planu">
          <button type="button" className={SECONDARY_BUTTON} onClick={onEdit}>
            <FiEdit2 aria-hidden="true" /> Edytuj ustawienia
          </button>
          {heaters.map((heater) => (
            <button key={heater.device_id} type="button" className={SECONDARY_BUTTON} onClick={() => setWaterHeater(heater)}>
              <FiDroplet aria-hidden="true" className="shrink-0" />
              <span className="truncate">{settingLabel("Temperatura wody", heater, heaters)}</span>
            </button>
          ))}
          {indoorPumps.map((pump) => (
            <button key={pump.device_id} type="button" className={SECONDARY_BUTTON} onClick={() => setIndoorPump(pump)}>
              <FiHome aria-hidden="true" className="shrink-0" />
              <span className="truncate">{settingLabel("Temperatura w domu", pump, indoorPumps)}</span>
            </button>
          ))}
        </div>
      </div>
      {approveError && <p className="text-sm text-red-600" role="alert">{approveError}</p>}
      {runError && <p className="text-sm text-red-600" role="alert">{runError}</p>}


      {plan.notes.length > 0 && (
        <MoreInfo summary="Jak ułożyliśmy plan">
          <ul className="p-3 text-sm text-gray-700 bg-gray-50 rounded-lg space-y-1 list-disc pl-6">
            {plan.notes.map((note) => <li key={note}>{note}</li>)}
          </ul>
        </MoreInfo>
      )}

      {waterHeater && (
        <Dialog title={`Temperatura wody: ${waterHeater.device_name}`} onClose={closeWaterHeater}>
          <WaterTemperatureChart heater={waterHeater} />
        </Dialog>
      )}
      {indoorPump && (
        <Dialog title={`Temperatura w domu: ${indoorPump.device_name}`} onClose={closeIndoorPump}>
          <IndoorTemperatureChart pump={indoorPump} />
        </Dialog>
      )}
    </div>
  );
}

export default DayPlanView;
