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
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);

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
