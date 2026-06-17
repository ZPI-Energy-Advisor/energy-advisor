import React, { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import axios from "axios";

function ResultsPage() {
  const user = JSON.parse(localStorage.getItem("user")) || {};

  const [tariffsData, setTariffsData] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

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
        const tariffsObj = response.data.results.tariffs;

        const tariffsArray = Object.keys(tariffsObj).map((key) => ({
          name: key,
          ...tariffsObj[key],
        }));

        setTariffsData(tariffsArray);
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

  return (
    <div className="max-w-6xl mx-auto">
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
        <div className="bg-white rounded-lg shadow-sm overflow-hidden border border-gray-200">
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
      )}
    </div>
  );
}

export default ResultsPage;
