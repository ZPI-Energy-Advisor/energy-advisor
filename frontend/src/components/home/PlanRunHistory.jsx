import { useCallback, useEffect, useRef, useState } from "react";
import apiClient from "../../api/client";
import { getApiErrorMessage } from "../../utils/energyFiles";
import { savingSummary, weekdayDay } from "../../utils/home";
import PlanRunCard from "./PlanRunCard";
import { CARD, SECONDARY_BUTTON } from "./styles";

const STATUS_TEXT = {
  running: "w trakcie",
  completed: "wykonany",
  ended: "zakończony przed końcem planu",
  superseded: "przerwany",
};

const savingText = (run) => {
  if (run.saving == null) return run.status === "running" ? "rachunek po zakończeniu" : "bez rachunku";
  return savingSummary(run);
};

// Raporty z symulacji (ZP-114), zakładka „Raporty” na „Mój dom”: przebiegi planu z rachunkiem z zapisanego
// raportu, a po kliknięciu cały raport. Raporty są w bazie, więc lista nie potrzebuje huba ani zegara.
// `openId`: raport otwarty od razu, np. po „Zobacz raport” na zakładce „Symulacja”.
function PlanRunHistory({ openId = null }) {
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

  // Numer ostatniego żądania raportu: odpowiedź (albo błąd) wcześniejszego nie zamyka raportu otwartego później.
  const request = useRef(0);
  const show = useCallback(async (runId) => {
    const current = ++request.current;
    setOpen(runId);
    setReport(null);
    setError(null); // Błąd poprzedniego raportu nie zostaje przy udanym otwarciu kolejnego.
    try {
      const { data } = await apiClient.get(`/home/plan-runs/${runId}`);
      if (current === request.current) setReport(data);
    } catch (err) {
      if (current !== request.current) return;
      setOpen(null);
      setError(getApiErrorMessage(err, "Nie udało się pobrać raportu przebiegu."));
    }
  }, []);

  const toggle = (run) => {
    if (open !== run.id) return show(run.id);
    request.current += 1; // Zwinięty raport nie otworzy się po spóźnionej odpowiedzi.
    setOpen(null);
  };

  // Raport z „Zobacz raport” otwieramy po wczytaniu listy i tylko wtedy, gdy przebieg na niej jest: inaczej
  // pobrany raport nie miałby gdzie się pokazać. Bez listy błąd jej pobrania jest już na ekranie.
  const opened = useRef(null);
  useEffect(() => {
    if (!openId || !loaded || opened.current === openId) return;
    opened.current = openId;
    if (runs.some((run) => run.id === openId)) {
      // show ustawia stan po odpowiedzi API, a nie synchronicznie w efekcie.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      show(openId);
    } else if (runs.length) {
      setError("Nie ma tego przebiegu na liście raportów.");
    }
  }, [openId, loaded, runs, show]);

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
          <li key={run.id} className="py-2" aria-label={`Przebieg ${weekdayDay(run.plan_date)}`}>
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 text-sm">
              <div>
                <span className="font-medium text-gray-900">{weekdayDay(run.plan_date)}</span>
                {run.plan_kind === "past_day" && (
                  <span className="ml-2 rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-semibold text-indigo-700">
                    plan idealny
                  </span>
                )}
                <span className="text-gray-600"> · {STATUS_TEXT[run.status] ?? run.status}</span>
                {/* Streszczenie tylko przy zwiniętym raporcie: rozwinięty pokazuje te same liczby pod spodem. */}
                {open !== run.id && (
                  <p className="text-gray-600">
                    {savingText(run)}
                    {run.deviations ? ` · odchylenia: ${run.deviations}` : ""}
                  </p>
                )}
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
