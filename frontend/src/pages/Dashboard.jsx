import { useState } from "react";
import DataContextBar from "../components/DataContextBar";
import DashboardPvCard from "../components/DashboardPvCard";
import DashboardPvPeriod from "../components/DashboardPvPeriod";
import DashboardTariffCard from "../components/DashboardTariffCard";
import { PageSkeleton } from "../components/Skeleton";
import DeviceUsagePanel from "../components/DeviceUsagePanel";
import SegmentedControl from "../components/SegmentedControl";
import NoFileData from "../components/NoFileData";
import NoDataInRange from "../components/NoDataInRange";
import ChartTooltip from "../components/ChartTooltip";
import IncompleteDaysNotice from "../components/IncompleteDaysNotice";
import { useEnergyFiles } from "../hooks/useEnergyFiles";
import ProfileTariffNotice from "../components/ProfileTariffNotice";
import { useCurrentUser } from "../hooks/useCurrentUser";
import { fillMissingDays, formatDate, hasDataInRange } from "../utils/energyFiles";
import { describeBreakdown, formatPln } from "../utils/tariffs";
import { axisUnitLabel, formatAxis, formatNumber } from "../utils/format";
import { UNAVAILABLE_NO_COMMON_DAYS, UNAVAILABLE_NO_DEVICE_FILES, deviceUsageSource } from "../utils/deviceUsage";
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

const INCOMPLETE_DAY_COLOR = "#f59e0b";

function TooltipValue({ point, metric }) {
  const unit = metric === "kwh" ? "kWh" : "zł";

  return (
    <>
      <p
        className={`font-bold text-xl ${metric === "kwh" ? "text-emerald-600" : "text-blue-600"}`}
      >
        {point.value == null ? (
          <span className="text-sm font-medium text-gray-400">Brak danych</span>
        ) : (
          <>
            {formatNumber(point.value)}{" "}
            <span className="text-sm font-normal">{unit}</span>
          </>
        )}
      </p>
      {point.payload.incomplete && (
        <p className="mt-1 text-xs font-medium text-amber-700">
          Niepełny dzień – brakuje części pomiarów
        </p>
      )}
    </>
  );
}

const METRIC_OPTIONS = [
  { value: "kwh", label: "Zużycie (kWh)", activeClassName: "text-emerald-700" },
  { value: "pln", label: "Koszty (zł)", activeClassName: "text-blue-700" },
];
const RESOLUTION_OPTIONS = [
  { value: "15m", label: "15 min" },
  { value: "1h", label: "1 godz" },
  { value: "1d", label: "Dni" },
];
// Podpowiedź po najechaniu na nieaktywny przycisk „Urządzenia”.
const DEVICES_UNAVAILABLE_HINT = {
  [UNAVAILABLE_NO_DEVICE_FILES]: "Podział na urządzenia wymaga pliku urządzeń.",
  [UNAVAILABLE_NO_COMMON_DAYS]: "Pliki urządzeń nie obejmują dni z tego pliku licznika.",
};

function Dashboard() {
  const { isReady, results, isLoadingData, selectedFile, dateRange, devicesAggregate } = useEnergyFiles();
  const { currentTariff, profileTariff, isReady: isUserReady, loadError: userLoadError } = useCurrentUser();

  const [chartResolution, setChartResolution] = useState("1h");
  const [chartMetric, setChartMetric] = useState("kwh");
  const [view, setView] = useState("total");
  const devicesSource = deviceUsageSource({ selectedFile, dateRange, devicesAggregate });
  const devicesUnavailable = devicesSource?.unavailable ?? null;
  const showDevices = view === "devices" && devicesSource && !devicesUnavailable;

  const toolbar = (
    <div className="flex flex-col sm:flex-row gap-3">
      <SegmentedControl label="Miara" options={METRIC_OPTIONS} value={chartMetric} onChange={setChartMetric} />
      <SegmentedControl label="Rozdzielczość" options={RESOLUTION_OPTIONS} value={chartResolution} onChange={setChartResolution} />
    </div>
  );

  // Wszystko poniżej wynika z danych aktualnie wybranego pliku, więc zmiana
  // pliku przełącza wykres i statystyki bez dodatkowych zapytań.
  // Koszty liczy backend przy odczycie: taryfa z profilu (albo zastępcza z uwagą), a bez profilu PGE G11.
  const pricing = results?.pricing ?? null;
  const costTariff = pricing?.tariff_key ?? null;
  const costTariffData = costTariff ? results?.tariffs?.[costTariff] ?? null : null;
  const hasCostTariff = costTariffData?.estimated_cost_pln != null;
  const simulationData = results
    ? {
        total_usage_kwh: results.total_usage_kwh,
        estimated_cost_pln: costTariffData?.estimated_cost_pln ?? null,
        energy_cost_pln: costTariffData?.energy_cost_pln ?? null,
        monthly_fees_pln: costTariffData?.monthly_fees_pln ?? null,
        cost_breakdown: costTariffData?.cost_breakdown ?? null,
        chart_hourly: results.chart_hourly,
        chart_15min: results.chart_15min,
        chart_daily: results.chart_daily,
      }
    : null;
  const tariffName = pricing?.tariff_label ?? costTariff;

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

    const incompleteDays = new Set(results?.statistics?.incomplete_days ?? []);

    return sourceData.map((item) => ({
      label: item[labelKey],
      incomplete: chartResolution === "1d" && incompleteDays.has(item.date),
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
    return <PageSkeleton label="Ładowanie danych..." />;
  }

  return (
    <div className="max-w-6xl mx-auto pb-12">
      <DataContextBar title="Mój profil zużycia" showRange={Boolean(simulationData)} />

      <ProfileTariffNotice
        missingProfile=", żebyśmy wiedzieli, jaką masz taryfę. Do tego czasu koszty liczymy dla taryfy G11 operatora PGE."
        pricingNote={pricing?.note}
      />

      <DashboardPvCard />

      {!simulationData ? (
        <NoFileData
          emptyTitle="Brak danych do analizy"
          emptyDescription="Wgraj swój plik z historią zużycia prądu, aby zobaczyć koszty i wykresy."
        />
      ) : !hasDataInRange(results) ? (
        <NoDataInRange />
      ) : (
        <>
          <IncompleteDaysNotice statistics={results?.statistics} className="mb-6" />
          <DashboardPvPeriod range={dateRange} />

          <div className="mb-6 flex flex-col sm:flex-row sm:items-center gap-3">
            <SegmentedControl
              label="Widok"
              options={[
                { value: "total", label: "Łącznie" },
                {
                  value: "devices",
                  label: "Urządzenia",
                  disabled: Boolean(devicesUnavailable),
                  title: DEVICES_UNAVAILABLE_HINT[devicesUnavailable],
                },
              ]}
              value={showDevices ? "devices" : "total"}
              onChange={setView}
            />
            {showDevices && devicesSource.meter && (
              <p className="text-xs md:text-sm text-gray-500">
                {devicesSource.deviceFiles?.length
                  ? `Urządzenia z ${devicesSource.deviceFiles.length === 1 ? "pliku" : "plików"} ${devicesSource.deviceFiles.join(", ")}`
                  : "Urządzenia z plików urządzeń"}
                , reszta domu z licznika, w dniach wspólnych ({formatDate(devicesSource.range.from)} – {formatDate(devicesSource.range.to)}).
              </p>
            )}
          </div>

          {showDevices ? (
            <DeviceUsagePanel
              source={devicesSource}
              metric={chartMetric}
              resolution={chartResolution}
              toolbar={toolbar}
              gridImport={{
                kwh: simulationData.total_usage_kwh,
                cost: simulationData.energy_cost_pln,
                tariff: costTariff,
              }}
            />
          ) : (
            <div
              className={`transition-opacity ${isLoadingData ? "opacity-60" : ""}`}
              aria-busy={isLoadingData}
            >
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4 md:gap-6 mb-8">
                <div className="bg-white p-5 md:p-6 rounded-lg shadow-sm border-x border-x-gray-100 border-y-4 border-y-emerald-500 hover:shadow-md transition-shadow">
                  <p className="text-sm font-medium text-gray-500 mb-2">
                    Szacowany koszt w okresie
                    {tariffName && ` (taryfa ${tariffName}${pricing?.from_profile ? "" : `, ${pricing?.operator}`})`}
                  </p>
                  <div className="flex items-baseline gap-2">
                    <h3 className="text-2xl md:text-3xl font-bold text-gray-900">
                      {formatNumber(simulationData.estimated_cost_pln)}
                    </h3>
                    <span className="text-emerald-600 font-semibold bg-emerald-50 px-2 py-1 rounded text-xs md:text-sm">
                      zł
                    </span>
                  </div>
                  {hasCostTariff && (
                    <p className="mt-2 text-xs text-gray-500" title={describeBreakdown(simulationData.cost_breakdown, formatPln) ?? undefined}>
                      Za kWh {formatPln(simulationData.energy_cost_pln)} · opłaty miesięczne{" "}
                      {formatPln(simulationData.monthly_fees_pln)}
                    </p>
                  )}
                </div>

                <div className="bg-white p-5 md:p-6 rounded-lg shadow-sm border-x border-x-gray-100 border-y-4 border-y-emerald-500 hover:shadow-md transition-shadow">
                  <p className="text-sm font-medium text-gray-500 mb-2">
                    Całkowite zużycie
                  </p>
                  <div className="flex items-baseline gap-2">
                    <h3 className="text-2xl md:text-3xl font-bold text-gray-900">
                      {formatNumber(simulationData.total_usage_kwh)}
                    </h3>
                    <span className="text-emerald-600 font-semibold bg-emerald-50 px-2 py-1 rounded text-xs md:text-sm">
                      kWh
                    </span>
                  </div>
                </div>

                <DashboardTariffCard
                  enabled={hasDataInRange(results)}
                  profileTariff={profileTariff}
                  currentTariff={currentTariff}
                  loadError={userLoadError}
                />
              </div>

              <div className="bg-white p-4 md:p-6 rounded-lg shadow-sm border border-gray-100 mb-8">
                <div className="flex flex-col lg:flex-row lg:items-center justify-between mb-6 gap-4">
                  <h3 className="text-lg font-bold text-gray-900">
                    Profil {chartMetric === "kwh" ? "zużycia energii" : "kosztów"}
                  </h3>

                  {toolbar}
                </div>

                {chartMetric === "pln" && hasCostTariff && (
                  <p className="-mt-2 mb-4 text-xs md:text-sm text-gray-500">
                    Koszt energii, dystrybucji i opłat za kWh z VAT w taryfie {tariffName}, bez opłat miesięcznych.
                  </p>
                )}
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
                {chartData.some((point) => point.incomplete) && (
                  <p className="-mt-2 mb-4 flex items-center gap-2 text-xs md:text-sm text-gray-500">
                    <span
                      className="w-2.5 h-2.5 rounded-sm shrink-0"
                      style={{ backgroundColor: INCOMPLETE_DAY_COLOR }}
                    />
                    Niepełne dni
                  </p>
                )}

                <div className="h-[300px] md:h-[400px] w-full">
                  {chartData.length > 0 ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart
                        data={chartData}
                        margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
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
                          tickFormatter={formatAxis}
                          width={48}
                          label={axisUnitLabel(chartMetric === "kwh" ? "kWh" : "zł")}
                        />
                        <Tooltip
                          content={
                            <ChartTooltip
                              resolution={chartResolution}
                              render={([point]) => (
                                <TooltipValue point={point} metric={chartMetric} />
                              )}
                            />
                          }
                          cursor={{ fill: "#f8fafc" }}
                        />
                        <Bar
                          dataKey="value"
                          radius={[4, 4, 0, 0]}
                          animationDuration={1000}
                        >
                          {chartData.map((point, index) => (
                            <Cell
                              key={`cell-${index}`}
                              fill={point.incomplete ? INCOMPLETE_DAY_COLOR : chartColor}
                            />
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
        </>
      )}
    </div>
  );
}

export default Dashboard;