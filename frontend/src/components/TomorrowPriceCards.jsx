import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { FiTrendingDown, FiTrendingUp } from "react-icons/fi";
import apiClient from "../api/client";
import { useCurrentUser } from "../hooks/useCurrentUser";
import { getApiErrorMessage } from "../utils/energyFiles";
import { describeFlatPrices, describeUnavailable, describeWindow, formatWindowHours } from "../utils/priceInsights";

const CARD = "bg-white p-5 md:p-6 rounded-lg shadow-sm border-x border-x-gray-100 border-y-4";
const NOTE = "rounded-lg border border-gray-200 bg-white px-4 py-3 text-sm text-gray-700 shadow-sm";
const LINK = "font-semibold text-emerald-700 underline hover:text-emerald-800";
// Cennik operatora nie obejmuje jutra: nie podajemy godziny, bo publikacja cen PSE tego nie zmieni.
const NO_TARIFF_DATA =
  "Nie mamy jeszcze cennika taryfy dynamicznej Twojego operatora na jutro, więc nie pokażemy, kiedy prąd będzie najtańszy.";

const VARIANTS = {
  cheapest: {
    title: "Jutro najtaniej",
    Icon: FiTrendingDown,
    card: "border-y-emerald-500",
    accent: "text-emerald-700",
    badge: "bg-emerald-50 text-emerald-700",
  },
  most_expensive: {
    title: "Jutro najdrożej",
    Icon: FiTrendingUp,
    card: "border-y-rose-500",
    accent: "text-rose-700",
    badge: "bg-rose-50 text-rose-700",
  },
};

function WindowCard({ variant, window }) {
  const { title, Icon, card, accent, badge } = VARIANTS[variant];
  return (
    <div className={`${CARD} ${card}`} data-testid={`price-card-${variant}`}>
      <p className="mb-2 flex items-center gap-2 text-sm font-medium text-gray-500">
        <span className={`inline-flex h-6 w-6 items-center justify-center rounded ${badge}`} aria-hidden="true">
          <Icon />
        </span>
        {title}
      </p>
      <p className={`text-2xl md:text-3xl font-bold ${accent}`}>{formatWindowHours(window)}</p>
      <p className="mt-1 text-sm text-gray-600">{describeWindow(window)}</p>
    </div>
  );
}

// Karty z cenami oferty dynamicznej na jutro. Nie zależą od wgranego pliku, tylko od profilu (operator).
function TomorrowPriceCards() {
  const { profileTariff } = useCurrentUser();
  const [insights, setInsights] = useState(null);
  const [error, setError] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const { data } = await apiClient.get("/dynamic-prices/tomorrow/insights", { params: { window: "2h" } });
      setInsights(data);
      setError(null);
    } catch (err) {
      setInsights(null);
      setError({
        missingProfile: err?.response?.status === 409,
        message: getApiErrorMessage(err, "Nie udało się pobrać cen na jutro."),
      });
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (!cancelled) load();
    });
    return () => {
      cancelled = true;
    };
  }, [load]);

  // Bez profilu prosi o niego już baner ProfileTariffNotice nad kartami, więc nie powtarzamy tej prośby.
  // Notka zostaje, gdy profil jest, ale backend go nie przyjął (409 przy niepełnym profilu).
  if (error?.missingProfile && profileTariff?.exists === false) return null;

  let content;
  if (isLoading && !insights && !error) {
    content = <p className={`${NOTE} text-gray-500`}>Sprawdzamy ceny na jutro…</p>;
  } else if (error?.missingProfile) {
    content = (
      <p className={NOTE}>
        <Link to="/profile" className={LINK}>
          Uzupełnij profil
        </Link>
        , żeby zobaczyć, kiedy jutro prąd będzie najtańszy i najdroższy.
      </p>
    );
  } else if (error) {
    content = (
      <p className={NOTE} role="alert">
        {error.message}{" "}
        <button type="button" onClick={load} className={LINK}>
          Spróbuj ponownie
        </button>
      </p>
    );
  } else if (insights.status === "no_tariff_data") {
    content = <p className={NOTE}>{NO_TARIFF_DATA}</p>;
  } else if (insights.status !== "available") {
    content = <p className={NOTE}>{describeUnavailable(insights)}</p>;
  } else if (insights.flat_prices) {
    content = <p className={NOTE}>{describeFlatPrices(insights)}</p>;
  } else {
    content = (
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 md:gap-6">
        <WindowCard variant="cheapest" window={insights.cheapest} />
        <WindowCard variant="most_expensive" window={insights.most_expensive} />
      </div>
    );
  }

  return (
    <section aria-label="Ceny prądu na jutro" className="mb-6 md:mb-8">
      {content}
      {/* Bez cennika nie ma czego porównywać, więc nie odsyłamy do analizy taryf. */}
      {insights && !insights.profile_dynamic && insights.status !== "no_tariff_data" && (
        <p className="mt-3 text-xs md:text-sm text-gray-500">
          To ceny taryfy dynamicznej
          {profileTariff?.tariff_type ? `, a Ty masz taryfę ${profileTariff.tariff_type}` : ", której teraz nie masz"}.{" "}
          <Link to="/tariffs" className={LINK}>
            Sprawdź w analizie taryf
          </Link>
          , czy taryfa dynamiczna by Ci się opłacała.
        </p>
      )}
    </section>
  );
}

export default TomorrowPriceCards;
