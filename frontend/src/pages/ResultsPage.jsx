import { useState } from "react";
import SelectedFileBar from "../components/SelectedFileBar";
import NoFileData from "../components/NoFileData";
import DateRangeFilter from "../components/DateRangeFilter";
import NoDataInRange from "../components/NoDataInRange";
import { useEnergyFiles } from "../hooks/useEnergyFiles";
import { hasDataInRange, resolveTariffName } from "../utils/energyFiles";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

function ChartTooltip({ active, payload, label, metricType }) {
  if (active && payload && payload.length) {
    const unit = metricType === "price" ? "PLN/kWh" : "PLN";

    return (
      <div className="bg-white p-3 md:p-4 border border-gray-100 shadow-xl rounded-xl min-w-[150px] md:min-w-[180px]">
        <p className="text-gray-500 font-medium text-xs md:text-sm mb-2 md:mb-3 border-b border-gray-100 pb-2">
          Godzina: {label}
        </p>
        <div className="space-y-1.5 md:space-y-2">
          {payload.map((entry, index) => {
            const cleanName = entry.name
              .replace("cost_", "Taryfa ")
              .replace("price_", "Taryfa ");

            return (
              <div
                key={index}
                className="flex justify-between items-center gap-3 md:gap-4"
              >
                <span className="text-xs md:text-sm font-medium flex items-center gap-1.5 md:gap-2">
                  <span
                    className="w-2 h-2 rounded-full inline-block"
                    style={{ backgroundColor: entry.color }}
                  ></span>
                  {cleanName}
                </span>
                <span className="font-bold text-gray-900 text-sm md:text-base">
                  {Number(entry.value).toFixed(2)}{" "}
                  <span className="text-[10px] md:text-xs text-gray-500 font-normal">
                    {unit}
                  </span>
                </span>
              </div>
            );
          })}
        </div>
      </div>
    );
  }
  return null;
}

function ResultsPage() {
  const [user] = useState(() => JSON.parse(localStorage.getItem("user")) || {});
  const { isReady, results, isLoadingData } = useEnergyFiles();

  const [timeResolution, setTimeResolution] = useState("1h");
  const [metricType, setMetricType] = useState("cost");

  const CHART_COLORS = ["#10b981", "#3b82f6", "#f59e0b", "#ef4444", "#8b5cf6"];

  if (!isReady) {
    return (
      <div className="p-10 text-gray-500">Kalkulowanie opłacalności...</div>
    );
  }

  const fullSimulationData = results;
  const tariffsData = Object.entries(results?.tariffs ?? {}).map(
    ([name, tariff]) => ({ name, ...tariff }),
  );
  const currentTariff = resolveTariffName(results?.tariffs, user.current_tariff);

  const pricedTariffs = tariffsData.filter(
    (tariff) => tariff.estimated_cost_pln != null,
  );
  const cheapestTariff =
    pricedTariffs.length > 0
      ? pricedTariffs.reduce((prev, curr) =>
          prev.estimated_cost_pln < curr.estimated_cost_pln ? prev : curr,
        )
      : null;

  let activeChartData = [];
  let timeKey = "hour";

  if (fullSimulationData) {
    if (timeResolution === "15m") {
      activeChartData = fullSimulationData.chart_15min || [];
      timeKey = "time";
    } else {
      activeChartData = fullSimulationData.chart_hourly || [];
    }
  }

  return (
    <div className="max-w-6xl mx-auto pb-12">
      <h2 className="text-xl font-bold text-gray-900 border-b border-gray-200 pb-4 mb-6 md:mb-8">
        Analiza opłacalności taryf
      </h2>

      <SelectedFileBar />
      {tariffsData.length > 0 && <DateRangeFilter />}

      {tariffsData.length === 0 ? (
        <NoFileData
          emptyTitle="Brak wyników symulacji"
          emptyDescription="Wgraj plik CSV z danymi godzinowymi, aby wygenerować tabelę porównawczą."
        />
      ) : !hasDataInRange(results) ? (
        <NoDataInRange />
      ) : (
        <div
          className={`transition-opacity ${isLoadingData ? "opacity-60" : ""}`}
          aria-busy={isLoadingData}
        >
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 mb-8 w-full overflow-hidden">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th
                      scope="col"
                      className="px-4 md:px-6 py-3 md:py-4 text-left text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap"
                    >
                      Taryfa
                    </th>
                    <th
                      scope="col"
                      className="px-4 md:px-6 py-3 md:py-4 text-right text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap"
                    >
                      Koszt w okresie
                    </th>
                    <th
                      scope="col"
                      className="px-4 md:px-6 py-3 md:py-4 text-right text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap"
                    >
                      Zużycie
                    </th>
                    <th
                      scope="col"
                      className="px-4 md:px-6 py-3 md:py-4 text-center text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap"
                    >
                      Status
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {tariffsData.map((tariff) => {
                    const isCheapest = tariff.name === cheapestTariff.name;
                    const isCurrent = tariff.name === currentTariff;

                    return (
                      <tr
                        key={tariff.name}
                        className={
                          isCheapest
                            ? "bg-emerald-50"
                            : "hover:bg-gray-50 transition-colors"
                        }
                      >
                        <td className="px-4 md:px-6 py-4 whitespace-nowrap">
                          <div className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-3">
                            <span className="font-bold text-gray-900 text-sm md:text-base">
                              {tariff.name}
                            </span>
                            {isCurrent && (
                              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] md:text-xs font-medium bg-blue-100 text-blue-800 border border-blue-200 w-max">
                                Twoja taryfa
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="px-4 md:px-6 py-4 whitespace-nowrap text-right">
                          <div
                            className={`text-base md:text-lg font-bold ${isCheapest ? "text-emerald-700" : "text-gray-900"}`}
                          >
                            {tariff.estimated_cost_pln != null ? (
                              <>
                                {Number(tariff.estimated_cost_pln).toFixed(2)}{" "}
                                <span className="text-xs md:text-sm font-normal text-gray-500">
                                  PLN
                                </span>
                              </>
                            ) : (
                              <span className="text-sm font-normal text-gray-500">
                                brak danych
                              </span>
                            )}
                          </div>
                          {tariff.price_coverage != null &&
                            tariff.price_coverage < 1 && (
                              <div className="text-[10px] md:text-xs text-amber-600">
                                ceny dla {Math.round(tariff.price_coverage * 100)}% okresu
                              </div>
                            )}
                        </td>
                        <td className="px-4 md:px-6 py-4 whitespace-nowrap text-right">
                          <div className="text-gray-900 font-medium text-sm md:text-base">
                            {Number(tariff.total_usage_kwh).toFixed(2)}{" "}
                            <span className="text-xs md:text-sm text-gray-500">kWh</span>
                          </div>
                        </td>
                        <td className="px-4 md:px-6 py-4 whitespace-nowrap text-center">
                          {isCheapest ? (
                            <span className="inline-flex items-center px-2 md:px-3 py-1 rounded-full text-[10px] md:text-sm font-bold bg-emerald-100 text-emerald-800 border border-emerald-200 shadow-sm w-max">
                              ★ Najlepsza
                            </span>
                          ) : (
                            <span className="text-gray-400">-</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {activeChartData.length > 0 && (
            <div className="bg-white p-4 md:p-6 rounded-lg shadow-sm border border-gray-100">
              <div className="flex flex-col xl:flex-row xl:items-center justify-between mb-6 gap-4">
                <h3 className="text-lg font-bold text-gray-900">
                  Porównanie taryf
                </h3>

                <div className="flex flex-col sm:flex-row gap-3">
                  <div className="flex bg-gray-100 p-1 rounded-lg w-full sm:w-auto">
                    <button
                      onClick={() => setMetricType("cost")}
                      className={`flex-1 sm:flex-none px-3 md:px-4 py-1.5 text-xs md:text-sm font-medium rounded-md transition-all whitespace-nowrap ${
                        metricType === "cost"
                          ? "bg-white text-emerald-700 shadow-sm"
                          : "text-gray-500 hover:text-gray-700"
                      }`}
                    >
                      Koszty całkowite
                    </button>
                    <button
                      onClick={() => setMetricType("price")}
                      className={`flex-1 sm:flex-none px-3 md:px-4 py-1.5 text-xs md:text-sm font-medium rounded-md transition-all whitespace-nowrap ${
                        metricType === "price"
                          ? "bg-white text-blue-700 shadow-sm"
                          : "text-gray-500 hover:text-gray-700"
                      }`}
                    >
                      Cenniki bazowe
                    </button>
                  </div>

                  <div className="flex bg-gray-100 p-1 rounded-lg w-full sm:w-auto">
                    <button
                      onClick={() => setTimeResolution("15m")}
                      className={`flex-1 sm:flex-none px-3 md:px-4 py-1.5 text-xs md:text-sm font-medium rounded-md transition-all whitespace-nowrap ${
                        timeResolution === "15m"
                          ? "bg-white text-gray-900 shadow-sm"
                          : "text-gray-500 hover:text-gray-700"
                      }`}
                    >
                      15 min
                    </button>
                    <button
                      onClick={() => setTimeResolution("1h")}
                      className={`flex-1 sm:flex-none px-3 md:px-4 py-1.5 text-xs md:text-sm font-medium rounded-md transition-all whitespace-nowrap ${
                        timeResolution === "1h"
                          ? "bg-white text-gray-900 shadow-sm"
                          : "text-gray-500 hover:text-gray-700"
                      }`}
                    >
                      Godzinowo
                    </button>
                  </div>
                </div>
              </div>

              <div className="h-[300px] md:h-[450px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart
                    data={activeChartData}
                    margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
                  >
                    <CartesianGrid
                      strokeDasharray="3 3"
                      vertical={false}
                      stroke="#f1f5f9"
                    />
                    <XAxis
                      dataKey={timeKey}
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
                    <Tooltip content={<ChartTooltip metricType={metricType} />} />
                    <Legend
                      verticalAlign="top"
                      height={36}
                      iconType="circle"
                      wrapperStyle={{ fontSize: '12px' }}
                      formatter={(value) => (
                        <span className="text-gray-700 font-medium">
                          {value
                            .replace("cost_", "Taryfa ")
                            .replace("price_", "Taryfa ")}
                        </span>
                      )}
                    />

                    {tariffsData.map((tariff, index) => {
                      const dataKeyName = `${metricType}_${tariff.name}`;
                      const lineType =
                        metricType === "price" ? "stepAfter" : "monotone";

                      return (
                        <Line
                          key={tariff.name}
                          type={lineType}
                          dataKey={dataKeyName}
                          name={dataKeyName}
                          stroke={CHART_COLORS[index % CHART_COLORS.length]}
                          strokeWidth={3}
                          dot={false}
                          activeDot={{ r: 5, strokeWidth: 0 }}
                          animationDuration={1000}
                        />
                      );
                    })}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default ResultsPage;