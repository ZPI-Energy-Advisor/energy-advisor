import { formatSimDate, formatSimTime } from "../../utils/home";
import { simTimeline } from "../../utils/houseView";

// Na cienkim pasku cen tylko skrajności: tanie i drogie kwadranse. Średnie zostają bez koloru, żeby pasek
// nie konkurował z domem.
const PRICE_COLORS = { cheap: "bg-emerald-400", expensive: "bg-rose-400" };
const percent = (fraction) => `${(fraction * 100).toFixed(3)}%`;

// Pasek czasu nad przekrojem domu: godzina symulacji widoczna razem z domem, bez przewijania do zegara.
// Gruby pasek to postęp czasu z kreską „teraz” i kreskami startów z planu; pod nim cienki pasek tanich
// i drogich kwadransów planu. Bez przebiegu planu pasek pokazuje dobę zegara bez cen.
function HouseTimeline({ run, simTime }) {
  const line = simTimeline(run, simTime);
  if (!line) return null;
  const approximateNote =
    line.approximateFrom != null
      ? `Ceny od ${formatSimTime(run.prices_approximate_from)} są przybliżone: nie były jeszcze znane, ` +
        "więc plan przyjął ceny z tych samych godzin dnia planu."
      : undefined;
  const hasPrices = line.prices.some((band) => PRICE_COLORS[band.level]);

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
        {line.markers.map((marker) => (
          <span
            key={`${marker.name}-${marker.start}`}
            className="absolute top-0 h-2.5 w-0.5 -translate-x-1/2 rounded bg-emerald-600"
            style={{ left: percent(marker.at) }}
            title={`${marker.name}: start ${formatSimTime(marker.start)}`}
            aria-hidden="true"
          />
        ))}
        <div className="relative h-2.5 overflow-hidden rounded-full bg-slate-200" aria-hidden="true">
          <span className="absolute inset-y-0 left-0 rounded-full bg-slate-400" style={{ width: percent(line.now) }} />
        </div>
        {hasPrices && (
          <div className="relative mt-1 h-1.5" title={approximateNote} data-testid="timeline-prices">
            {line.prices.map((band) =>
              PRICE_COLORS[band.level] ? (
                <span
                  key={band.from}
                  className={`absolute inset-y-0 ${PRICE_COLORS[band.level]} ${
                    line.approximateFrom != null && band.from >= line.approximateFrom ? "opacity-40" : ""
                  }`}
                  style={{ left: percent(band.from), width: percent(band.to - band.from) }}
                />
              ) : null,
            )}
          </div>
        )}
        <span
          className="absolute top-1.5 h-5 w-1 -translate-x-1/2 rounded-full bg-slate-900 ring-2 ring-white"
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
      {line.planned && (hasPrices || line.markers.length > 0) && (
        <p className="flex flex-wrap items-center gap-x-3 text-[11px] text-slate-500">
          {hasPrices && (
            <>
              <span className="flex items-center gap-1"><span className="h-1.5 w-3 rounded-sm bg-emerald-400" />tanio</span>
              <span className="flex items-center gap-1"><span className="h-1.5 w-3 rounded-sm bg-rose-400" />drogo</span>
            </>
          )}
          {line.markers.length > 0 && (
            <span className="flex items-center gap-1"><span className="h-2.5 w-0.5 rounded bg-emerald-600" />start z planu</span>
          )}
        </p>
      )}
    </section>
  );
}

export default HouseTimeline;
