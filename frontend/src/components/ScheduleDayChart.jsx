import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatNumber } from "../utils/format";
import { actionSummary, dayOf, dayPrices, dayRows, formatDayMonth, formatPln } from "../utils/schedule";
import { cloudLabel, hourlyWeather } from "../utils/weather";

const PRICE_COLOR = "#10b981";
const HOURS = [0, 6, 12, 18, 24];
const LABEL_WIDTH = "w-28 md:w-36 shrink-0";
const SURPLUS_KWH = 0.05;
const CLEAR_SKY = [186, 230, 253];
const OVERCAST = [156, 163, 175];

const skyColor = (cloud) => {
  const share = Math.min(Math.max(cloud ?? 0, 0), 100) / 100;
  const [r, g, b] = CLEAR_SKY.map((value, index) => Math.round(value + (OVERCAST[index] - value) * share));
  return `rgb(${r}, ${g}, ${b})`;
};

const hourText = (hour) => `${String(hour).padStart(2, "0")}:00`;
// Godziny doby jako 24 kolumny siatki: bez szczelin z zaokrągleń szerokości w procentach.
const HOUR_GRID = { display: "grid", gridTemplateColumns: "repeat(24, minmax(0, 1fr))" };
const hourCell = (hour) => ({ gridColumn: `${hour + 1}`, gridRow: "1" });

function WeatherRow({ hours }) {
  return (
    <div className="flex mt-1">
      <div className={`${LABEL_WIDTH} text-xs text-gray-500`}>Pogoda</div>
      <div className="flex-1 min-w-0">
        <div className="h-3 rounded-sm bg-gray-100 overflow-hidden" style={HOUR_GRID} aria-label="Zachmurzenie co godzinę">
          {hours.map((entry) => (
            <div
              key={entry.hour}
              style={{ ...hourCell(entry.hour), backgroundColor: skyColor(entry.cloud) }}
              title={`${hourText(entry.hour)}: ${cloudLabel(entry.cloud) ?? "brak danych"}${
                entry.temperature != null ? `, ${formatNumber(entry.temperature, 0)}°C` : ""}`}
            />
          ))}
        </div>
        <div className="relative h-4 text-[11px] text-gray-600" aria-label="Temperatura co godzinę">
          {hours.filter((entry) => entry.hour % 3 === 0 && entry.temperature != null).map((entry) => (
            <span
              key={entry.hour}
              className={`absolute -translate-x-1/2 tabular-nums ${entry.hour % 6 ? "hidden sm:inline" : ""}`}
              style={{ left: `${((entry.hour + 0.5) / 24) * 100}%` }}
            >
              {formatNumber(entry.temperature, 0)}°
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function PvRow({ hours, note }) {
  const peak = Math.max(...hours.map((entry) => entry.planned), 0);
  return (
    <div className="flex mt-1 mb-1">
      <div className={`${LABEL_WIDTH} text-xs text-gray-500`}>Z paneli</div>
      {note ? (
        <p className="flex-1 min-w-0 text-xs text-gray-500" role="note">{note}</p>
      ) : (
        <div className="flex-1 min-w-0 h-8 bg-gray-50 rounded-sm" style={HOUR_GRID} aria-label="Prąd z paneli co godzinę">
          {hours.map((entry) => (
            <div
              key={entry.hour}
              className={`flex items-end ${entry.surplus ? "bg-amber-100" : ""}`}
              style={hourCell(entry.hour)}
              title={`${hourText(entry.hour)}: plan liczy na ${formatNumber(entry.planned, 1)} kWh z paneli${
                entry.surplus ? `, nadwyżka nad resztą domu ${formatNumber(entry.surplusKwh, 1)} kWh` : ""}`}
              data-surplus={entry.surplus || undefined}
            >
              <div
                className="w-full rounded-t-sm bg-amber-400"
                style={{ height: `${peak ? Math.max((entry.planned / peak) * 100, 4) : 0}%` }}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const pvHours = (pv, day) =>
  (pv?.hours ?? [])
    .filter((entry) => dayOf(entry.start) === day)
    .map((entry) => ({
      hour: Number(entry.start.slice(11, 13)),
      planned: entry.planned_kwh,
      surplusKwh: entry.surplus_kwh,
      surplus: entry.surplus_kwh >= SURPLUS_KWH,
    }));

function PriceTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const { minute, price } = payload[0].payload;
  const label = `${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}`;
  return (
    <div className="bg-white border border-gray-200 rounded shadow-sm px-2 py-1 text-xs">
      {label}: <span className="font-medium">{formatPln(price)}/kWh</span>
    </div>
  );
}

function SurplusShade({ hours }) {
  const surplus = hours.filter((entry) => entry.surplus);
  if (!surplus.length) return null;
  return (
    <div aria-hidden="true" className="absolute inset-0 -z-10 !mt-0" style={HOUR_GRID}>
      {surplus.map((entry) => (
        <div key={entry.hour} className="bg-amber-100" style={hourCell(entry.hour)} />
      ))}
    </div>
  );
}

function Lane({ segments, className, label }) {
  return (
    <div className="relative h-3" aria-label={label}>
      {segments.map((segment) => (
        <div
          key={`${segment.action.action_id}-${segment.left}`}
          title={actionSummary(segment.action)}
          className={`absolute inset-y-0 rounded-sm ${className(segment.action)}`}
          style={{ left: `${segment.left}%`, width: `${segment.width}%` }}
        />
      ))}
    </div>
  );
}

const afterColor = (action) => (action.status === "moved" ? "bg-emerald-500" : "bg-gray-400");

// Doba: wykres cen, pogoda i prąd z paneli z planu, a pod nimi dla każdego urządzenia akcje przed i po
// optymalizacji, na tej samej osi. Godziny z nadwyżką paneli są podświetlone także pod urządzeniami.
function ScheduleDayChart({ day, actions, prices, isTail = false, subtitle = null, weather = null, pv = null, pvNote = null }) {
  const points = dayPrices(prices, day);
  const rows = dayRows(actions, day);
  const weatherHours = hourlyWeather(weather?.quarters, day);
  const sun = pvHours(pv, day);

  return (
    <section className="bg-white p-4 md:p-5 rounded-lg shadow-sm border border-gray-100">
      <h3 className="font-bold text-gray-900 mb-3">
        {formatDayMonth(day)}
        {(subtitle || isTail) && (
          <span className="ml-2 text-sm font-normal text-gray-500">{subtitle ?? "dokończenie akcji z poprzedniego dnia"}</span>
        )}
      </h3>

      <div className="flex">
        <div className={`${LABEL_WIDTH} text-xs text-gray-500 pt-1`}>Cena (zł/kWh)</div>
        <div className="flex-1 min-w-0 h-24">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={points} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
              <XAxis dataKey="minute" type="number" domain={[0, 1440]} hide />
              <YAxis hide domain={["auto", "auto"]} />
              <Tooltip content={<PriceTooltip />} />
              <Area type="stepAfter" dataKey="price" stroke={PRICE_COLOR} fill={PRICE_COLOR} fillOpacity={0.15} isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {weatherHours.length > 0 && <WeatherRow hours={weatherHours} />}
      {(sun.length > 0 || pvNote) && <PvRow hours={sun} note={sun.length ? null : pvNote} />}

      <div className="flex mb-2">
        <div className={LABEL_WIDTH} />
        <div className="flex-1 min-w-0 relative h-4 text-[11px] text-gray-400">
          {HOURS.map((hour) => (
            <span
              key={hour}
              className="absolute -translate-x-1/2 first:translate-x-0 last:-translate-x-full"
              style={{ left: `${(hour / 24) * 100}%` }}
            >
              {hour}:00
            </span>
          ))}
        </div>
      </div>

      <div className="space-y-2">
        {rows.map((row) => (
          <div key={row.deviceId} className="flex items-center">
            <div className={`${LABEL_WIDTH} text-sm text-gray-700 truncate pr-2`} title={row.name}>
              {row.name}
            </div>
            <div className="relative isolate flex-1 min-w-0 space-y-0.5 bg-gray-50 rounded-sm py-0.5">
              <Lane segments={row.before} className={() => "bg-gray-300"} label={`${row.name} przed`} />
              <Lane segments={row.after} className={afterColor} label={`${row.name} po`} />
              <SurplusShade hours={sun} />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

export default ScheduleDayChart;
