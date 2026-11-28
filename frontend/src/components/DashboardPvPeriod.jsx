import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { FiSun } from "react-icons/fi";
import apiClient from "../api/client";
import { formatNumber } from "../utils/format";

const kwh = (value) => `${formatNumber(value, 1)} kWh`;
const LINK = "font-medium text-emerald-700 underline hover:text-emerald-800";

function Figure({ label, value, hint = null }) {
  return (
    <div>
      <p className="text-xs text-gray-500">{label}</p>
      <p className="text-lg font-bold text-gray-900">{value}</p>
      {hint && <p className="text-xs text-gray-500">{hint}</p>}
    </div>
  );
}

function DashboardPvPeriod({ range }) {
  const from = range?.from;
  const to = range?.to;
  const [loaded, setLoaded] = useState(null);

  useEffect(() => {
    if (!from || !to) return undefined;
    let cancelled = false;
    apiClient
      .get("/pv/period", { params: { from, to } })
      .then(({ data }) => {
        if (!cancelled) setLoaded({ key: `${from}:${to}`, data });
      })
      .catch(() => {
        if (!cancelled) setLoaded({ key: `${from}:${to}`, data: null });
      });
    return () => {
      cancelled = true;
    };
  }, [from, to]);

  const data = loaded?.key === `${from}:${to}` ? loaded.data : null;
  if (!data || data.model_kwh == null) return null;
  const partial = data.model_days < data.days;
  return (
    <section className="mb-6 rounded-lg border border-amber-100 bg-white p-4 shadow-sm" aria-label="Panele w tym okresie">
      <h3 className="flex items-center gap-2 font-semibold text-gray-900">
        <FiSun aria-hidden="true" className="text-amber-500" /> Panele w tym okresie
      </h3>
      <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Figure
          label="Szacunek z pogody"
          value={`ok. ${kwh(data.model_kwh)}`}
          hint={partial
            ? `Pogoda dla ${data.model_days} z ${data.days} dni z plików: obie liczby są z tych samych dni.`
            : "Model paneli z zapisanej pogody."}
        />
        {data.actual_kwh != null ? (
          <Figure label="Produkcja z pliku urządzeń" value={kwh(data.actual_kwh)} />
        ) : data.export_kwh != null ? (
          <Figure label="Oddane do sieci (licznik)" value={kwh(data.export_kwh)} hint="Licznik nie mierzy produkcji, tylko to, co dom oddał." />
        ) : null}
      </div>
      {data.estimated_installation && (
        <p className="mt-2 text-xs text-amber-800">
          Szacunek orientacyjny: panele w profilu są szacunkowe. <Link to="/profile" className={LINK}>Uzupełnij panele w profilu</Link>
        </p>
      )}
      {data.approximate_location && (
        <p className="mt-1 text-xs text-amber-800">
          Pogoda dla regionu: lokalizacja domu jest przybliżona. <Link to="/profile" className={LINK}>Podaj adres w profilu</Link>
        </p>
      )}
      <Link to="/pv" className={`mt-2 inline-block text-sm ${LINK}`}>Prognoza i produkcja dzień po dniu</Link>
    </section>
  );
}

export default DashboardPvPeriod;
