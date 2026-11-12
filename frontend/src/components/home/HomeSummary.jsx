import { formatKw, formatKwh, formatPln, formatSimTime } from "../../utils/home";

function Stat({ label, value, hint, tone = "default" }) {
  const color = { default: "text-gray-900", production: "text-emerald-700", export: "text-sky-700" }[tone];
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm min-w-0">
      <p className="text-xs font-medium uppercase tracking-wide text-gray-500">{label}</p>
      <p className={`mt-1 text-xl md:text-2xl font-bold tabular-nums truncate ${color}`}>{value}</p>
      {hint && <p className="mt-1 text-xs text-gray-500">{hint}</p>}
    </div>
  );
}

// Moc chwilowa z huba i bilans doby ze zdarzeń energy_report (GET /home/state).
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

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat
          label="Zużycie dziś"
          value={formatKwh(today?.consumption_kwh)}
          hint={today ? `od północy do ${formatSimTime(today.until)}` : "Brak danych z tej doby"}
        />
        <Stat label="Produkcja dziś" value={formatKwh(today?.production_kwh)} tone="production" />
        <Stat label="Pobrane z sieci" value={formatKwh(today?.grid_import_kwh)} />
        <Stat
          label="Koszt dziś"
          value={formatPln(today?.cost_pln)}
          hint={today?.cost_error ?? "Energia z sieci w cenach taryfy, bez opłat stałych"}
        />
      </div>
    </section>
  );
}

export default HomeSummary;
