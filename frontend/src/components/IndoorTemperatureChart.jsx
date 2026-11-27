import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { clockOf } from "../utils/schedule";
import { formatNumber } from "../utils/format";

const AFTER_COLOR = "#10b981";
const BEFORE_COLOR = "#9ca3af";

const degrees = (value) => `${formatNumber(value, 1)}°C`;

function IndoorTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div className="bg-white border border-gray-200 rounded shadow-sm px-2 py-1 text-xs space-y-0.5">
      <p className="font-medium">{clockOf(point.start)}</p>
      <p className="text-emerald-700">w domu według planu: {degrees(point.after)}</p>
      <p className="text-gray-500">na dworze: {degrees(point.outdoor)}</p>
    </div>
  );
}

// Temperatura w domu przez dobę planu: plan grzeje na zapas w tanich godzinach i pozwala jej spaść w drogich,
// zawsze w zakresie ustawiona ± 1 °C.
function IndoorTemperatureChart({ pump }) {
  const points = pump.temperatures.map((point, index) => ({ ...point, index }));
  const ticks = points
    .filter((point) => clockOf(point.start).endsWith(":00") && Number(clockOf(point.start).slice(0, 2)) % 6 === 0)
    .map((point) => point.index);
  const [low, high] = pump.band;
  return (
    // Treść okienka „Temperatura w domu” w planie (tytuł daje okienko).
    <div>
      <p className="text-sm text-gray-600">
        Bez planu pompa cały czas trzyma {formatNumber(pump.indoor_c, 0)}°C. Według planu nagrzewa dom na zapas, kiedy
        prąd jest tani, i pozwala mu trochę ostygnąć, kiedy jest drogi, zawsze między {formatNumber(low, 0)} a{" "}
        {formatNumber(high, 0)}°C.
      </p>
      <div className="mt-3 h-48">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 4, right: 8, bottom: 0, left: -16 }}>
            <CartesianGrid stroke="#f3f4f6" vertical={false} />
            <XAxis
              dataKey="index"
              type="number"
              domain={[0, points.length - 1]}
              ticks={ticks}
              tickFormatter={(index) => clockOf(points[index].start)}
              tick={{ fontSize: 11, fill: "#9ca3af" }}
            />
            <YAxis domain={[low - 1, high + 1]} ticks={[low, pump.indoor_c, high]} tick={{ fontSize: 11, fill: "#9ca3af" }} />
            <ReferenceLine y={low} stroke="#f59e0b" strokeDasharray="4 4" />
            <ReferenceLine y={high} stroke="#f59e0b" strokeDasharray="4 4" />
            <Tooltip content={<IndoorTooltip />} />
            <Line type="monotone" dataKey="before" stroke={BEFORE_COLOR} dot={false} strokeWidth={1.5} isAnimationActive={false} />
            <Line type="monotone" dataKey="after" stroke={AFTER_COLOR} dot={false} strokeWidth={2} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-2 flex flex-wrap gap-4 text-xs text-gray-600">
        <span className="flex items-center gap-1.5"><i className="w-4 h-0.5 bg-emerald-500" /> w domu według planu</span>
        <span className="flex items-center gap-1.5"><i className="w-4 h-0.5 bg-gray-400" /> bez planu (stała temperatura)</span>
        <span className="flex items-center gap-1.5"><i className="w-4 border-t border-dashed border-amber-500" /> zakres</span>
      </div>
    </div>
  );
}

export default IndoorTemperatureChart;
