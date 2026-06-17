import React, { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import axios from "axios";

function Dashboard() {
  const [user, setUser] = useState(
    JSON.parse(localStorage.getItem("user")) || {},
  );

  const [availableTariffs, setAvailableTariffs] = useState([]);

  const [simulationData, setSimulationData] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isUpdating, setIsUpdating] = useState(false);

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

        setSimulationData(specificTariffData);
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

  if (isLoading) {
    return <div className="p-10 text-gray-500">Ładowanie danych z bazy...</div>;
  }

  return (
    <div className="max-w-6xl mx-auto">
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
            to="/import"
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

            <div className="bg-white p-6 rounded-lg shadow-sm border-x border-x-gray-100 border-y-4 border-y-emerald-500 hover:shadow-md transition-shadow">
              <p className="text-sm font-medium text-gray-500 mb-2">
                Aktualna taryfa
              </p>
              <div className="relative flex items-center">
                <select
                  value={user.current_tariff || ""}
                  onChange={handleTariffChange}
                  disabled={isUpdating || availableTariffs.length === 0}
                  className="w-full text-2xl font-bold text-gray-900 bg-transparent border-b-2 border-transparent hover:border-emerald-500 focus:border-emerald-600 focus:outline-none cursor-pointer transition-colors pb-1 appearance-none"
                >
                  {availableTariffs.map((tariff) => (
                    <option key={tariff} value={tariff} className="text-lg">
                      {tariff}
                    </option>
                  ))}
                </select>
                <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-gray-700">
                  <svg
                    className="fill-current h-5 w-5"
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 20 20"
                  >
                    <path d="M9.293 12.95l.707.707L15.657 8l-1.414-1.414L10 10.828 5.757 6.586 4.343 8z" />
                  </svg>
                </div>
              </div>
              {isUpdating && (
                <span className="text-xs text-emerald-500 mt-1 block">
                  Zapisywanie w bazie...
                </span>
              )}
            </div>
          </div>

          <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-100 min-h-[400px] flex items-center justify-center">
            <p className="text-gray-400 font-medium">
              Wkrótce pojawi się tutaj prawdziwy wykres z biblioteki Recharts
              (ZPI-23)
            </p>
          </div>
        </>
      )}
    </div>
  );
}

export default Dashboard;
