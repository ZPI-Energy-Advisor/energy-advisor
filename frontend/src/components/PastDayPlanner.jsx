import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { FiLoader } from "react-icons/fi";
import apiClient from "../api/client";
import DayPlanView from "./DayPlanView";
import { getApiErrorMessage } from "../utils/energyFiles";
import { inPeriods, periodsText } from "../utils/dayPlan";

const CARD = "bg-white border border-gray-200 rounded-lg p-4 md:p-5 shadow-sm";
const PRIMARY =
  "w-full sm:w-auto inline-flex items-center justify-center gap-1.5 rounded-md bg-emerald-600 px-5 py-3 font-semibold " +
  "text-white hover:bg-emerald-700 disabled:opacity-50";

const errorText = (err, fallback) => {
  const detail = err?.response?.data?.detail;
  return detail?.message ?? getApiErrorMessage(err, fallback);
};

// Plan idealny dnia z przeszłości (ZP-152): wybór doby z kalendarza, plan z pogodą z archiwum i uruchomienie
// w symulacji. Plan na jutro zostaje bez zmian, bo plan dnia z przeszłości ma swój widok.
function PastDayPlanner({ flatTariff, onEditSettings, canRun, initialDay = null }) {
  const [range, setRange] = useState(null);
  const [rangeError, setRangeError] = useState(null);
  const [day, setDay] = useState(initialDay ?? "");
  const [loaded, setLoaded] = useState(null);
  const [error, setError] = useState(null);
  const [isCreating, setIsCreating] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [approveError, setApproveError] = useState(null);
  const [isStartingRun, setIsStartingRun] = useState(false);
  const [runError, setRunError] = useState(null);
  const navigate = useNavigate();
  const request = useRef(0);

  useEffect(() => {
    apiClient
      .get("/planning/past-days")
      .then(({ data }) => {
        setRange(data);
        const lastFileDay = data.file_periods.at(-1)?.last_day;
        const fallback = lastFileDay && (!data.first_day || lastFileDay >= data.first_day) ? lastFileDay : data.last_day;
        setDay((current) => current || fallback);
      })
      .catch((err) => setRangeError(getApiErrorMessage(err, "Nie udało się pobrać dni z cenami.")));
  }, []);

  useEffect(() => {
    if (!day) return undefined;
    let cancelled = false;
    const current = ++request.current;
    apiClient
      .get("/planning/plans", { params: { date: day } })
      .then(({ data }) => {
        if (!cancelled && current === request.current) setLoaded({ day, plan: data });
      })
      .catch(() => {
        if (!cancelled && current === request.current) setLoaded({ day, plan: null });
      });
    return () => {
      cancelled = true;
    };
  }, [day]);

  const plan = loaded?.day === day ? loaded.plan : null;
  const inRange = Boolean(range?.first_day) && day >= range.first_day && day <= range.last_day;
  const fileDay = range ? inPeriods(day, range.file_periods) : false;

  const choose = (value) => {
    setDay(value);
    setError(null);
    setApproveError(null);
    setRunError(null);
  };

  const create = async () => {
    setIsCreating(true);
    setError(null);
    try {
      const { data } = await apiClient.post("/planning/plans", { plan_date: day });
      request.current += 1;
      setLoaded({ day, plan: data });
    } catch (err) {
      setError(errorText(err, "Nie udało się ułożyć planu idealnego."));
    } finally {
      setIsCreating(false);
    }
  };

  const approve = async () => {
    setIsApproving(true);
    setApproveError(null);
    try {
      const { data } = await apiClient.post(`/planning/plans/${plan.id}/approve`);
      setLoaded({ day, plan: data });
    } catch (err) {
      setApproveError(getApiErrorMessage(err, "Nie udało się zatwierdzić planu."));
    } finally {
      setIsApproving(false);
    }
  };

  const startRun = async () => {
    setIsStartingRun(true);
    setRunError(null);
    try {
      await apiClient.post("/home/plan-runs", { plan_id: plan.id });
      navigate("/home");
    } catch (err) {
      setRunError(getApiErrorMessage(err, "Nie udało się uruchomić planu w symulacji."));
      setIsStartingRun(false);
    }
  };

  if (rangeError) {
    return (
      <p className="p-3 rounded bg-red-50 text-sm text-red-700" role="alert">
        {rangeError} <Link to="/profile" className="font-semibold underline">Przejdź do profilu</Link>
      </p>
    );
  }
  if (!range) return <p className="text-sm text-gray-500" role="status">Ładowanie dni…</p>;

  return (
    <div className="space-y-4">
      <section className={CARD} aria-label="Wybór dnia">
        <p className="text-sm text-gray-600">
          Plan idealny układamy z pełną wiedzą o dobie: pogoda i prąd z paneli są z archiwum, czyli takie, jakie
          naprawdę były. Pokazuje największą oszczędność, jaką plan mógł dać tego dnia.
        </p>
        {range.first_day ? (
          <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-end">
            <label className="block text-sm font-medium text-gray-700">
              Dzień
              <input
                type="date"
                className="mt-1 block w-full sm:w-48 rounded-md border border-gray-300 px-3 py-2 text-gray-900"
                min={range.first_day}
                max={range.last_day}
                value={day}
                onChange={(event) => choose(event.target.value)}
              />
            </label>
            <button type="button" className={PRIMARY} onClick={create} disabled={!inRange || isCreating}>
              {isCreating && <FiLoader aria-hidden="true" className="animate-spin" />}
              {isCreating ? "Układanie planu..." : plan ? "Ułóż plan idealny ponownie" : "Ułóż plan idealny"}
            </button>
          </div>
        ) : (
          <p className="mt-3 text-sm text-amber-800" role="alert">
            Nie ma cen Twojej taryfy dla żadnego dnia z przeszłości, więc planu idealnego nie ułożymy.
          </p>
        )}
        {day && !inRange && range.first_day && (
          <p className="mt-2 text-sm text-amber-800" role="alert">
            Wybierz dzień od {range.first_day.split("-").reverse().join(".")} do{" "}
            {range.last_day.split("-").reverse().join(".")}: tylko dla nich mamy ceny Twojej taryfy.
          </p>
        )}
        {inRange && (
          <p className="mt-2 text-sm text-gray-600" role="status">
            {fileDay
              ? "Ten dzień jest w plikach urządzeń: „bez planu” to to, co dom naprawdę wtedy robił."
              : "Tego dnia nie ma w plikach urządzeń: urządzenia i godziny bez planu bierzemy z ustawień, jak w planie na jutro."}
          </p>
        )}
        {range.file_periods.length > 0 && (
          <p className="mt-1 text-xs text-gray-500">Dni w plikach urządzeń: {periodsText(range.file_periods)}.</p>
        )}
        {error && <p className="mt-2 text-sm text-red-600" role="alert">{error}</p>}
      </section>

      {plan && (
        <DayPlanView
          plan={plan}
          flatTariff={flatTariff}
          onApprove={approve}
          onEdit={onEditSettings}
          onReplan={create}
          isApproving={isApproving}
          isReplanning={isCreating}
          approveError={approveError}
          onRun={canRun ? startRun : null}
          isStartingRun={isStartingRun}
          runError={runError}
        />
      )}
    </div>
  );
}

export default PastDayPlanner;
