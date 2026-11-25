import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { axisUnitLabel, formatAxis, formatNumber } from "../../utils/format";

const MAX_DAYS = 60;

function AccuracyTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const day = payload[0].payload;
  const error = day.actual_kwh > 0 ? Math.abs(day.model_kwh - day.actual_kwh) / day.actual_kwh : null;
  return (
    <div className="rounded-lg border border-gray-100 bg-white p-3 text-xs shadow-xl">
      <p className="mb-1 font-medium text-gray-500">{day.date}</p>
      <p>Z pliku: <span className="font-medium">{formatNumber(day.actual_kwh, 1)} kWh</span></p>
      <p>Z modelu: <span className="font-medium">{formatNumber(day.model_kwh, 1)} kWh</span></p>
      {error != null && <p className="mt-1 text-gray-500">Różnica {formatNumber(error * 100, 0)}% · kliknij, żeby zobaczyć dzień</p>}
    </div>
  );
}

function PvAccuracyChart({ days, onSelect }) {
  const recent = days.slice(-MAX_DAYS);
  return (
    <>
      {days.length > MAX_DAYS && (
        <p className="mb-2 text-xs text-gray-500">Ostatnie {MAX_DAYS} dni z {days.length} z produkcją w plikach.</p>
      )}
      <div className="h-[240px]" aria-label="Produkcja z pliku i z modelu w kolejnych dniach">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={recent} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} onClick={(state) => state?.activeLabel && onSelect(state.activeLabel)}>
            <CartesianGrid stroke="#f1f5f9" vertical={false} />
            <XAxis dataKey="date" tickFormatter={(value) => `${value.slice(8, 10)}.${value.slice(5, 7)}`} tick={{ fontSize: 11, fill: "#94a3b8" }} minTickGap={16} />
            <YAxis tickFormatter={formatAxis} tick={{ fontSize: 11, fill: "#94a3b8" }} width={48} label={axisUnitLabel("kWh")} />
            <Tooltip content={<AccuracyTooltip />} cursor={{ fill: "#f8fafc" }} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar dataKey="actual_kwh" name="Z pliku" fill="#059669" isAnimationActive={false} className="cursor-pointer" />
            <Bar dataKey="model_kwh" name="Z modelu" fill="#f59e0b" isAnimationActive={false} className="cursor-pointer" />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </>
  );
}

export default PvAccuracyChart;
