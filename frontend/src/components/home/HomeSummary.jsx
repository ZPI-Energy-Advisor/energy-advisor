import { formatKw, formatKwh, formatPln, periodLabel, shortDay } from "../../utils/home";
import { CARD } from "../uiStyles";

function Stat({ label, value, hint, tone = "default" }) {
  const color = { default: "text-gray-900", production: "text-emerald-700", export: "text-sky-700" }[tone];
  return (
    <div className={`${CARD} min-w-0`}>
      <p className="text-xs font-medium uppercase tracking-wide text-gray-500">{label}</p>
      <p className={`mt-1 text-xl md:text-2xl font-bold tabular-nums truncate ${color}`}>{value}</p>
      {hint && <p className="mt-1 text-xs text-gray-500">{hint}</p>}
    </div>
  );
}

// Moc chwilowa z huba i bilans ze zdarzeń energy_report (GET /home/state). Nad kafelkami bilansu stoi okres
// (`today.period`): zwykła doba od północy albo przebieg planu od jego początku, także po północy drugiego dnia,
// jak w raporcie przebiegu. Bilans dotyczy całego domu, a raport porównuje tylko urządzenia z planu.
function HomeSummary({ power, today }) {
  const exporting = power != null && power.net_kw < 0;

  return (
    <section aria-label="Podsumowanie domu" className="space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <Stat label="Pobór teraz" value={formatKw(power?.consumption_kw)} />
        <Stat label="Produkcja PV teraz" value={formatKw(power?.production_kw)} tone="production" />
        <Stat
          label={exporting ? "Oddawanie do sieci" : "Pobór z sieci"}
          value={formatKw(power ? Math.abs(power.net_kw) : null)}
          tone={exporting ? "export" : "default"}
        />
      </div>

      {today && (
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 pt-1">
          <h3 className="text-sm font-semibold text-gray-900">
            {today.period === "plan_run" && today.plan_date ? `Przebieg planu na ${shortDay(today.plan_date)}` : "Bilans doby"}{" "}
            <span className="font-normal text-gray-500">· cały dom</span>
          </h3>
          <p className="text-xs text-gray-500 tabular-nums">{periodLabel(today)}</p>
        </div>
      )}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat
          label="Zużycie"
          value={formatKwh(today?.consumption_kwh)}
          hint={today ? null : "Brak danych z tej doby"}
        />
        <Stat label="Produkcja" value={formatKwh(today?.production_kwh)} tone="production" />
        <Stat label="Pobrane z sieci" value={formatKwh(today?.grid_import_kwh)} />
        <Stat
          label="Koszt"
          value={formatPln(today?.cost_pln)}
          hint={today?.cost_error ?? "Cały dom: energia pobrana z sieci (po PV), w cenach taryfy, bez opłat stałych i bez wartości prądu oddanego do sieci"}
        />
      </div>
    </section>
  );
}

export default HomeSummary;
