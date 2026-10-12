import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FiCalendar, FiClock } from "react-icons/fi";
import apiClient from "../api/client";
import PriceChart from "../components/PriceChart";
import PriceDataCompleteness from "../components/PriceDataCompleteness";
import PriceRangeForm from "../components/PriceRangeForm";
import { countDays, formatDate, getApiErrorMessage } from "../utils/energyFiles";
import {
  PRICE_RESOLUTIONS,
  QUARTER_HOUR_PRICES_SINCE,
  describeTariffPrice,
  formatDateTime,
  formatDaysCount,
  formatPrice,
  isResolutionAllowed,
  resolveResolution,
} from "../utils/dynamicPrices";

const toggleClass = (isActive) =>
  `flex-1 sm:flex-none px-3 md:px-4 py-1.5 text-xs md:text-sm font-medium rounded-md transition-all whitespace-nowrap disabled:opacity-40 disabled:cursor-not-allowed ${
    isActive ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-700"
  }`;

function StatTile({ label, value, hint }) {
  return (
    <div className="bg-white p-4 md:p-5 rounded-lg shadow-sm border border-gray-100">
      <p className="text-xs md:text-sm font-medium text-gray-500 mb-1">{label}</p>
      <div className="text-lg md:text-2xl font-bold text-gray-900">{value}</div>
      {hint && <p className="mt-1 text-xs text-gray-500">{hint}</p>}
    </div>
  );
}

function DynamicPricesPage() {
  const [history, setHistory] = useState(null);
  const [resolution, setResolution] = useState("hour");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const latestRequestRef = useRef(0);

  const loadHistory = useCallback(async (range, nextResolution) => {
    const requestId = ++latestRequestRef.current;
    setIsLoading(true);
    const params = { resolution: nextResolution };
    if (range) {
      params.from = range.from;
      params.to = range.to;
    }
    try {
      const response = await apiClient.get("/dynamic-prices/history", { params });
      if (requestId !== latestRequestRef.current) return;
      setHistory(response.data);
      setResolution(nextResolution);
      setError(null);
    } catch (err) {
      if (requestId !== latestRequestRef.current) return;
      setError(getApiErrorMessage(err, "Nie udało się pobrać cen dynamicznych."));
    } finally {
      if (requestId === latestRequestRef.current) setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (!cancelled) loadHistory(null, "hour");
    });
    return () => {
      cancelled = true;
    };
  }, [loadHistory]);

  const availableFrom = history?.available_from;
  const availableTo = history?.available_to;
  const dateFrom = history?.date_from;
  const dateTo = history?.date_to;
  const bounds = useMemo(
    () => (availableFrom && availableTo ? { from: availableFrom, to: availableTo } : null),
    [availableFrom, availableTo],
  );
  const appliedRange = useMemo(
    () => (dateFrom && dateTo ? { from: dateFrom, to: dateTo } : null),
    [dateFrom, dateTo],
  );

  const applyRange = (range) => loadHistory(range, resolveResolution(resolution, range));
  const changeResolution = (value) => {
    if (value !== resolution && appliedRange) loadHistory(appliedRange, value);
  };

  if (isLoading && !history) {
    return <div className="p-10 text-gray-500">Ładowanie cen dynamicznych...</div>;
  }

  const hasAnyPrices = Boolean(bounds);
  const hasPricesInRange = history?.average_price_pln_kwh != null;
  const shows15minBeforeQuarterPrices =
    resolution === "15min" && appliedRange && appliedRange.from < QUARTER_HOUR_PRICES_SINCE;

  return (
    <div className="max-w-6xl mx-auto pb-12">
      <h2 className="text-xl font-bold text-gray-900 border-b border-gray-200 pb-4 mb-6 md:mb-8">
        Ceny dynamiczne energii
      </h2>

      {error && (
        <div role="alert" className="mb-6 p-3 text-sm text-red-600 bg-red-50 rounded-lg flex items-start justify-between gap-3">
          <span>
            {error}
            {history ? " Wyświetlane są nadal poprzednie dane." : ""}
          </span>
          <button type="button" onClick={() => setError(null)} className="font-medium hover:underline shrink-0" aria-label="Zamknij komunikat">
            ✕
          </button>
        </div>
      )}

      {!hasAnyPrices ? (
        <div className="bg-white p-8 md:p-10 rounded-lg shadow-sm border border-emerald-100 text-center">
          <h3 className="text-xl font-bold text-gray-800 mb-2">Brak zapisanych cen dynamicznych</h3>
          <p className="text-gray-500 text-sm md:text-base">
            Ceny RCE pobiera automatycznie worker synchronizacji (codziennie o 15:00). Historię można uzupełnić
            komendą <code className="text-xs bg-gray-100 px-1 rounded">backfill</code>.
          </p>
        </div>
      ) : (
        <>
          <div className="mb-6 md:mb-8 bg-white border border-gray-100 rounded-lg shadow-sm px-4 py-4">
            <PriceRangeForm
              key={`${appliedRange.from}:${appliedRange.to}`}
              bounds={bounds}
              appliedRange={appliedRange}
              onApply={applyRange}
              isLoading={isLoading}
            />
            <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs md:text-sm text-gray-500">
              <FiCalendar className="text-emerald-600 shrink-0" />
              <span>
                Wyświetlany okres:{" "}
                <span className="font-semibold text-gray-800">
                  {formatDate(appliedRange.from)} – {formatDate(appliedRange.to)}
                </span>{" "}
                ({formatDaysCount(countDays(appliedRange))})
              </span>
              {isLoading && <span className="text-emerald-600 text-xs">Ładowanie...</span>}
            </div>
          </div>

          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 md:gap-4 mb-6 md:mb-8">
            <StatTile label="Średnia w okresie" value={formatPrice(history.average_price_pln_kwh)} hint="cena brutto w taryfie dynamicznej" />
            <StatTile label="Najniższa" value={formatPrice(history.min_price_pln_kwh)} hint="cena brutto w taryfie dynamicznej" />
            <StatTile label="Najwyższa" value={formatPrice(history.max_price_pln_kwh)} hint="cena brutto w taryfie dynamicznej" />
            <StatTile
              label="Ostatnia aktualizacja"
              value={
                <span className="flex items-center gap-2 text-base md:text-lg">
                  <FiClock className="text-emerald-600 shrink-0" />
                  {formatDateTime(history.last_updated_at)}
                </span>
              }
              hint="ceny z PSE"
            />
          </div>

          <div
            className={`bg-white p-4 md:p-6 rounded-lg shadow-sm border border-gray-100 transition-opacity ${isLoading ? "opacity-60" : ""}`}
            aria-busy={isLoading}
          >
            <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-3 mb-4">
              <div>
                <h3 className="text-base md:text-lg font-bold text-gray-800">Cena w taryfie {history.tariff_name}</h3>
                <p className="text-xs md:text-sm text-gray-500">
                  {describeTariffPrice(history)} · cena brutto za kWh · czas polski
                </p>
              </div>
              <div className="flex bg-gray-100 p-1 rounded-lg w-full sm:w-auto" role="group" aria-label="Rozdzielczość">
                {PRICE_RESOLUTIONS.map((option) => {
                  const allowed = isResolutionAllowed(option.value, appliedRange);
                  return (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => changeResolution(option.value)}
                      disabled={!allowed || isLoading}
                      title={allowed ? undefined : `Dostępne dla zakresu do ${option.maxDays} dni`}
                      className={toggleClass(resolution === option.value)}
                    >
                      {option.label}
                    </button>
                  );
                })}
              </div>
            </div>

            {hasPricesInRange ? (
              <PriceChart history={history} resolution={resolution} />
            ) : (
              <div className="h-[200px] flex items-center justify-center text-center text-gray-400 text-sm md:text-base px-4">
                Brak cen w wybranym okresie. Wybierz inny zakres dat.
              </div>
            )}

            <PriceDataCompleteness days={history.days} showsHourlyPricesNote={shows15minBeforeQuarterPrices} />
          </div>
        </>
      )}
    </div>
  );
}

export default DynamicPricesPage;
