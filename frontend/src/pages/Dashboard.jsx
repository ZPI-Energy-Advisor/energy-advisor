import React, { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import axios from "axios";
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

function Dashboard() {
  const [user, setUser] = useState(
    JSON.parse(localStorage.getItem("user")) || {},
  );

  const [availableTariffs, setAvailableTariffs] = useState([]);
  const [simulationData, setSimulationData] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isUpdating, setIsUpdating] = useState(false);
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);

  const [chartResolution, setChartResolution] = useState("1h");
  const [chartMetric, setChartMetric] = useState("kwh");

  useEffect(() => {
    const fetchTariffs = async () => {
      try {
        const response = await axios.get("http://localhost:8000/tariffs");
        setAvailableTariffs(response.data.tariffs);
      } catch (err) {
        console.error("Błąd pobierania listy taryf:", err);
      }
    };

    const fetchSimulation = async () => {
      const simId = localStorage.getItem("last_simulation_id");

      if (!simId) {
        setIsLoading(false);
        return;
      }

      try {
        const response = await axios.get(
          `http://localhost:8000/results/${simId}`,
        );
        const tariffName = user.current_tariff || "G11";
        const specificTariffData = response.data.results.tariffs[tariffName];

        setSimulationData({
          ...specificTariffData,
          chart_hourly: response.data.results.chart_hourly,
          chart_15min: response.data.results.chart_15min,
          chart_daily: response.data.results.chart_daily,
        });
      } catch (err) {
        console.error("Błąd pobierania symulacji:", err);
        setError("Nie udało się pobrać wyników symulacji.");
      } finally {
        setIsLoading(false);
      }
    };

    fetchTariffs();
    fetchSimulation();
  }, [user.current_tariff]);

  const handleTariffChange = async (e) => {
    const newTariff = e.target.value;
    setIsUpdating(true);

    try {
      await axios.patch("http://localhost:8000/auth/current-tariff", {
        email: user.email,
        new_tariff: newTariff,
      });

      const updatedUser = { ...user, current_tariff: newTariff };
      setUser(updatedUser);
      localStorage.setItem("user", JSON.stringify(updatedUser));
    } catch (err) {
      console.error("Błąd zmiany taryfy:", err);
      alert("Wystąpił błąd podczas zmiany taryfy na serwerze.");
    } finally {
      setIsUpdating(false);
    }
  };

  const getChartData = () => {
    if (!simulationData) return [];

    let sourceData = [];
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
        sourceData = simulationData.chart_daily || [];
        labelKey = "date";
        break;
      default:
        sourceData = simulationData.chart_hourly || [];
    }

    return sourceData.map((item) => ({
      label: item[labelKey],
      value:
        chartMetric === "kwh"
          ? item.kwh
          : item[`cost_${user.current_tariff || "G11"}`] || 0,
    }));
  };

  const chartData = getChartData();
  const chartColor = chartMetric === "kwh" ? "#10b981" : "#3b82f6";

  const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
      const unit = chartMetric === "kwh" ? "kWh" : "PLN";
      const prefix = chartResolution === "1d" ? "Dzień:" : "Godzina:";

      return (
        <div className="bg-white p-3 border border-gray-100 shadow-xl rounded-lg min-w-[120px]">
          <p className="text-gray-500 font-medium text-sm mb-1">
            {prefix} {label}
          </p>
          <p
            className={`font-bold text-xl ${chartMetric === "kwh" ? "text-emerald-600" : "text-blue-600"}`}
          >
            {payload[0].value}{" "}
            <span className="text-sm font-normal">{unit}</span>
          </p>
        </div>
      );
    }
    return null;
  };

  if (isLoading) {
    return <div className="p-10 text-gray-500">Ładowanie danych z bazy...</div>;
  }

  return (
    <div className="max-w-6xl mx-auto pb-12">
      <h2 className="text-xl font-bold text-gray-900 border-b border-gray-200 pb-4 mb-8">
        Mój profil zużycia
      </h2>

      {error && (
        <div className="mb-4 p-4 text-red-600 bg-red-50 rounded-lg">
          {error}
        </div>
      )}

      {!simulationData ? (
        <div className="bg-white p-10 rounded-lg shadow-sm border border-emerald-100 text-center">
          <h3 className="text-xl font-bold text-gray-800 mb-2">
            Brak danych do analizy
          </h3>
          <p className="text-gray-500 mb-6">
            Wgraj swój plik z historią zużycia prądu, aby zobaczyć koszty i
            wykresy.
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
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
            <div className="bg-white p-6 rounded-lg shadow-sm border-x border-x-gray-100 border-y-4 border-y-emerald-500 hover:shadow-md transition-shadow">
              <p className="text-sm font-medium text-gray-500 mb-2">
                Szacowane koszty miesięczne
              </p>
              <div className="flex items-baseline gap-2">
                <h3 className="text-3xl font-bold text-gray-900">
                  {simulationData.estimated_cost_pln}
                </h3>
                <span className="text-emerald-600 font-semibold bg-emerald-50 px-2 py-1 rounded text-sm">
                  PLN
                </span>
              </div>
            </div>

            <div className="bg-white p-6 rounded-lg shadow-sm border-x border-x-gray-100 border-y-4 border-y-emerald-500 hover:shadow-md transition-shadow">
              <p className="text-sm font-medium text-gray-500 mb-2">
                Całkowite zużycie
              </p>
              <div className="flex items-baseline gap-2">
                <h3 className="text-3xl font-bold text-gray-900">
                  {simulationData.total_usage_kwh}
                </h3>
                <span className="text-emerald-600 font-semibold bg-emerald-50 px-2 py-1 rounded text-sm">
                  kWh
                </span>
              </div>
            </div>

            <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-100 hover:shadow-md transition-shadow relative">
              <div className="absolute top-0 left-0 w-full h-1 bg-emerald-500 rounded-t-lg"></div>

              <p className="text-sm font-medium text-gray-500 mb-3">
                Aktualna taryfa
              </p>

              <div className="relative">
                <div
                  onClick={() =>
                    !isUpdating &&
                    availableTariffs.length > 0 &&
                    setIsDropdownOpen(!isDropdownOpen)
                  }
                  className={`w-full bg-gray-50 border ${isDropdownOpen ? "border-emerald-500 ring-2 ring-emerald-500" : "border-gray-200"} text-gray-900 text-xl font-bold py-3 pl-4 pr-10 rounded-xl hover:bg-gray-100 hover:border-emerald-300 transition-all cursor-pointer shadow-sm flex items-center justify-between ${isUpdating || availableTariffs.length === 0 ? "opacity-50 cursor-not-allowed" : ""}`}
                >
                  <span>
                    {user.current_tariff
                      ? `Taryfa ${user.current_tariff}`
                      : "Wybierz taryfę"}
                  </span>
                  <svg
                    className={`h-6 w-6 text-emerald-600 transition-transform duration-200 ${isDropdownOpen ? "rotate-180" : ""}`}
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth="2"
                      d="M19 9l-7 7-7-7"
                    />
                  </svg>
                </div>

                {isDropdownOpen && (
                  <>
                    <div
                      className="fixed inset-0 z-10"
                      onClick={() => setIsDropdownOpen(false)}
                    ></div>

                    <div className="absolute z-20 w-full mt-2 bg-white border border-gray-100 rounded-xl shadow-lg overflow-hidden">
                      {availableTariffs.map((tariff) => (
                        <div
                          key={tariff}
                          onClick={() => {
                            handleTariffChange({ target: { value: tariff } });
                            setIsDropdownOpen(false);
                          }}
                          className={`px-4 py-3 text-lg font-medium cursor-pointer transition-colors ${
                            user.current_tariff === tariff
                              ? "bg-emerald-50 text-emerald-700 border-l-4 border-emerald-500"
                              : "text-gray-700 hover:bg-gray-50 hover:text-emerald-600 border-l-4 border-transparent"
                          }`}
                        >
                          Taryfa {tariff}
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>

              {isUpdating && (
                <div className="mt-3 flex items-center text-sm text-emerald-600 font-medium">
                  <svg
                    className="animate-spin -ml-1 mr-2 h-4 w-4 text-emerald-600"
                    fill="none"
                    viewBox="0 0 24 24"
                  >
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                    ></circle>
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                    ></path>
                  </svg>
                  Aktualizacja w bazie...
                </div>
              )}
            </div>
          </div>

          <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-100 mb-8">
            <div className="flex flex-col lg:flex-row lg:items-center justify-between mb-8 gap-4">
              <h3 className="text-lg font-bold text-gray-900">
                Profil {chartMetric === "kwh" ? "zużycia energii" : "kosztów"}
              </h3>

              <div className="flex flex-col sm:flex-row gap-4">
                <div className="flex bg-gray-100 p-1 rounded-lg">
                  <button
                    onClick={() => setChartMetric("kwh")}
                    className={`px-4 py-1.5 text-sm font-medium rounded-md transition-all ${
                      chartMetric === "kwh"
                        ? "bg-white text-emerald-700 shadow-sm"
                        : "text-gray-500 hover:text-gray-700"
                    }`}
                  >
                    Zużycie (kWh)
                  </button>
                  <button
                    onClick={() => setChartMetric("pln")}
                    className={`px-4 py-1.5 text-sm font-medium rounded-md transition-all ${
                      chartMetric === "pln"
                        ? "bg-white text-blue-700 shadow-sm"
                        : "text-gray-500 hover:text-gray-700"
                    }`}
                  >
                    Koszty (PLN)
                  </button>
                </div>

                <div className="flex bg-gray-100 p-1 rounded-lg">
                  <button
                    onClick={() => setChartResolution("15m")}
                    className={`px-3 py-1.5 text-sm font-medium rounded-md transition-all ${
                      chartResolution === "15m"
                        ? "bg-white text-gray-900 shadow-sm"
                        : "text-gray-500 hover:text-gray-700"
                    }`}
                  >
                    15 min
                  </button>
                  <button
                    onClick={() => setChartResolution("1h")}
                    className={`px-3 py-1.5 text-sm font-medium rounded-md transition-all ${
                      chartResolution === "1h"
                        ? "bg-white text-gray-900 shadow-sm"
                        : "text-gray-500 hover:text-gray-700"
                    }`}
                  >
                    Godzinowo
                  </button>
                  <button
                    onClick={() => setChartResolution("1d")}
                    className={`px-3 py-1.5 text-sm font-medium rounded-md transition-all ${
                      chartResolution === "1d"
                        ? "bg-white text-gray-900 shadow-sm"
                        : "text-gray-500 hover:text-gray-700"
                    }`}
                  >
                    Dziennie
                  </button>
                </div>
              </div>
            </div>

            <div className="h-[400px] w-full">
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
                      tick={{ fontSize: 12, fill: "#64748b" }}
                      dy={10}
                      minTickGap={20}
                    />
                    <YAxis
                      axisLine={false}
                      tickLine={false}
                      tick={{ fontSize: 12, fill: "#64748b" }}
                    />
                    <Tooltip
                      content={<CustomTooltip />}
                      cursor={{ fill: "#f8fafc" }}
                    />
                    <Bar
                      dataKey="value"
                      radius={[4, 4, 0, 0]}
                      animationDuration={1000}
                    >
                      {chartData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={chartColor} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-full flex items-center justify-center text-gray-400">
                  Wybierz inny przedział czasu lub wgraj dane.
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default Dashboard;
