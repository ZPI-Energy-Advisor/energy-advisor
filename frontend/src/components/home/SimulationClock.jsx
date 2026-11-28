import { useEffect, useRef, useState } from "react";
import { FiPause, FiPlay } from "react-icons/fi";
import { SPEED_STEPS, formatSimDate, formatSimTime, nearestSpeedStep, realDuration, speedLabel } from "../../utils/home";
import WeatherBadge from "../WeatherBadge";
import { CARD, PRIMARY_BUTTON, SECONDARY_BUTTON } from "./styles";

const SEND_DELAY_MS = 400;

// Suwak tempa: progi od „kwadrans w minutę” do „doba w minutę”. Podpis zmienia się od razu, a tempo idzie do huba
// chwilę po ostatnim ruchu, żeby przeciąganie nie wysyłało serii poleceń. Podgląd trzyma się, dopóki hub ma
// jeszcze stare tempo (stan domu odświeża się z opóźnieniem), a po nieudanym poleceniu wraca do tempa huba.
function SpeedSlider({ clock, disabled, onChange }) {
  const [preview, setPreview] = useState(null); // { index, base }: base to tempo huba w chwili ruchu
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);

  const speed = clock?.speed;
  // Tempo huba w chwili wysyłki (stan domu odświeża się w tle), a nie z chwili ruchu suwakiem.
  const hubSpeed = useRef(speed);
  useEffect(() => {
    hubSpeed.current = speed;
  }, [speed]);
  const pending = preview && preview.base === speed ? preview.index : null;
  const index = pending ?? nearestSpeedStep(speed);
  const label = pending != null ? SPEED_STEPS[pending].label : speed ? speedLabel(speed) : "—";
  const remaining = clock?.running && clock.stop_at && speed
    ? (new Date(clock.stop_at) - new Date(clock.sim_time)) / 1000 / speed
    : null;

  const select = (next) => {
    setPreview({ index: next, base: speed });
    clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      if (SPEED_STEPS[next].value === hubSpeed.current) return;
      if (!(await onChange(SPEED_STEPS[next].value))) setPreview(null);
    }, SEND_DELAY_MS);
  };
  const change = (event) => select(Number(event.target.value));
  // Tempo huba spoza progów (np. ustawione przez API): suwak stoi na najbliższym progu, więc kliknięcie w to
  // samo miejsce nie zmienia wartości i nie wywołuje onChange. Puszczenie suwaka wybiera wtedy ten próg.
  const offStep = speed != null && !SPEED_STEPS.some((step) => step.value === speed);
  const release = () => {
    if (offStep && pending == null) select(index);
  };

  return (
    <div className="w-full md:max-w-md">
      <label htmlFor="sim-speed" className="block text-sm font-medium text-gray-700">
        Tempo: <span className="font-normal text-gray-900">{label}</span>
      </label>
      <input
        id="sim-speed"
        type="range"
        min={0}
        max={SPEED_STEPS.length - 1}
        step={1}
        value={index}
        disabled={disabled}
        onChange={change}
        onPointerUp={release}
        onKeyUp={release}
        aria-valuetext={label}
        className="mt-2 w-full accent-emerald-600 cursor-pointer disabled:cursor-not-allowed"
      />
      <div className="flex justify-between text-xs text-gray-500">
        <span>wolniej</span>
        {remaining != null && remaining > 0 && <span>koniec planu za {realDuration(remaining)}</span>}
        <span>szybciej</span>
      </div>
    </div>
  );
}

// Zegar huba: start, pauza i tempo. Dobę ustawia uruchomienie planu („Uruchom symulację” na stronie planu),
// więc ręcznego wyboru doby tu nie ma: przerwałby przebieg planu. `plan`: pasek przebiegu planu (PlanRunBar),
// który sam mówi, do której trwa plan, więc wtedy nie powtarzamy godziny zatrzymania zegara.
// `startBlocked`: powód, dla którego „Start” nic by nie dał (plan tej symulacji już się skończył), albo null.
function SimulationClock({ clock, disabled, onUpdate, plan = null, startBlocked = null, weather = null }) {
  const [isBusy, setIsBusy] = useState(false);
  const locked = disabled || isBusy || !clock;

  const update = async (change) => {
    setIsBusy(true);
    try {
      return await onUpdate(change);
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <section className={CARD} aria-label="Zegar symulacji">
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-gray-500">Czas symulacji</p>
          {clock ? (
            <>
              <p className="text-3xl font-bold text-gray-900 tabular-nums" data-testid="sim-time">
                {formatSimTime(clock.sim_time)}
              </p>
              <p className="text-sm text-gray-600 first-letter:uppercase">{formatSimDate(clock.sim_time)}</p>
              {weather && (
                <p className="mt-1.5">
                  <WeatherBadge quarter={weather} label="Pogoda w symulacji" />
                </p>
              )}
              {clock.stop_at && !plan && (
                <p className="mt-1 text-xs text-gray-500">
                  Zegar sam stanie o {formatSimTime(clock.stop_at)}, na końcu planu dnia.
                </p>
              )}
            </>
          ) : (
            <p className="text-3xl font-bold text-gray-300">--:--</p>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ${
              clock?.running ? "bg-emerald-100 text-emerald-800" : "bg-gray-100 text-gray-600"
            }`}
          >
            <span className={`h-2 w-2 rounded-full ${clock?.running ? "bg-emerald-500 animate-pulse" : "bg-gray-400"}`} />
            {clock?.running ? "Symulacja trwa" : "Pauza"}
          </span>
          {clock?.running ? (
            <button type="button" className={SECONDARY_BUTTON} disabled={locked} onClick={() => update({ running: false })}>
              <FiPause aria-hidden="true" /> Pauza
            </button>
          ) : (
            <button
              type="button"
              className={PRIMARY_BUTTON}
              disabled={locked || Boolean(startBlocked)}
              title={startBlocked ?? undefined}
              onClick={() => update({ running: true })}
            >
              <FiPlay aria-hidden="true" /> Start
            </button>
          )}
        </div>
      </div>
      {startBlocked && !clock?.running && <p className="mt-2 text-xs text-gray-500">{startBlocked}</p>}

      {plan}

      <div className="mt-4 pt-4 border-t border-gray-100 flex flex-col md:flex-row md:items-end gap-4">
        <SpeedSlider clock={clock} disabled={locked} onChange={(speed) => update({ speed })} />
      </div>
    </section>
  );
}

export default SimulationClock;
