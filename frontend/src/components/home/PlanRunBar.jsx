import { useState } from "react";
import { FiAlertTriangle, FiArrowRight, FiCheckCircle, FiLoader, FiSquare } from "react-icons/fi";
import { formatSimTime, savingSummary, shortDay } from "../../utils/home";
import { SECONDARY_BUTTON } from "./styles";

const LINK = "inline-flex items-center gap-1 font-medium text-emerald-700 hover:text-emerald-900 hover:underline";

// Przebieg planu w karcie zegara (ZP-114): w trakcie dzień planu i „Zakończ”, a po końcu jedna linijka
// z wynikiem i przejściem do raportu w zakładce „Raporty”. Godziny planu są przy urządzeniach na liście.
function PlanRunBar({ run, disabled, onEnd, onShowReport }) {
  const [isEnding, setIsEnding] = useState(false);
  const day = shortDay(run.plan_date);

  const end = async () => {
    setIsEnding(true);
    try {
      await onEnd(run);
    } finally {
      setIsEnding(false);
    }
  };

  const report = (
    <button type="button" className={LINK} onClick={() => onShowReport(run)}>
      Zobacz raport <FiArrowRight aria-hidden="true" />
    </button>
  );

  let content;
  if (run.status === "running") {
    content = (
      <>
        <p className="text-sm text-gray-700">
          <span className="font-semibold text-gray-900">Plan na {day}</span> · w trakcie, do{" "}
          {formatSimTime(run.horizon_end)} następnego dnia
        </p>
        <button type="button" className={SECONDARY_BUTTON} disabled={disabled || isEnding} onClick={end}>
          {isEnding ? <FiLoader aria-hidden="true" className="animate-spin" /> : <FiSquare aria-hidden="true" />}
          {isEnding ? "Kończenie..." : "Zakończ"}
        </button>
      </>
    );
  } else if (run.status === "superseded") {
    content = (
      <>
        <p className="flex items-center gap-1.5 text-sm text-amber-800">
          <FiAlertTriangle aria-hidden="true" /> Plan na {day} przerwany: symulacja zaczęła inną dobę.
        </p>
        {report}
      </>
    );
  } else {
    const done = run.status === "completed" ? "wykonany" : "zakończony przed czasem";
    content = (
      <>
        <p className="flex items-center gap-1.5 text-sm text-gray-700">
          <FiCheckCircle aria-hidden="true" className="text-emerald-600" />
          <span>
            <span className="font-semibold text-gray-900">Plan na {day} {done}</span>
            {run.cost && ` · ${savingSummary(run.cost)}`}
          </span>
        </p>
        {report}
      </>
    );
  }

  return (
    <section
      className="mt-4 pt-4 border-t border-gray-100 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2"
      aria-label="Przebieg planu"
    >
      {content}
    </section>
  );
}

export default PlanRunBar;
