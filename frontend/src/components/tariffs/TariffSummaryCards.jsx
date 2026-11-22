import { formatPln } from "../../utils/tariffs";
import { comparisonSummary } from "../../utils/tariffComparison";

function Card({ title, value, hint, accent = false }) {
  return (
    <div className={`rounded-xl border p-4 ${accent ? "border-emerald-200 bg-emerald-50" : "border-gray-200 bg-white"}`}>
      <p className="text-xs font-medium uppercase tracking-wide text-gray-500">{title}</p>
      <p className={`mt-2 text-xl md:text-2xl font-bold ${accent ? "text-emerald-700" : "text-gray-900"}`}>{value}</p>
      {hint && <p className="mt-1 text-xs md:text-sm text-gray-500">{hint}</p>}
    </div>
  );
}

function TariffSummaryCards({ comparison }) {
  const { selected, cheapest, saving } = comparisonSummary(comparison);
  const ownTitle = selected?.is_profile ? "Twoja taryfa" : "Taryfa odniesienia";

  let savingValue = "—";
  let savingHint = selected ? null : "Brak kwoty dla taryfy odniesienia.";
  if (saving != null && saving > 0) {
    savingValue = formatPln(saving);
    savingHint = `w tym okresie po przejściu na ${cheapest.label}`;
  } else if (saving != null) {
    savingValue = formatPln(0);
    savingHint = selected.is_profile ? "Masz już najtańszą taryfę." : "To najtańsza taryfa.";
  }

  return (
    <div className="mb-6 grid gap-3 md:gap-4 sm:grid-cols-3">
      <Card
        title={ownTitle}
        value={selected ? formatPln(selected.payable_gross) : "—"}
        hint={selected ? [selected.label, selected.name].filter(Boolean).join(" · ") : null}
      />
      <Card
        title="Najtańsza"
        value={cheapest ? formatPln(cheapest.payable_gross) : "—"}
        hint={cheapest ? [cheapest.label, cheapest.name].filter(Boolean).join(" · ") : "Żadnej taryfy nie udało się policzyć."}
      />
      <Card title="Możesz zaoszczędzić" value={savingValue} hint={savingHint} accent={saving != null && saving > 0} />
    </div>
  );
}

export default TariffSummaryCards;
