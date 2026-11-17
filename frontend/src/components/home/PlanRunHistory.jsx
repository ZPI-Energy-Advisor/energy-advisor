import { useEffect, useState } from "react";
import apiClient from "../../api/client";
import { getApiErrorMessage } from "../../utils/energyFiles";
import { formatNumber, formatPln, formatSimDate } from "../../utils/home";
import PlanRunCard from "./PlanRunCard";
import { CARD, SECONDARY_BUTTON } from "./styles";

const STATUS_TEXT = {
  running: "w trakcie",
  completed: "wykonany",
  ended: "zakończony przed końcem planu",
  superseded: "przerwany",
};

// Doba RRRR-MM-DD słowami; południe UTC to ten sam dzień w strefie domu.
const dayText = (day) => formatSimDate(`${day}T12:00:00Z`);

const savingText = (run) => {
  if (run.saving == null) return run.status === "running" ? "rachunek po zakończeniu" : "bez rachunku";
  const percent = run.saving_percent == null ? "" : ` (${formatNumber(run.saving_percent, 1)}%)`;
  return `oszczędność ${formatPln(run.saving)}${percent}${run.complete ? "" : ", niepełny"}`;
};

// Raporty z symulacji (ZP-114), zakładka „Raporty” na „Mój dom”: przebiegi planu z rachunkiem z zapisanego
// raportu, a po kliknięciu cały raport. Raporty są w bazie, więc lista nie potrzebuje huba ani zegara.
function PlanRunHistory() {
  const [loaded, setLoaded] = useState(false);
  const [runs, setRuns] = useState([]);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null);
  const [report, setReport] = useState(null);

  useEffect(() => {
    let cancelled = false;
    apiClient
      .get("/home/plan-runs")
      .then(({ data }) => {
        if (cancelled) return;
        setRuns(data);
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(getApiErrorMessage(err, "Nie udało się pobrać raportów z symulacji."));
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const toggle = async (run) => {
    if (open === run.id) {
      setOpen(null);
      return;
    }
    setOpen(run.id);
    setReport(null);
    try {
      setReport((await apiClient.get(`/home/plan-runs/${run.id}`)).data);
    } catch (err) {
      setOpen(null);
      setError(getApiErrorMessage(err, "Nie udało się pobrać raportu przebiegu."));
    }
  };

  if (!loaded) {
    return (
      <p className="text-sm text-gray-500" role="status">
        Ładowanie raportów…
      </p>
    );
  }

  return (
    <section className={CARD} aria-label="Historia przebiegów">
      <h3 className="text-base font-semibold text-gray-900">Raporty z symulacji</h3>
      {!runs.length && !error && (
        <p className="mt-2 text-sm text-gray-600">
          Nie ma jeszcze raportów. Zatwierdź plan na stronie „Plan na jutro” i uruchom go w symulacji.
        </p>
      )}
      {error && (
        <p className="mt-2 text-sm text-red-700" role="alert">
          {error}
        </p>
      )}
      <ul className="mt-2 divide-y divide-gray-100">
        {runs.map((run) => (
          <li key={run.id} className="py-2" aria-label={`Przebieg ${dayText(run.plan_date)}`}>
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 text-sm">
              <div>
                <span className="font-medium text-gray-900">{dayText(run.plan_date)}</span>
                <span className="text-gray-600"> · {STATUS_TEXT[run.status] ?? run.status}</span>
                <p className="text-gray-600">
                  {savingText(run)}
                  {run.deviations ? ` · odchylenia: ${run.deviations}` : ""}
                </p>
              </div>
              <button type="button" className={SECONDARY_BUTTON} onClick={() => toggle(run)} aria-expanded={open === run.id}>
                {open === run.id ? "Ukryj raport" : "Pokaż raport"}
              </button>
            </div>
            {open === run.id && (
              <div className="mt-3">
                {report?.id === run.id ? (
                  <PlanRunCard run={report} />
                ) : (
                  <p className="text-sm text-gray-500" role="status">
                    Ładowanie raportu…
                  </p>
                )}
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

export default PlanRunHistory;
