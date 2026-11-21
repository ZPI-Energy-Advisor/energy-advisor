import { formatSimDate, formatSimTime } from "../../utils/home";
import { simTimeline } from "../../utils/houseView";

const PRICE_COLORS = { cheap: "bg-emerald-300", mid: "bg-amber-200", expensive: "bg-rose-300" };
const percent = (fraction) => `${(fraction * 100).toFixed(3)}%`;

// Pasek czasu nad przekrojem domu: godzina symulacji widoczna razem z domem, bez przewijania do zegara.
// Przy przebiegu planu pasek obejmuje zakres przebiegu, ma ceny kwadransów (tanio, średnio, drogo) i znaczniki
// startów pozycji planu; bez planu pokazuje dobę zegara.
function HouseTimeline({ run, simTime }) {
  const line = simTimeline(run, simTime);
  if (!line) return null;

  return (
    <section aria-label="Czas symulacji na osi" className="space-y-1">
      <div className="flex flex-wrap items-baseline gap-x-2 text-sm text-slate-600">
        <span className="text-lg font-bold tabular-nums text-slate-900" data-testid="timeline-time">
          {formatSimTime(simTime)}
        </span>
        <span className="first-letter:uppercase">{formatSimDate(simTime)}</span>
        {line.planned && <span className="text-xs text-slate-500">· koniec symulacji o {formatSimTime(run.horizon_end)}</span>}
      </div>
      <div className="relative pt-3 pb-4">
        {/* Starty pozycji planu nad paskiem. */}
        {line.markers.map((marker) => (
          <span
            key={`${marker.name}-${marker.start}`}
            className="absolute top-0 h-2.5 w-0.5 -translate-x-1/2 rounded bg-emerald-600"
            style={{ left: percent(marker.at) }}
            title={`${marker.name}: start ${formatSimTime(marker.start)}`}
            aria-hidden="true"
          />
        ))}
        <div className="relative h-3 overflow-hidden rounded-full bg-slate-200" aria-hidden="true">
          {line.prices.map((band) => (
            <span
              key={band.from}
              className={`absolute inset-y-0 ${PRICE_COLORS[band.level] ?? "bg-slate-200"}`}
              style={{ left: percent(band.from), width: percent(band.to - band.from) }}
            />
          ))}
          {line.approximateFrom != null && (
            // Ceny przybliżone (noc po dniu planu) w paski, żeby nie wyglądały na prawdziwe.
            <span
              className="absolute inset-y-0 right-0"
              style={{
                left: percent(line.approximateFrom),
                backgroundImage:
                  "repeating-linear-gradient(135deg, rgba(255,255,255,0.75) 0 3px, transparent 3px 7px)",
              }}
            />
          )}
          {/* Minione godziny przyciemnione: od razu widać, ile planu już za nami. */}
          <span className="absolute inset-y-0 left-0 bg-slate-900/15" style={{ width: percent(line.now) }} />
        </div>
        <span
          className="absolute top-1.5 h-6 w-1 -translate-x-1/2 rounded-full bg-slate-900 ring-2 ring-white"
          style={{ left: percent(line.now) }}
          aria-hidden="true"
        />
        {line.ticks.map((tick) => (
          <span
            key={tick.time}
            className={`absolute bottom-0 text-[10px] tabular-nums text-slate-500 ${
              tick.at < 0.02 ? "" : tick.at > 0.98 ? "-translate-x-full" : "-translate-x-1/2"
            }`}
            style={{ left: percent(tick.at) }}
            aria-hidden="true"
          >
            {formatSimTime(new Date(tick.time).toISOString())}
          </span>
        ))}
      </div>
      {line.planned && line.prices.length > 0 && (
        <ul className="flex flex-wrap gap-3 text-[11px] text-slate-500" aria-label="Ceny na pasku">
          <li className="flex items-center gap-1"><span className="h-2 w-3 rounded-sm bg-emerald-300" />tanio</li>
          <li className="flex items-center gap-1"><span className="h-2 w-3 rounded-sm bg-amber-200" />średnio</li>
          <li className="flex items-center gap-1"><span className="h-2 w-3 rounded-sm bg-rose-300" />drogo</li>
          <li className="flex items-center gap-1"><span className="h-2.5 w-0.5 rounded bg-emerald-600" />start z planu</li>
          {line.approximateFrom != null && (
            <li className="flex items-center gap-1">
              <span
                className="h-2 w-3 rounded-sm bg-amber-200"
                style={{ backgroundImage: "repeating-linear-gradient(135deg, rgba(255,255,255,0.75) 0 2px, transparent 2px 5px)" }}
              />
              od {formatSimTime(run.prices_approximate_from)} ceny przybliżone: nie były jeszcze znane, przyjęte z tych
              samych godzin dnia planu
            </li>
          )}
        </ul>
      )}
    </section>
  );
}

export default HouseTimeline;
