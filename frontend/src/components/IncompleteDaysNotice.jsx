import { FiAlertTriangle } from "react-icons/fi";
import { formatCount, formatDate } from "../utils/energyFiles";

const INCOMPLETE_DAYS = ["niepełny dzień", "niepełne dni", "niepełnych dni"];

// Ostrzeżenie o dniach z brakującymi pomiarami, z rozwijaną listą dat.
function IncompleteDaysNotice({ statistics, className = "" }) {
  const days = statistics?.incomplete_days ?? [];
  if (days.length === 0) return null;

  return (
    <details className={`p-3 rounded-lg bg-amber-50 border border-amber-200 text-sm text-amber-900 ${className}`}>
      <summary className="cursor-pointer font-medium">
        <FiAlertTriangle className="inline mr-2 align-text-bottom" />
        Dane zawierają {formatCount(days.length, INCOMPLETE_DAYS)}
      </summary>
      <p className="mt-2">Brakuje w nich części pomiarów, więc zużycie i koszty tych dni są zaniżone.</p>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
        {days.map((day) => (
          <li key={day}>{formatDate(day)}</li>
        ))}
      </ul>
    </details>
  );
}

export default IncompleteDaysNotice;
