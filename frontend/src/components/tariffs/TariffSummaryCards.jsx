import { Link } from "react-router-dom";
import { FiAlertCircle, FiCheckCircle } from "react-icons/fi";
import { formatDate } from "../../utils/energyFiles";
import { formatPln } from "../../utils/tariffs";
import { entryLabel, findEntry, formatPercent, isPriced, profileEntry } from "../../utils/tariffComparison";

const LINK = "font-semibold text-emerald-700 underline";

function Card({ title, value, children, accent = false, icon = null }) {
  return (
    <section
      aria-label={title}
      className={`rounded-xl border p-4 ${accent ? "border-emerald-200 bg-emerald-50" : "border-gray-200 bg-white"}`}
    >
      <h3 className="text-xs font-medium uppercase tracking-wide text-gray-500">{title}</h3>
      <p className={`mt-2 flex items-center gap-2 text-xl md:text-2xl font-bold ${accent ? "text-emerald-700" : "text-gray-900"}`}>
        {icon}
        {value}
      </p>
      <div className="mt-1 space-y-0.5 text-xs md:text-sm text-gray-600">{children}</div>
    </section>
  );
}

function CostSplit({ entry }) {
  return (
    <p className="text-gray-500">
      za kWh {formatPln(entry.energy_cost_pln)} · opłaty mies. {formatPln(entry.monthly_fees_pln)}
    </p>
  );
}

function OwnTariffCard({ comparison, own }) {
  if (!comparison.from_profile) {
    return (
      <Card title="Twoja taryfa" value="—">
        <p>
          <Link to="/profile" className={LINK}>
            Uzupełnij profil
          </Link>
          , żeby porównać taryfy z Twoją.
        </p>
      </Card>
    );
  }
  if (!isPriced(own)) {
    return (
      <Card title="Twoja taryfa" value="—">
        <p>{own?.note ?? `Operator nie ma w tym okresie stawek taryfy ${comparison.profile_tariff}.`}</p>
      </Card>
    );
  }
  return (
    <Card title="Twoja taryfa" value={formatPln(own.payable_gross)}>
      <p>{entryLabel(own)}</p>
      <CostSplit entry={own} />
    </Card>
  );
}

function CheapestCard({ cheapest }) {
  if (!cheapest) {
    return (
      <Card title="Najtańsza" value="—">
        <p>Żadnej taryfy nie udało się policzyć za cały okres.</p>
      </Card>
    );
  }
  return (
    <Card title="Najtańsza" value={formatPln(cheapest.payable_gross)}>
      <p>{entryLabel(cheapest)}</p>
      <CostSplit entry={cheapest} />
    </Card>
  );
}

function RecommendationCard({ comparison, recommendation, cheapest }) {
  const recommended = findEntry(comparison, recommendation?.tariff);
  if (!recommendation || !recommended) {
    return (
      <Card title="Rekomendacja" value="—">
        <p>Bez kompletu cen nie wskażemy najkorzystniejszej taryfy.</p>
      </Card>
    );
  }
  const period = `${formatDate(comparison.billed_from)} – ${formatDate(comparison.billed_to)}`;

  if (recommendation.is_current) {
    return (
      <Card
        title="Rekomendacja"
        value="Zostań przy swojej taryfie"
        accent
        icon={<FiCheckCircle aria-hidden="true" className="shrink-0" />}
      >
        {recommendation.difference_to_cheapest > 0 ? (
          <p>
            {cheapest.label} wyszłaby taniej tylko o {formatPln(recommendation.difference_to_cheapest)}, więc zmiana się
            nie opłaca.
          </p>
        ) : (
          <p>Masz najtańszą taryfę w okresie {period}.</p>
        )}
      </Card>
    );
  }

  if (recommendation.saving == null) {
    return (
      <Card title="Najkorzystniejsza taryfa" value={recommended.label} accent>
        {recommended.name && <p>{recommended.name}</p>}
        <p>
          {comparison.from_profile
            ? "Twojej taryfy nie policzyliśmy w tym okresie, więc nie podajemy kwoty oszczędności."
            : "Kwotę oszczędności pokażemy po uzupełnieniu profilu."}
        </p>
      </Card>
    );
  }

  const percent = formatPercent(recommendation.saving_percent);
  return (
    <Card
      title="Możesz zaoszczędzić"
      value={`${formatPln(recommendation.saving)}${percent ? ` (${percent})` : ""}`}
      accent
    >
      <p>
        w okresie {period} po przejściu na <span className="font-semibold">{entryLabel(recommended)}</span>
      </p>
    </Card>
  );
}

function SkippedTariffs({ comparison, keys }) {
  const skipped = keys.map((key) => findEntry(comparison, key)).filter(Boolean);
  if (skipped.length === 0) return null;
  return (
    <p className="mb-6 -mt-3 flex items-start gap-2 text-xs md:text-sm text-amber-800">
      <FiAlertCircle aria-hidden="true" className="mt-0.5 shrink-0" />
      <span>
        Nie rekomendujemy taryf, których nie da się policzyć w tym okresie:{" "}
        {skipped.map((entry, index) => (
          <span key={entry.key}>
            {index > 0 && ", "}
            <span title={entry.note ?? undefined} className="font-medium">
              {entry.label}
            </span>
          </span>
        ))}
        . Powód jest przy każdej z nich w tabeli.
      </span>
    </p>
  );
}

function TariffSummaryCards({ comparison }) {
  const own = profileEntry(comparison);
  const cheapest = findEntry(comparison, comparison.cheapest_tariff);
  const recommendation = comparison.recommendation;

  return (
    <>
      <div className="mb-6 grid gap-3 md:gap-4 sm:grid-cols-3">
        <OwnTariffCard comparison={comparison} own={own} />
        <CheapestCard cheapest={cheapest} />
        <RecommendationCard comparison={comparison} recommendation={recommendation} cheapest={cheapest} />
      </div>
      <SkippedTariffs comparison={comparison} keys={recommendation?.skipped_tariffs ?? []} />
    </>
  );
}

export default TariffSummaryCards;
