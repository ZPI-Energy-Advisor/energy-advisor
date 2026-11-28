import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { clockOf, formatDayMonth, dayOf } from "../utils/schedule";
import { formatDegrees } from "../utils/format";

const AFTER_COLOR = "#10b981";
const BEFORE_COLOR = "#9ca3af";

const degrees = (value) => formatDegrees(value, 1);

function TemperatureTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div className="bg-white border border-gray-200 rounded shadow-sm px-2 py-1 text-xs space-y-0.5">
      <p className="font-medium">{formatDayMonth(dayOf(point.start))} {clockOf(point.end)}</p>
      <p className="text-emerald-700">według planu: {degrees(point.after)}</p>
      <p className="text-gray-500">bez planu: {degrees(point.before)}</p>
    </div>
  );
}

// Temperatura wody w bojlerze w planie i bez planu (termostat), z wymaganiami: gotowa i minimum.
function WaterTemperatureChart({ heater }) {
  const points = heater.temperatures.map((point, index) => ({
    ...point,
    index,
    // Temperatura jest na końcu kwadransu: oś pokazuje godzinę końca.
    end: heater.temperatures[index + 1]?.start ?? point.start,
  }));
  const ticks = points.filter((point) => clockOf(point.start).endsWith(":00") && Number(clockOf(point.start).slice(0, 2)) % 6 === 0);

  return (
    // Treść okienka „Temperatura wody” w planie (tytuł daje okienko).
    <div>
      <p className="text-sm text-gray-600">
        Bez planu bojler cały czas trzyma tę samą temperaturę. Według planu nagrzewa wodę na zapas, kiedy prąd
        jest tani, a w nocy pozwala jej trochę ostygnąć. Woda jest gorąca na {heater.ready_times.join(" i ")}.
      </p>
      {heater.shortfall > 0 && (
        <p className="mt-2 p-2 text-xs text-amber-900 bg-amber-50 rounded">
          Bojler nie zdąży nagrzać tyle wody, ile zwykle zużywacie. Pomoże większy zbiornik.
        </p>
      )}
      <div className="mt-3 h-48">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 4, right: 8, bottom: 0, left: -16 }}>
            <CartesianGrid stroke="#f3f4f6" vertical={false} />
            <XAxis
              dataKey="index"
              type="number"
              domain={[0, points.length - 1]}
              ticks={ticks.map((point) => point.index)}
              tickFormatter={(index) => clockOf(points[index].start)}
              tick={{ fontSize: 11, fill: "#9ca3af" }}
            />
            <YAxis domain={[30, 80]} ticks={[40, 55, 75]} tick={{ fontSize: 11, fill: "#9ca3af" }} />
            <ReferenceLine y={heater.ready_temp} stroke="#f59e0b" strokeDasharray="4 4" />
            <ReferenceLine y={heater.min_temp} stroke="#ef4444" strokeDasharray="4 4" />
            <Tooltip content={<TemperatureTooltip />} />
            <Line type="monotone" dataKey="before" stroke={BEFORE_COLOR} dot={false} strokeWidth={1.5} isAnimationActive={false} />
            <Line type="monotone" dataKey="after" stroke={AFTER_COLOR} dot={false} strokeWidth={2} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-2 flex flex-wrap gap-4 text-xs text-gray-600">
        <span className="flex items-center gap-1.5"><i className="w-4 h-0.5 bg-emerald-500" /> według planu</span>
        <span className="flex items-center gap-1.5"><i className="w-4 h-0.5 bg-gray-400" /> bez planu (termostat)</span>
        <span className="flex items-center gap-1.5"><i className="w-4 border-t border-dashed border-amber-500" /> woda gotowa</span>
        <span className="flex items-center gap-1.5"><i className="w-4 border-t border-dashed border-red-500" /> minimum</span>
      </div>
    </div>
  );
}

export default WaterTemperatureChart;
