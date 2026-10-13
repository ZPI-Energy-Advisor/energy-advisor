import { useMemo } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  buildAxisTicks,
  buildStatusAreas,
  formatAxisPrice,
  formatPointLabel,
  formatPointTick,
  formatPrice,
} from "../utils/dynamicPrices";

const PRICE_COLOR = "#10b981";
const AVERAGE_COLOR = "#2563eb";

function PriceTooltip({ active, payload, resolution }) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;

  return (
    <div className="bg-white p-3 border border-gray-100 shadow-xl rounded-lg min-w-[180px]">
      <p className="text-gray-500 font-medium text-sm mb-1">{formatPointLabel(point.start, resolution)}</p>
      {point.price_pln_kwh == null ? (
        <p className="text-sm font-medium text-gray-400">Brak danych</p>
      ) : (
        <>
          <p className="font-bold text-xl text-emerald-600">{formatPrice(point.price_pln_kwh)}</p>
          <p className="text-xs text-gray-500">brutto, w taryfie dynamicznej</p>
          {!point.complete && (
            <p className="mt-1 text-xs text-amber-600">
              Niepełne dane: {point.intervals} z {point.expected_intervals} kwadransów
            </p>
          )}
        </>
      )}
    </div>
  );
}

function IncompleteDot({ cx, cy, payload }) {
  if (payload.complete || payload.price_pln_kwh == null || cx == null || cy == null) return null;
  return <circle cx={cx} cy={cy} r={3} fill="#f59e0b" stroke="#fff" strokeWidth={1} />;
}

function LegendItem({ swatch, children }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      {swatch}
      {children}
    </span>
  );
}

function PriceChart({ history, resolution }) {
  const { points, days } = history;
  const axis = useMemo(() => {
    const { ticks, singleDay } = buildAxisTicks(points, resolution);
    const multiYear = history.date_from.slice(0, 4) !== history.date_to.slice(0, 4);
    return { ticks, singleDay, multiYear };
  }, [points, resolution, history.date_from, history.date_to]);
  const statusAreas = useMemo(() => buildStatusAreas(points, days), [points, days]);
  const hasNegative = history.min_price_pln_kwh < 0;

  return (
    <>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mb-3 text-xs text-gray-600">
        <LegendItem swatch={<span className="w-4 h-0.5 rounded" style={{ backgroundColor: PRICE_COLOR }} />}>
          Cena w taryfie
        </LegendItem>
        <LegendItem swatch={<span className="w-4 border-t-2 border-dashed" style={{ borderColor: AVERAGE_COLOR }} />}>
          Średnia w okresie: <span className="font-semibold text-gray-800">{formatPrice(history.average_price_pln_kwh)}</span>
        </LegendItem>
        {days.incomplete.length > 0 && (
          <LegendItem swatch={<span className="w-3 h-3 rounded-sm bg-amber-100 border border-amber-200" />}>
            Niepełne dane
          </LegendItem>
        )}
        {days.missing.length > 0 && (
          <LegendItem swatch={<span className="w-3 h-3 rounded-sm bg-slate-200 border border-slate-300" />}>
            Brak danych
          </LegendItem>
        )}
      </div>

      <div className="h-[300px] md:h-[400px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={points} margin={{ top: 10, right: 12, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="priceFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={PRICE_COLOR} stopOpacity={0.3} />
                <stop offset="100%" stopColor={PRICE_COLOR} stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
            {statusAreas.map((area) => (
              <ReferenceArea
                key={`${area.status}-${area.x1}`}
                x1={area.x1}
                x2={area.x2}
                fill={area.status === "missing" ? "#e2e8f0" : "#fef3c7"}
                fillOpacity={0.7}
                strokeOpacity={0}
                label={
                  area.status === "missing"
                    ? { value: "Brak danych", position: "center", fontSize: 11, fill: "#64748b" }
                    : undefined
                }
              />
            ))}
            <XAxis
              dataKey="start"
              ticks={axis.ticks}
              interval={axis.ticks ? 0 : "preserveStartEnd"}
              tickFormatter={(value) => formatPointTick(value, axis)}
              axisLine={false}
              tickLine={false}
              tick={{ fontSize: 11, fill: "#64748b" }}
              dy={8}
              minTickGap={24}
            />
            <YAxis
              tickFormatter={formatAxisPrice}
              axisLine={false}
              tickLine={false}
              tick={{ fontSize: 11, fill: "#64748b" }}
              width={48}
              label={{ value: "zł/kWh", angle: -90, position: "insideLeft", offset: 8, fontSize: 11, fill: "#94a3b8" }}
            />
            <Tooltip
              content={<PriceTooltip resolution={resolution} />}
              cursor={{ stroke: "#cbd5e1", strokeWidth: 1 }}
            />
            {hasNegative && <ReferenceLine y={0} stroke="#94a3b8" />}
            <ReferenceLine y={history.average_price_pln_kwh} stroke={AVERAGE_COLOR} strokeDasharray="6 4" strokeWidth={1.5} />
            <Area
              type={resolution === "day" ? "monotone" : "stepAfter"}
              dataKey="price_pln_kwh"
              stroke={PRICE_COLOR}
              strokeWidth={1.75}
              fill="url(#priceFill)"
              dot={<IncompleteDot />}
              activeDot={{ r: 4, fill: PRICE_COLOR, stroke: "#fff", strokeWidth: 2 }}
              connectNulls={false}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </>
  );
}

export default PriceChart;
