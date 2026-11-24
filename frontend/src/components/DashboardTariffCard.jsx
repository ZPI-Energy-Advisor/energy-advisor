import { Link } from "react-router-dom";
import { FiArrowRight, FiCheckCircle } from "react-icons/fi";
import { useEnergyFiles } from "../hooks/useEnergyFiles";
import { useTariffComparison } from "../hooks/useTariffComparison";
import { formatPln } from "../utils/tariffs";
import { entryLabel, findEntry, formatPercent } from "../utils/tariffComparison";

const CARD =
  "bg-white p-5 md:p-6 rounded-lg shadow-sm border border-gray-100 hover:shadow-md transition-shadow relative sm:col-span-2 md:col-span-1";
const LINK = "inline-flex items-center gap-1 text-sm font-medium text-emerald-600 hover:text-emerald-700 hover:underline";

function CompareLink({ children = "Porównaj taryfy" }) {
  return (
    <Link to="/tariffs" className={LINK}>
      {children} <FiArrowRight aria-hidden="true" />
    </Link>
  );
}

// Dotychczasowa treść karty: sama taryfa z profilu (gdy porównania nie ma albo się nie udało).
function CurrentTariff({ title, profileTariff, currentTariff, loadError }) {
  return (
    <>
      <p className="text-sm font-medium text-gray-500 mb-3">{title}</p>
      <p className="text-lg md:text-xl font-bold text-gray-900">
        {profileTariff?.tariff_type
          ? `Taryfa ${currentTariff?.label ?? profileTariff.tariff_type}${currentTariff ? ` · ${currentTariff.operator}` : ""}`
          : loadError
            ? "Nie udało się pobrać taryfy"
            : "Nie znamy jeszcze Twojej taryfy"}
      </p>
      <Link to="/profile" className="mt-2 inline-block text-sm font-medium text-emerald-600 hover:text-emerald-700 hover:underline">
        {profileTariff?.exists ? "Zmień w profilu" : loadError ? "Przejdź do profilu" : "Uzupełnij profil"}
      </Link>
    </>
  );
}

// Trzecia karta Dashboardu: ile można zaoszczędzić na innej taryfie (te same kwoty co w Analizie taryf,
// z tej samej pamięci porównań), albo potwierdzenie, że obecna taryfa jest najkorzystniejsza.
function DashboardTariffCard({ enabled, profileTariff, currentTariff, loadError }) {
  const { viewSource, cacheScope, comparisonCache } = useEnergyFiles();
  const { comparison, isLoading } = useTariffComparison(enabled ? viewSource : null, cacheScope, comparisonCache);
  const recommendation = comparison?.recommendation;
  const recommended = findEntry(comparison, recommendation?.tariff);
  const accent = <div className="absolute top-0 left-0 w-full h-1 bg-emerald-500 rounded-t-lg" />;
  const current = { profileTariff, currentTariff, loadError };

  if (!comparison && isLoading) {
    return (
      <div className={CARD} role="status">
        {accent}
        <span className="sr-only">Liczymy porównanie taryf...</span>
        <div aria-hidden="true" className="h-4 w-1/2 animate-pulse rounded bg-gray-200/70" />
        <div aria-hidden="true" className="mt-4 h-8 w-2/3 animate-pulse rounded bg-gray-200/70" />
        <div aria-hidden="true" className="mt-3 h-3 w-3/4 animate-pulse rounded bg-gray-200/70" />
      </div>
    );
  }

  if (comparison?.from_profile && recommendation && recommended) {
    if (recommendation.is_current) {
      return (
        <div className={CARD}>
          {accent}
          <CurrentTariff title="Twoja taryfa" {...current} />
          <p className="mt-3 flex items-start gap-2 text-sm text-emerald-700">
            <FiCheckCircle aria-hidden="true" className="mt-0.5 shrink-0" />
            Najkorzystniejsza z taryf operatora w tym okresie.
          </p>
          <div className="mt-2">
            <CompareLink />
          </div>
        </div>
      );
    }
    if (recommendation.saving != null) {
      const percent = formatPercent(recommendation.saving_percent);
      return (
        <div className={`${CARD} border-emerald-200 bg-emerald-50/60`}>
          {accent}
          <p className="text-sm font-medium text-gray-500 mb-2">Możesz zaoszczędzić</p>
          <p className="text-2xl md:text-3xl font-bold text-emerald-700">
            {formatPln(recommendation.saving)}
            {percent && <span className="ml-2 text-base font-semibold text-emerald-600">({percent})</span>}
          </p>
          <p className="mt-2 text-sm text-gray-700">
            w tym okresie na <span className="font-semibold">{entryLabel(recommended)}</span>
          </p>
          <div className="mt-3">
            <CompareLink>Zobacz analizę taryf</CompareLink>
          </div>
        </div>
      );
    }
  }

  return (
    <div className={CARD}>
      {accent}
      <CurrentTariff title="Aktualna taryfa" {...current} />
    </div>
  );
}

export default DashboardTariffCard;
