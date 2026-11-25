import { Area, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { axisUnitLabel, formatAxis, formatNumber } from "../../utils/format";
import { chartPoints } from "../../utils/pv";

const COLORS = { model: "#f59e0b", actual: "#059669", consumption: "#64748b" };
const Y_AXIS_WIDTH = 48;

function PvTooltip({ active, payload, modelLabel, consumptionLabel }) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  const row = (label, value, unit, color) =>
    value == null ? null : (
      <p className="flex justify-between gap-4">
        <span style={{ color }}>{label}</span>
        <span className="font-medium text-gray-900">{formatNumber(value, unit === "kW" ? 2 : 0)} {unit}</span>
      </p>
    );
  return (
    <div className="min-w-[200px] rounded-lg border border-gray-100 bg-white p-3 text-xs shadow-xl">
      <p className="mb-1 font-medium text-gray-500">{point.label}</p>
      {row(modelLabel, point.model, "kW", COLORS.model)}
      {row("Produkcja z pliku", point.actual, "kW", COLORS.actual)}
      {row(consumptionLabel, point.consumption, "kW", COLORS.consumption)}
      {row("Zachmurzenie", point.cloud, "%", "#475569")}
      {row("Temperatura", point.temperature, "°C", "#6b7280")}
    </div>
  );
}

function CloudStrip({ points }) {
  const values = points.map((point) => point.cloud).filter((value) => value != null);
  if (!values.length) return null;
  return (
    <div className="mt-2" style={{ paddingLeft: Y_AXIS_WIDTH, paddingRight: 8 }}>
      <div className="flex h-3 overflow-hidden rounded-sm" role="img" aria-label="Zachmurzenie w ciągu doby">
        {points.map((point) => (
          <div
            key={point.start}
            className="flex-1"
            title={point.cloud == null ? point.label : `${point.label}: zachmurzenie ${point.cloud}%`}
            style={{ backgroundColor: point.cloud == null ? "#f8fafc" : `rgba(100, 116, 139, ${0.08 + (point.cloud / 100) * 0.6})` }}
          />
        ))}
      </div>
      <p className="mt-1 flex justify-between text-[11px] text-gray-500">
        <span>Zachmurzenie nieba (jaśniej = mniej chmur)</span>
        <span>{Math.min(...values)}–{Math.max(...values)}%</span>
      </p>
    </div>
  );
}

function PvDayChart({ intervals, modelLabel, consumptionLabel = "Zużycie domu", consumptionEstimated = false }) {
  const points = chartPoints(intervals);
  const hasActual = points.some((point) => point.actual != null);
  const hasConsumption = points.some((point) => point.consumption != null);
  const ticks = points
    .filter((point) => point.label.endsWith(":00") && Number(point.label.slice(0, 2)) % 3 === 0)
    .map((point) => point.start);

  return (
    <div>
      <div className="h-[280px] md:h-[340px]" aria-label="Produkcja PV i zużycie domu w ciągu doby">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="#f1f5f9" vertical={false} />
            <XAxis
              dataKey="start"
              ticks={ticks}
              tickFormatter={(value) => points.find((point) => point.start === value)?.label ?? ""}
              tick={{ fontSize: 11, fill: "#94a3b8" }}
            />
            <YAxis tickFormatter={formatAxis} tick={{ fontSize: 11, fill: "#94a3b8" }} width={Y_AXIS_WIDTH} label={axisUnitLabel("kW")} />
            <Tooltip content={<PvTooltip modelLabel={modelLabel} consumptionLabel={consumptionLabel} />} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {hasConsumption && (
              <Area
                type="stepAfter"
                dataKey="consumption"
                name={consumptionLabel}
                stroke={COLORS.consumption}
                strokeDasharray={consumptionEstimated ? "4 3" : undefined}
                fill={COLORS.consumption}
                fillOpacity={consumptionEstimated ? 0.03 : 0.08}
                strokeWidth={1}
                isAnimationActive={false}
              />
            )}
            <Area type="monotone" dataKey="model" name={modelLabel} stroke={COLORS.model} fill={COLORS.model} fillOpacity={0.25} strokeWidth={2} isAnimationActive={false} />
            {hasActual && (
              <Line type="monotone" dataKey="actual" name="Produkcja z pliku" stroke={COLORS.actual} strokeWidth={2} dot={false} isAnimationActive={false} />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <CloudStrip points={points} />
    </div>
  );
}

export default PvDayChart;
