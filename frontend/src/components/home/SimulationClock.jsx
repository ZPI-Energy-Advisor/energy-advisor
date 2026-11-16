import { useState } from "react";
import { FiPause, FiPlay } from "react-icons/fi";
import { formatSimDate, formatSimTime, simDay, speedOptions } from "../../utils/home";
import { CARD, PRIMARY_BUTTON, SECONDARY_BUTTON } from "./styles";

// Zegar huba: start, pauza, tempo i wybór doby. Doba zaczyna nową symulację (hub resetuje urządzenia),
// więc hub pozwala ją zmienić tylko przy zatrzymanym zegarze.
function SimulationClock({ clock, disabled, onUpdate }) {
  const [day, setDay] = useState("");
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

  const selectedDay = day || (clock ? simDay(clock.sim_time) : "");
  const startDay = async (event) => {
    event.preventDefault();
    if (await update({ day: selectedDay })) setDay("");
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
            <button type="button" className={PRIMARY_BUTTON} disabled={locked} onClick={() => update({ running: true })}>
              <FiPlay aria-hidden="true" /> Start
            </button>
          )}
        </div>
      </div>

      <div className="mt-4 pt-4 border-t border-gray-100 flex flex-col md:flex-row md:items-end gap-4">
        <label className="text-sm text-gray-700">
          <span className="block font-medium mb-1">Tempo</span>
          <select
            className="w-full md:w-48 border border-gray-300 rounded px-3 py-2 bg-white disabled:bg-gray-50"
            value={clock?.speed ?? ""}
            disabled={locked}
            onChange={(event) => update({ speed: Number(event.target.value) })}
          >
            {speedOptions(clock?.speed).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <form className="flex flex-col sm:flex-row sm:items-end gap-2" onSubmit={startDay}>
          <label className="text-sm text-gray-700">
            <span className="block font-medium mb-1">Doba symulacji</span>
            <input
              type="date"
              required
              className="w-full sm:w-44 border border-gray-300 rounded px-3 py-2 disabled:bg-gray-50"
              value={selectedDay}
              disabled={locked || clock?.running}
              onChange={(event) => setDay(event.target.value)}
            />
          </label>
          <button type="submit" className={SECONDARY_BUTTON} disabled={locked || clock?.running || !selectedDay}>
            Zacznij dobę od północy
          </button>
        </form>
      </div>
      <p className="mt-2 text-xs text-gray-500">
        {clock?.running
          ? "Dobę można zmienić po zatrzymaniu zegara."
          : "Nowa doba zaczyna symulację od nowa: urządzenia wracają do stanu wyłączonego, a zużycie liczy się od zera."}
      </p>
    </section>
  );
}

export default SimulationClock;
