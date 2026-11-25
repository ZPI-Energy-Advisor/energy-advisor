import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { FiSun } from "react-icons/fi";
import apiClient from "../api/client";
import { formatNumber } from "../utils/format";
import { addDays } from "../utils/pv";

function DashboardPvCard() {
  const [tomorrow, setTomorrow] = useState(null);

  useEffect(() => {
    let cancelled = false;
    apiClient.get("/pv/overview")
      .then(({ data }) => {
        const day = data.days.find((summary) => summary.date === addDays(data.today, 1));
        if (!cancelled && day?.available) setTomorrow(day);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  if (!tomorrow) return null;
  return (
    <Link
      to="/pv"
      className="mb-6 flex items-center gap-3 rounded-lg border border-amber-100 bg-amber-50 px-4 py-3 text-sm text-amber-900 transition-colors hover:bg-amber-100"
    >
      <FiSun aria-hidden="true" className="shrink-0 text-xl text-amber-500" />
      <span>
        Jutro z paneli ok. <strong>{formatNumber(tomorrow.total_kwh, 1)} kWh</strong>.
        <span className="ml-1 font-medium underline">Prognoza PV</span>
      </span>
    </Link>
  );
}

export default DashboardPvCard;
