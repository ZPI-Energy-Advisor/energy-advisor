import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { clockOf, dayPrices, dayRows, formatDayMonth, formatPln } from "../utils/schedule";

const PRICE_COLOR = "#10b981";
const HOURS = [0, 6, 12, 18, 24];
const LABEL_WIDTH = "w-28 md:w-36 shrink-0";

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

function actionTitle({ action }) {
  const program = action.program_name ? ` (${action.program_name})` : "";
  return (
    `${action.device_name}${program}: ${clockOf(action.original_start)} → ${clockOf(action.start)}, ` +
    `${formatPln(action.cost_before)} → ${formatPln(action.cost_after)}`
  );
}

function Lane({ segments, className, label }) {
  return (
    <div className="relative h-3" aria-label={label}>
      {segments.map((segment) => (
        <div
          key={segment.action.action_id}
          title={actionTitle(segment)}
          className={`absolute inset-y-0 rounded-sm ${className(segment.action)}`}
          style={{ left: `${segment.left}%`, width: `${segment.width}%` }}
        />
      ))}
    </div>
  );
}

const afterColor = (action) => (action.status === "moved" ? "bg-emerald-500" : "bg-gray-400");

// Doba: wykres cen, a pod nim dla każdego urządzenia akcje przed i po optymalizacji, na tej samej osi.
function ScheduleDayChart({ day, actions, prices, isTail = false }) {
  const points = dayPrices(prices, day);
  const rows = dayRows(actions, day);

  return (
    <section className="bg-white p-4 md:p-5 rounded-lg shadow-sm border border-gray-100">
      <h3 className="font-bold text-gray-900 mb-3">
        {formatDayMonth(day)}
        {isTail && <span className="ml-2 text-sm font-normal text-gray-500">dokończenie akcji z poprzedniego dnia</span>}
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
            <div className="flex-1 min-w-0 space-y-0.5 bg-gray-50 rounded-sm py-0.5">
              <Lane segments={row.before} className={() => "bg-gray-300"} label={`${row.name} przed`} />
              <Lane segments={row.after} className={afterColor} label={`${row.name} po`} />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

export default ScheduleDayChart;
