import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { FiSun } from "react-icons/fi";
import apiClient from "../api/client";
import { formatKwh } from "../utils/format";
import { addDays } from "../utils/pv";

// Brak paneli (404) albo lokalizacji (409) w profilu to nie błąd: karta po prostu się nie pokazuje.
const NO_PV_STATUSES = [404, 409];

function DashboardPvCard() {
  const [tomorrow, setTomorrow] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiClient.get("/pv/overview")
      .then(({ data }) => {
        const day = data.days.find((summary) => summary.date === addDays(data.today, 1));
        if (!cancelled && day?.available) setTomorrow(day);
      })
      .catch((error) => {
        if (!cancelled && !NO_PV_STATUSES.includes(error?.response?.status)) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (failed) {
    return (
      <p className="mb-6 text-sm text-gray-500" role="status">
        Nie udało się pobrać prognozy produkcji z paneli. <Link to="/pv" className="underline">Spróbuj na ekranie Fotowoltaika</Link>.
      </p>
    );
  }
  if (!tomorrow) return null;
  return (
    <Link
      to="/pv"
      className="mb-6 flex items-center gap-3 rounded-lg border border-amber-100 bg-amber-50 px-4 py-3 text-sm text-amber-900 transition-colors hover:bg-amber-100"
    >
      <FiSun aria-hidden="true" className="shrink-0 text-xl text-amber-500" />
      <span>
        Jutro z paneli ok. <strong>{formatKwh(tomorrow.total_kwh)}</strong>.
        <span className="ml-1 font-medium underline">Prognoza PV</span>
      </span>
    </Link>
  );
}

export default DashboardPvCard;
