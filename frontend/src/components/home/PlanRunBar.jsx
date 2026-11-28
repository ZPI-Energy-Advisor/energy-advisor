import { useState } from "react";
import { FiAlertTriangle, FiArrowRight, FiCheckCircle, FiLoader, FiRotateCcw, FiSquare } from "react-icons/fi";
import { formatSimTime, planName, savingSummary } from "../../utils/home";
import { SECONDARY_BUTTON } from "./styles";

const LINK = "inline-flex items-center gap-1 font-medium text-emerald-700 hover:text-emerald-900 hover:underline";

// Przebieg planu w karcie zegara (ZP-114): w trakcie dzień planu i „Zakończ”, a po końcu jedna linijka
// z wynikiem, przejściem do raportu w zakładce „Raporty” i ponownym uruchomieniem tego samego planu od północy.
// Godziny planu są przy urządzeniach na liście.
function PlanRunBar({ run, disabled, onEnd, onRestart, onShowReport }) {
  const [isEnding, setIsEnding] = useState(false);
  const [isRestarting, setIsRestarting] = useState(false);
  const name = planName(run);

  const end = async () => {
    setIsEnding(true);
    try {
      await onEnd(run);
    } finally {
      setIsEnding(false);
    }
  };

  const restart = async () => {
    setIsRestarting(true);
    try {
      await onRestart(run);
    } finally {
      setIsRestarting(false);
    }
  };

  const report = (
    <div className="flex flex-wrap items-center gap-3">
      <button type="button" className={LINK} onClick={() => onShowReport(run)}>
        Zobacz raport <FiArrowRight aria-hidden="true" />
      </button>
      <button type="button" className={SECONDARY_BUTTON} disabled={disabled || isRestarting} onClick={restart}>
        {isRestarting ? <FiLoader aria-hidden="true" className="animate-spin" /> : <FiRotateCcw aria-hidden="true" />}
        {isRestarting ? "Uruchamianie..." : "Uruchom ponownie"}
      </button>
    </div>
  );

  let content;
  if (run.status === "running") {
    content = (
      <>
        <p className="text-sm text-gray-700">
          <span className="font-semibold text-gray-900">{name}</span> · w trakcie, do{" "}
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
          <FiAlertTriangle aria-hidden="true" /> {name} przerwany: symulacja zaczęła inną dobę.
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
            <span className="font-semibold text-gray-900">{name} {done}</span>
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
