import { Link } from "react-router-dom";
import { FiCloud, FiMoon, FiSun } from "react-icons/fi";
import { formatDegrees } from "../utils/format";
import { cloudLabel, weatherKind } from "../utils/weather";

const ICONS = {
  sun: <FiSun aria-hidden="true" className="text-amber-500" />,
  partly: <FiCloud aria-hidden="true" className="text-amber-500" />,
  cloud: <FiCloud aria-hidden="true" className="text-gray-500" />,
  night: <FiMoon aria-hidden="true" className="text-indigo-400" />,
};

function WeatherBadge({ quarter, label = "Pogoda" }) {
  const kind = weatherKind(quarter);
  if (!kind && quarter?.temperature_c == null) return null;
  const parts = [
    quarter.temperature_c != null ? formatDegrees(quarter.temperature_c) : null,
    kind === "night" ? "noc, bezchmurnie" : cloudLabel(quarter.cloud_cover_pct),
  ].filter(Boolean);
  const text = parts.join(", ");
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full bg-gray-50 px-2.5 py-1 text-xs font-medium text-gray-700"
      role="status"
      aria-label={`${label}: ${text}${quarter.approximate ? ", pogoda dla regionu" : ""}`}
    >
      {ICONS[kind]} {text}
      {/* Przybliżona lokalizacja domu: dopisek widoczny (także na telefonie) z linkiem do poprawy adresu. */}
      {quarter.approximate && (
        <>
          {" · "}
          <Link to="/profile" className="font-normal text-gray-500 underline hover:text-gray-700">
            dla regionu
          </Link>
        </>
      )}
    </span>
  );
}

export default WeatherBadge;
