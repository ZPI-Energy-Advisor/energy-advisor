import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';

function Dashboard() {
  const user = JSON.parse(localStorage.getItem('user')) || {};
  
  const [simulationData, setSimulationData] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {

    setIsLoading(false);
  }, []);

  if (isLoading) {
    return <div className="p-10 text-gray-500">Ładowanie danych z bazy...</div>;
  }

  return (
    <div className="max-w-6xl mx-auto">
      <h2 className="text-xl font-bold text-gray-900 border-b border-gray-200 pb-4 mb-8">
        Mój profil zużycia
      </h2>

      {!simulationData ? (
        <div className="bg-white p-10 rounded-lg shadow-sm border border-emerald-100 text-center">
          <h3 className="text-xl font-bold text-gray-800 mb-2">Brak danych do analizy</h3>
          <p className="text-gray-500 mb-6">Wgraj swój plik z historią zużycia prądu, aby zobaczyć koszty i wykresy.</p>
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
            <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-100">
              <p className="text-sm font-medium text-gray-500 mb-1">Koszty (M-c)</p>
              <h3 className="text-3xl font-bold text-gray-900">
                {simulationData.estimated_cost_pln} PLN
              </h3>
            </div>

            <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-100">
              <p className="text-sm font-medium text-gray-500 mb-1">Zużycie</p>
              <h3 className="text-3xl font-bold text-gray-900">
                {simulationData.total_usage_kwh} kWh
              </h3>
            </div>

            <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-100">
              <p className="text-sm font-medium text-gray-500 mb-1">Taryfa</p>
              <h3 className="text-3xl font-bold text-gray-900">
                {user.current_tariff || 'Brak'}
              </h3>
            </div>
          </div>

          <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-100 min-h-[400px] flex items-center justify-center">
            <p className="text-gray-400 font-medium">
              Wkrótce pojawi się tutaj prawdziwy wykres z biblioteki Recharts (ZPI-23)
            </p>
          </div>
        </>
      )}
    </div>
  );
}

export default Dashboard;