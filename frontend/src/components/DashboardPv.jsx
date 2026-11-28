import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { FiSun } from "react-icons/fi";
import apiClient from "../api/client";
import { formatKwh } from "../utils/format";
import { addDays } from "../utils/pv";
import { CARD } from "./uiStyles";

const LINK = "font-medium text-emerald-700 underline hover:text-emerald-800";
// Brak paneli (404) albo lokalizacji (409) w profilu to nie błąd: karta po prostu się nie pokazuje.
const NO_PV_STATUSES = [404, 409];

function Figure({ label, value, hint = null }) {
  return (
    <div>
      <p className="text-xs text-gray-500">{label}</p>
      <p className="text-lg font-bold text-gray-900">{value}</p>
      {hint && <p className="text-xs text-gray-500">{hint}</p>}
    </div>
  );
}

// Jutrzejsza prognoza z GET /pv/overview; `failed` tylko przy błędzie serwera, nie przy braku paneli w profilu.
function useTomorrow() {
  const [state, setState] = useState({ tomorrow: null, failed: false });
  useEffect(() => {
    let cancelled = false;
    apiClient
      .get("/pv/overview")
      .then(({ data }) => {
        const day = data.days.find((summary) => summary.date === addDays(data.today, 1));
        if (!cancelled) setState({ tomorrow: day?.available ? day : null, failed: false });
      })
      .catch((error) => {
        if (!cancelled) setState({ tomorrow: null, failed: !NO_PV_STATUSES.includes(error?.response?.status) });
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return state;
}

// Szacunek z pogody dla okresu pliku z GET /pv/period (ZP-122); null bez zakresu, paneli albo pogody.
function usePeriod(from, to) {
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
  return data?.model_kwh != null ? data : null;
}

/**
 * Panele na pulpicie w jednej karcie pod wykresem zużycia: jutrzejsza prognoza (ZP-150) i szacunek z pogody dla
 * okresu pliku obok produkcji z pliku urządzeń albo oddania z licznika (ZP-122). Bez paneli w profilu karty nie ma.
 */
function DashboardPv({ range = null }) {
  const { tomorrow, failed } = useTomorrow();
  const period = usePeriod(range?.from, range?.to);

  if (!tomorrow && !period) {
    return failed ? (
      <p className="mb-6 text-sm text-gray-500" role="status">
        Nie udało się pobrać prognozy produkcji z paneli. <Link to="/pv" className="underline">Spróbuj na ekranie Fotowoltaika</Link>.
      </p>
    ) : null;
  }
  const partial = period && period.model_days < period.days;
  return (
    <section className={`${CARD} mb-8`} aria-label="Panele">
      <h3 className="flex items-center gap-2 text-lg font-bold text-gray-900">
        <FiSun aria-hidden="true" className="text-amber-500" /> Panele
      </h3>
      <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
        {tomorrow && <Figure label="Jutro z paneli (prognoza)" value={`ok. ${formatKwh(tomorrow.total_kwh)}`} />}
        {period && (
          <Figure
            label="W tym okresie: szacunek z pogody"
            value={`ok. ${formatKwh(period.model_kwh)}`}
            hint={partial
              ? `Pogoda dla ${period.model_days} z ${period.days} dni z plików: obie liczby są z tych samych dni.`
              : "Model paneli z zapisanej pogody."}
          />
        )}
        {period?.actual_kwh != null ? (
          <Figure label="W tym okresie: produkcja z pliku urządzeń" value={formatKwh(period.actual_kwh)} />
        ) : period?.export_kwh != null ? (
          <Figure
            label="W tym okresie: oddane do sieci (licznik)"
            value={formatKwh(period.export_kwh)}
            hint="Licznik nie mierzy produkcji, tylko to, co dom oddał."
          />
        ) : null}
      </div>
      {period?.estimated_installation && (
        <p className="mt-3 text-xs text-amber-800">
          Szacunek orientacyjny: panele w profilu są szacunkowe. <Link to="/profile" className={LINK}>Uzupełnij panele w profilu</Link>
        </p>
      )}
      {period?.approximate_location && (
        <p className="mt-1 text-xs text-amber-800">
          Pogoda dla regionu: lokalizacja domu jest przybliżona. <Link to="/profile" className={LINK}>Podaj adres w profilu</Link>
        </p>
      )}
      <Link to="/pv" className={`mt-3 inline-block text-sm ${LINK}`}>Prognoza i produkcja dzień po dniu</Link>
    </section>
  );
}

export default DashboardPv;
