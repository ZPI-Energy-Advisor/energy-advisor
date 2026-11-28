import { useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import ChartTooltip from "../ChartTooltip";
import SegmentedControl from "../SegmentedControl";
import { chartKeysOf, chartTariffKeys, findEntry, keyLabel } from "../../utils/tariffComparison";
import { formatDate } from "../../utils/energyFiles";
import { axisUnitLabel, formatAxis, formatNumber } from "../../utils/format";
import { ChartSkeleton } from "../Skeleton";
import { CARD } from "../uiStyles";

const COLORS = ["#10b981", "#3b82f6", "#f59e0b", "#ef4444", "#8b5cf6", "#0ea5e9", "#ec4899", "#84cc16"];
const METRIC_OPTIONS = [
  { value: "cost", label: "Koszt energii", activeClassName: "text-emerald-700" },
  { value: "price", label: "Cena kWh brutto", activeClassName: "text-blue-700" },
];
const RESOLUTION_OPTIONS = [
  { value: "1h", label: "Godzinowo" },
  { value: "15m", label: "15 min" },
];

// Krótkie przejście między miarą, rozdzielczością i taryfami (najwyżej kilka linii po 96 punktów).
const ANIMATION_MS = 400;

// „Typowy dzień”: z ilu dni i z jakiego okresu jest średnia, żeby było jasne, co pokazuje wykres.
const averageText = (statistics) => {
  const days = statistics?.days_analyzed;
  if (!days) return "Typowy dzień w wybranym okresie";
  const span = statistics.data_start && statistics.data_end
    ? ` (${formatDate(statistics.data_start)} – ${formatDate(statistics.data_end)})`
    : "";
  return `Typowy dzień: średnio z ${days} ${days === 1 ? "dnia" : "dni"}${span}`;
};

function TooltipValues({ payload, unit, labels }) {
  return (
    <div className="space-y-1.5">
      {payload.map((entry) => (
        <div key={entry.dataKey} className="flex items-center justify-between gap-3">
          <span className="flex items-center gap-1.5 text-xs md:text-sm font-medium">
            <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: entry.color }} />
            {labels[entry.dataKey]}
          </span>
          <span className="text-sm font-bold text-gray-900">
            {formatNumber(entry.value)} <span className="text-[10px] md:text-xs font-normal text-gray-500">{unit}</span>
          </span>
        </div>
      ))}
    </div>
  );
}

function TariffDayChart({ results, comparison, chosenKey, failed = false, onRetry }) {
  const [metric, setMetric] = useState("cost");
  const [resolution, setResolution] = useState("1h");
  const [showAll, setShowAll] = useState(false);

  const ready = results?.pricing?.all_tariffs === true;
  const rows = (resolution === "15m" ? results?.chart_15min : results?.chart_hourly) ?? [];
  const chartKeys = chartKeysOf(rows);
  const keys = ready ? chartTariffKeys(comparison, chosenKey, showAll, chartKeys) : [];
  const order = comparison ? comparison.tariffs.map((entry) => entry.key) : chartKeys;
  const labels = Object.fromEntries(
    order.map((key) => [`${metric}_${key}`, findEntry(comparison, key)?.label ?? keyLabel(key)]),
  );
  const unit = metric === "price" ? "zł/kWh" : "zł";

  return (
    <section className={`${CARD} mb-6`} aria-labelledby="tariff-chart-title">
      <div className="mb-4 flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <h3 id="tariff-chart-title" className="font-semibold text-gray-900">Kiedy płacisz najwięcej</h3>
          <p className="mt-1 text-xs md:text-sm text-gray-500">
            {averageText(results?.statistics)}.{" "}
            {metric === "price"
              ? "Średnia cena kWh brutto w każdej godzinie."
              : "Ile średnio płacisz za energię w każdej godzinie (zużycie × cena kWh brutto, bez opłat miesięcznych i PV)."}
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <SegmentedControl label="Miara wykresu" options={METRIC_OPTIONS} value={metric} onChange={setMetric} />
          <SegmentedControl label="Rozdzielczość wykresu" options={RESOLUTION_OPTIONS} value={resolution} onChange={setResolution} />
        </div>
      </div>
      {comparison && (
      <label className="mb-3 inline-flex items-center gap-2 text-sm text-gray-700">
        <input
          type="checkbox"
          checked={showAll}
          onChange={(event) => setShowAll(event.target.checked)}
          className="h-4 w-4 rounded border-gray-300 text-emerald-600 focus:ring-emerald-500"
        />
        Pokaż wszystkie taryfy
      </label>
      )}
      {!ready && failed ? (
        <div role="alert" className="py-16 text-center text-sm text-gray-600">
          Nie udało się pobrać cen do wykresu.{" "}
          <button type="button" onClick={onRetry} className="font-semibold text-emerald-700 underline">
            Spróbuj ponownie
          </button>
        </div>
      ) : !ready ? (
        <ChartSkeleton label="Ładowanie wykresu..." />
      ) : keys.length === 0 || rows.length === 0 ? (
        <p className="py-16 text-center text-sm text-gray-500">Brak cen do wykresu w tym okresie.</p>
      ) : (
        <div className="h-[280px] md:h-[400px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rows} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
              <XAxis
                dataKey={resolution === "15m" ? "time" : "hour"}
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 10, fill: "#64748b" }}
                dy={10}
                minTickGap={20}
              />
              <YAxis
                axisLine={false}
                tickLine={false}
                tick={{ fontSize: 10, fill: "#64748b" }}
                tickFormatter={formatAxis}
                width={52}
                label={axisUnitLabel(unit)}
              />
              <Tooltip
                content={
                  <ChartTooltip
                    resolution={resolution}
                    render={(payload) => <TooltipValues payload={payload} unit={unit} labels={labels} />}
                  />
                }
              />
              <Legend
                verticalAlign="top"
                height={36}
                iconType="circle"
                wrapperStyle={{ fontSize: "12px" }}
                formatter={(value) => <span className="font-medium text-gray-700">{labels[value] ?? value}</span>}
              />
              {keys.map((key) => (
                <Line
                  key={key}
                  type={metric === "price" ? "stepAfter" : "monotone"}
                  dataKey={`${metric}_${key}`}
                  stroke={COLORS[order.indexOf(key) % COLORS.length]}
                  strokeWidth={key === chosenKey ? 3.5 : 2}
                  dot={false}
                  activeDot={{ r: 5, strokeWidth: 0 }}
                  animationDuration={ANIMATION_MS}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}

export default TariffDayChart;
