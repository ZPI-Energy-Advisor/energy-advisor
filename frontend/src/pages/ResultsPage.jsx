import React, { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
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

function ResultsPage() {
  const user = JSON.parse(localStorage.getItem("user")) || {};

  const [tariffsData, setTariffsData] = useState([]);
  const [fullSimulationData, setFullSimulationData] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  const [timeResolution, setTimeResolution] = useState("1h");
  const [metricType, setMetricType] = useState("cost");

  const CHART_COLORS = ["#10b981", "#3b82f6", "#f59e0b", "#ef4444", "#8b5cf6"];

  useEffect(() => {
    const fetchResults = async () => {
      const simId = localStorage.getItem("last_simulation_id");
      if (!simId) {
        setIsLoading(false);
        return;
      }

      try {
        const response = await axios.get(
          `http://localhost:8000/results/${simId}`,
        );
        const results = response.data.results;

        // Tabele taryf
        const tariffsObj = results.tariffs;
        const tariffsArray = Object.keys(tariffsObj).map((key) => ({
          name: key,
          ...tariffsObj[key],
        }));

        setTariffsData(tariffsArray);
        setFullSimulationData(results);
      } catch (err) {
        console.error("Błąd pobierania:", err);
        setError("Nie udało się pobrać wyników analizy.");
      } finally {
        setIsLoading(false);
      }
    };

    fetchResults();
  }, []);

  if (isLoading) {
    return (
      <div className="p-10 text-gray-500">Kalkulowanie opłacalności...</div>
    );
  }

  const cheapestTariff =
    tariffsData.length > 0
      ? tariffsData.reduce((prev, curr) =>
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

  const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
      const prefix = timeResolution === "15m" ? "Godzina:" : "Godzina:";
      const unit = metricType === "price" ? "PLN/kWh" : "PLN";

      return (
        <div className="bg-white p-4 border border-gray-100 shadow-xl rounded-xl min-w-[180px]">
          <p className="text-gray-500 font-medium text-sm mb-3 border-b border-gray-100 pb-2">
            {prefix} {label}
          </p>
          <div className="space-y-2">
            {payload.map((entry, index) => {
              const cleanName = entry.name
                .replace("cost_", "Taryfa ")
                .replace("price_", "Taryfa ");

              return (
                <div
                  key={index}
                  className="flex justify-between items-center gap-4"
                >
                  <span className="text-sm font-medium flex items-center gap-2">
                    <span
                      className="w-2 h-2 rounded-full inline-block"
                      style={{ backgroundColor: entry.color }}
                    ></span>
                    {cleanName}
                  </span>
                  <span className="font-bold text-gray-900">
                    {Number(entry.value).toFixed(2)}{" "}
                    <span className="text-xs text-gray-500 font-normal">
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
  };

  return (
    <div className="max-w-6xl mx-auto pb-12">
      <h2 className="text-xl font-bold text-gray-900 border-b border-gray-200 pb-4 mb-8">
        Analiza opłacalności taryf
      </h2>

      {error && (
        <div className="mb-4 p-4 text-red-600 bg-red-50 rounded-lg">
          {error}
        </div>
      )}

      {tariffsData.length === 0 ? (
        <div className="bg-white p-10 rounded-lg shadow-sm border border-emerald-100 text-center">
          <h3 className="text-xl font-bold text-gray-800 mb-2">
            Brak wyników symulacji
          </h3>
          <p className="text-gray-500 mb-6">
            Wgraj plik CSV z danymi godzinowymi, aby wygenerować tabelę
            porównawczą.
          </p>
          <Link
            to="/upload"
            className="inline-block bg-emerald-600 text-white font-medium px-6 py-3 rounded hover:bg-emerald-700 transition-colors"
          >
            Przejdź do Importu Danych
          </Link>
        </div>
      ) : (
        <>
          <div className="bg-white rounded-lg shadow-sm overflow-hidden border border-gray-200 mb-8">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th
                    scope="col"
                    className="px-6 py-4 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                  >
                    Taryfa
                  </th>
                  <th
                    scope="col"
                    className="px-6 py-4 text-right text-xs font-medium text-gray-500 uppercase tracking-wider"
                  >
                    Miesięczny koszt
                  </th>
                  <th
                    scope="col"
                    className="px-6 py-4 text-right text-xs font-medium text-gray-500 uppercase tracking-wider"
                  >
                    Zużycie
                  </th>
                  <th
                    scope="col"
                    className="px-6 py-4 text-center text-xs font-medium text-gray-500 uppercase tracking-wider"
                  >
                    Status
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {tariffsData.map((tariff) => {
                  const isCheapest = tariff.name === cheapestTariff.name;
                  const isCurrent = tariff.name === user.current_tariff;

                  return (
                    <tr
                      key={tariff.name}
                      className={
                        isCheapest
                          ? "bg-emerald-50"
                          : "hover:bg-gray-50 transition-colors"
                      }
                    >
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="flex items-center gap-3">
                          <span className="font-bold text-gray-900">
                            {tariff.name}
                          </span>
                          {isCurrent && (
                            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800 border border-blue-200">
                              Twoja taryfa
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-right">
                        <div
                          className={`text-lg font-bold ${isCheapest ? "text-emerald-700" : "text-gray-900"}`}
                        >
                          {tariff.estimated_cost_pln}{" "}
                          <span className="text-sm font-normal text-gray-500">
                            PLN
                          </span>
                        </div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-right">
                        <div className="text-gray-900 font-medium">
                          {tariff.total_usage_kwh}{" "}
                          <span className="text-sm text-gray-500">kWh</span>
                        </div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-center">
                        {isCheapest ? (
                          <span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-bold bg-emerald-100 text-emerald-800 border border-emerald-200 shadow-sm">
                            ★ Rekomendowana
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

          {activeChartData.length > 0 && (
            <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-100">
              <div className="flex flex-col lg:flex-row lg:items-center justify-between mb-8 gap-4">
                <h3 className="text-lg font-bold text-gray-900">
                  Porównanie taryf
                </h3>

                <div className="flex flex-col sm:flex-row gap-4">
                  <div className="flex bg-gray-100 p-1 rounded-lg">
                    <button
                      onClick={() => setMetricType("cost")}
                      className={`px-4 py-1.5 text-sm font-medium rounded-md transition-all ${
                        metricType === "cost"
                          ? "bg-white text-emerald-700 shadow-sm"
                          : "text-gray-500 hover:text-gray-700"
                      }`}
                    >
                      Koszty użytkownika
                    </button>
                    <button
                      onClick={() => setMetricType("price")}
                      className={`px-4 py-1.5 text-sm font-medium rounded-md transition-all ${
                        metricType === "price"
                          ? "bg-white text-blue-700 shadow-sm"
                          : "text-gray-500 hover:text-gray-700"
                      }`}
                    >
                      Cenniki bazowe taryf
                    </button>
                  </div>

                  <div className="flex bg-gray-100 p-1 rounded-lg">
                    <button
                      onClick={() => setTimeResolution("15m")}
                      className={`px-3 py-1.5 text-sm font-medium rounded-md transition-all ${
                        timeResolution === "15m"
                          ? "bg-white text-gray-900 shadow-sm"
                          : "text-gray-500 hover:text-gray-700"
                      }`}
                    >
                      15 min
                    </button>
                    <button
                      onClick={() => setTimeResolution("1h")}
                      className={`px-3 py-1.5 text-sm font-medium rounded-md transition-all ${
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

              <div className="h-[450px] w-full">
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
                      tick={{ fontSize: 12, fill: "#64748b" }}
                      dy={10}
                      minTickGap={20}
                    />
                    <YAxis
                      axisLine={false}
                      tickLine={false}
                      tick={{ fontSize: 12, fill: "#64748b" }}
                    />
                    <Tooltip content={<CustomTooltip />} />
                    <Legend
                      verticalAlign="top"
                      height={36}
                      iconType="circle"
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
                          activeDot={{ r: 6, strokeWidth: 0 }}
                          animationDuration={1000}
                        />
                      );
                    })}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default ResultsPage;
