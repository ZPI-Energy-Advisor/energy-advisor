import { useState } from "react";
import { Link } from "react-router-dom";
import SelectedFileBar from "../components/SelectedFileBar";
import NoFileData from "../components/NoFileData";
import DateRangeFilter from "../components/DateRangeFilter";
import NoDataInRange from "../components/NoDataInRange";
import { useEnergyFiles } from "../hooks/useEnergyFiles";
import { useCurrentUser } from "../hooks/useCurrentUser";
import { fillMissingDays, hasDataInRange } from "../utils/energyFiles";
import { comparisonTariffCode } from "../utils/tariffs";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";

function ChartTooltip({ active, payload, label, metric, resolution }) {
  if (active && payload && payload.length) {
    const unit = metric === "kwh" ? "kWh" : "PLN";
    const prefix = resolution === "1d" ? "Dzień:" : "Godzina:";

    return (
      <div className="bg-white p-3 border border-gray-100 shadow-xl rounded-lg min-w-[120px]">
        <p className="text-gray-500 font-medium text-sm mb-1">
          {prefix} {label}
        </p>
        <p
          className={`font-bold text-xl ${metric === "kwh" ? "text-emerald-600" : "text-blue-600"}`}
        >
          {payload[0].value == null ? (
            <span className="text-sm font-medium text-gray-400">Brak danych</span>
          ) : (
            <>
              {Number(payload[0].value).toFixed(2)}{" "}
              <span className="text-sm font-normal">{unit}</span>
            </>
          )}
        </p>
      </div>
    );
  }
  return null;
}

function Dashboard() {
  const { isReady, results, isLoadingData } = useEnergyFiles();
  const { currentTariff, profileTariff, isReady: isUserReady } = useCurrentUser();

  const [chartResolution, setChartResolution] = useState("1h");
  const [chartMetric, setChartMetric] = useState("kwh");

  // Wszystko poniżej wynika z danych aktualnie wybranego pliku, więc zmiana
  // pliku przełącza wykres i statystyki bez dodatkowych zapytań.
  const tariffResults = results?.tariffs ?? {};
  const costTariff = comparisonTariffCode(currentTariff);
  const hasCostTariff = Boolean(tariffResults[costTariff]);
  const simulationData =
    results && Object.keys(tariffResults).length > 0
      ? {
          ...Object.values(tariffResults)[0],
          ...tariffResults[costTariff],
          estimated_cost_pln: tariffResults[costTariff]?.estimated_cost_pln ?? null,
          chart_hourly: results.chart_hourly,
          chart_15min: results.chart_15min,
          chart_daily: results.chart_daily,
        }
      : null;

  const getChartData = () => {
    if (!simulationData) return [];

    let sourceData;
    let labelKey = "hour";

    switch (chartResolution) {
      case "15m":
        sourceData = simulationData.chart_15min || [];
        labelKey = "time";
        break;
      case "1h":
        sourceData = simulationData.chart_hourly || [];
        labelKey = "hour";
        break;
      case "1d":
        // Dni bez pomiarów (np. przerwa między plikami) zostają pustym miejscem na osi.
        sourceData = fillMissingDays(simulationData.chart_daily || []);
        labelKey = "date";
        break;
      default:
        sourceData = simulationData.chart_hourly || [];
    }

    return sourceData.map((item) => ({
      label: item[labelKey],
      value: item.missing
        ? null
        : chartMetric === "kwh"
          ? item.kwh
          : hasCostTariff
            ? item[`cost_${costTariff}`] || 0
            : null,
    }));
  };

  const chartData = getChartData();
  const chartColor = chartMetric === "kwh" ? "#10b981" : "#3b82f6";

  if (!isReady || !isUserReady) {
    return <div className="p-10 text-gray-500">Ładowanie danych z bazy...</div>;
  }

  return (
    <div className="max-w-6xl mx-auto pb-12">
      <h2 className="text-xl font-bold text-gray-900 border-b border-gray-200 pb-4 mb-6 md:mb-8">
        Mój profil zużycia
      </h2>

      {!profileTariff?.exists ? (
        <div className="mb-6 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">
          <Link to="/profile" className="font-semibold underline hover:text-blue-900">
            Uzupełnij profil
          </Link>
          , żebyśmy wiedzieli, jaką masz taryfę. Do tego czasu koszty liczymy dla taryfy{" "}
          {costTariff}.
        </div>
      ) : (
        !currentTariff && (
          <div className="mb-6 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">
            Nie mamy jeszcze cen taryfy {profileTariff.tariff_type} z Twojego profilu, więc koszty
            liczymy dla taryfy {costTariff}.
          </div>
        )
      )}

      <SelectedFileBar />
      {simulationData && <DateRangeFilter />}

      {!simulationData ? (
        <NoFileData
          emptyTitle="Brak danych do analizy"
          emptyDescription="Wgraj swój plik z historią zużycia prądu, aby zobaczyć koszty i wykresy."
        />
      ) : !hasDataInRange(results) ? (
        <NoDataInRange />
      ) : (
        <div
          className={`transition-opacity ${isLoadingData ? "opacity-60" : ""}`}
          aria-busy={isLoadingData}
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4 md:gap-6 mb-8">
            <div className="bg-white p-5 md:p-6 rounded-lg shadow-sm border-x border-x-gray-100 border-y-4 border-y-emerald-500 hover:shadow-md transition-shadow">
              <p className="text-sm font-medium text-gray-500 mb-2">
                Szacowany koszt w okresie
                {!currentTariff && ` (taryfa ${costTariff})`}
              </p>
              <div className="flex items-baseline gap-2">
                <h3 className="text-2xl md:text-3xl font-bold text-gray-900">
                  {simulationData.estimated_cost_pln ?? "—"}
                </h3>
                <span className="text-emerald-600 font-semibold bg-emerald-50 px-2 py-1 rounded text-xs md:text-sm">
                  PLN
                </span>
              </div>
            </div>

            <div className="bg-white p-5 md:p-6 rounded-lg shadow-sm border-x border-x-gray-100 border-y-4 border-y-emerald-500 hover:shadow-md transition-shadow">
              <p className="text-sm font-medium text-gray-500 mb-2">
                Całkowite zużycie
              </p>
              <div className="flex items-baseline gap-2">
                <h3 className="text-2xl md:text-3xl font-bold text-gray-900">
                  {simulationData.total_usage_kwh}
                </h3>
                <span className="text-emerald-600 font-semibold bg-emerald-50 px-2 py-1 rounded text-xs md:text-sm">
                  kWh
                </span>
              </div>
            </div>

            <div className="bg-white p-5 md:p-6 rounded-lg shadow-sm border border-gray-100 hover:shadow-md transition-shadow relative sm:col-span-2 md:col-span-1">
              <div className="absolute top-0 left-0 w-full h-1 bg-emerald-500 rounded-t-lg"></div>

              <p className="text-sm font-medium text-gray-500 mb-3">
                Aktualna taryfa
              </p>

              {/* Taryfę zmienia się wyłącznie w profilu - tu tylko ją pokazujemy. */}
              <p className="text-lg md:text-xl font-bold text-gray-900">
                {profileTariff?.tariff_type
                  ? `Taryfa ${currentTariff?.code ?? profileTariff.tariff_type}`
                  : "Nie znamy jeszcze Twojej taryfy"}
              </p>
              <Link
                to="/profile"
                className="mt-2 inline-block text-sm font-medium text-emerald-600 hover:text-emerald-700 hover:underline"
              >
                {profileTariff?.exists ? "Zmień w profilu" : "Uzupełnij profil"}
              </Link>
            </div>
          </div>

          <div className="bg-white p-4 md:p-6 rounded-lg shadow-sm border border-gray-100 mb-8">
            <div className="flex flex-col lg:flex-row lg:items-center justify-between mb-6 gap-4">
              <h3 className="text-lg font-bold text-gray-900">
                Profil {chartMetric === "kwh" ? "zużycia energii" : "kosztów"}
              </h3>

              <div className="flex flex-col sm:flex-row gap-3">
                <div className="flex bg-gray-100 p-1 rounded-lg w-full sm:w-auto">
                  <button
                    onClick={() => setChartMetric("kwh")}
                    className={`flex-1 sm:flex-none px-3 md:px-4 py-1.5 text-xs md:text-sm font-medium rounded-md transition-all ${
                      chartMetric === "kwh"
                        ? "bg-white text-emerald-700 shadow-sm"
                        : "text-gray-500 hover:text-gray-700"
                    }`}
                  >
                    Zużycie (kWh)
                  </button>
                  <button
                    onClick={() => setChartMetric("pln")}
                    className={`flex-1 sm:flex-none px-3 md:px-4 py-1.5 text-xs md:text-sm font-medium rounded-md transition-all ${
                      chartMetric === "pln"
                        ? "bg-white text-blue-700 shadow-sm"
                        : "text-gray-500 hover:text-gray-700"
                    }`}
                  >
                    Koszty (PLN)
                  </button>
                </div>

                <div className="flex bg-gray-100 p-1 rounded-lg w-full sm:w-auto overflow-x-auto">
                  <button
                    onClick={() => setChartResolution("15m")}
                    className={`flex-1 sm:flex-none px-2 md:px-3 py-1.5 text-xs md:text-sm font-medium rounded-md transition-all whitespace-nowrap ${
                      chartResolution === "15m"
                        ? "bg-white text-gray-900 shadow-sm"
                        : "text-gray-500 hover:text-gray-700"
                    }`}
                  >
                    15 min
                  </button>
                  <button
                    onClick={() => setChartResolution("1h")}
                    className={`flex-1 sm:flex-none px-2 md:px-3 py-1.5 text-xs md:text-sm font-medium rounded-md transition-all whitespace-nowrap ${
                      chartResolution === "1h"
                        ? "bg-white text-gray-900 shadow-sm"
                        : "text-gray-500 hover:text-gray-700"
                    }`}
                  >
                    1 godz
                  </button>
                  <button
                    onClick={() => setChartResolution("1d")}
                    className={`flex-1 sm:flex-none px-2 md:px-3 py-1.5 text-xs md:text-sm font-medium rounded-md transition-all whitespace-nowrap ${
                      chartResolution === "1d"
                        ? "bg-white text-gray-900 shadow-sm"
                        : "text-gray-500 hover:text-gray-700"
                    }`}
                  >
                    Dni
                  </button>
                </div>
              </div>
            </div>

            {chartResolution === "15m" && results?.statistics?.resolution_minutes === 60 && (
              <p className="-mt-2 mb-4 text-xs md:text-sm text-gray-500">
                Plik zawiera odczyty godzinowe, więc wartości 15-minutowe to równy podział każdej godziny.
              </p>
            )}
            {chartResolution === "15m" && results?.statistics?.resolution_minutes === null && (
              <p className="-mt-2 mb-4 text-xs md:text-sm text-gray-500">
                Część plików zawiera odczyty godzinowe – dla ich danych wartości 15-minutowe to równy podział godziny.
              </p>
            )}

            <div className="h-[300px] md:h-[400px] w-full">
              {chartData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={chartData}
                    margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
                  >
                    <CartesianGrid
                      strokeDasharray="3 3"
                      vertical={false}
                      stroke="#f1f5f9"
                    />
                    <XAxis
                      dataKey="label"
                      axisLine={false}
                      tickLine={false}
                      tick={{ fontSize: 10, fill: "#64748b" }}
                      dy={10}
                      minTickGap={20}
                    />
                    <YAxis
                      axisLine={false}
                      tickLine={false}
                      tick={{ fontSize: 10, fill: "#64748b" }}
                    />
                    <Tooltip
                      content={
                        <ChartTooltip
                          metric={chartMetric}
                          resolution={chartResolution}
                        />
                      }
                      cursor={{ fill: "#f8fafc" }}
                    />
                    <Bar
                      dataKey="value"
                      radius={[4, 4, 0, 0]}
                      animationDuration={1000}
                    >
                      {chartData.map((_, index) => (
                        <Cell key={`cell-${index}`} fill={chartColor} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-full flex items-center justify-center text-gray-400 text-center px-4 text-sm md:text-base">
                  Wybierz inny przedział czasu lub wgraj dane.
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default Dashboard;