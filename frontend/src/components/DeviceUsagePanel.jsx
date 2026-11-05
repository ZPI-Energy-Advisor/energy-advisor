import { useState } from "react";
import { FiArrowLeft, FiRepeat } from "react-icons/fi";
import { Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useDeviceUsage } from "../hooks/useDeviceUsage";
import SegmentedControl from "./SegmentedControl";
import {
  PRODUCTION_COLOR,
  PRODUCTION_KEY,
  breadcrumbs,
  buildChartRows,
  buildSeries,
  formatKwh,
  formatPln,
  formatShare,
  productionSeries,
  ranking,
  totals,
  usageQuery,
} from "../utils/deviceUsage";

const RESOLUTION_PREFIX = { "15m": "Średnio o", "1h": "Średnio o", "1d": "Dzień" };
const LEVEL_NAMES = ["kategorii", "typów", "urządzeń", "urządzenia"];
const FLEXIBLE_HINT = "Można przenieść na inne godziny";
const DEVICE_FILTER_OPTIONS = [
  { value: "all", label: "Wszystkie urządzenia" },
  { value: "flexible", label: "Tylko przesuwalne", title: "Urządzenia, których pracę można przenieść na inne godziny" },
];

// Znaczek przy urządzeniach (albo grupach z urządzeniami), które można przenieść na inne godziny.
function FlexibleMark({ item }) {
  const flexible = item.flexibilityMode ? item.flexibilityMode !== "fixed" : item.flexibleCount > 0;
  if (!flexible) return null;
  return <FiRepeat className="text-emerald-600 shrink-0" title={FLEXIBLE_HINT} aria-label={FLEXIBLE_HINT} />;
}

function UsageTooltip({ active, payload, label, series, resolution }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  const items = series.filter((item) => row[`${item.key}__kwh`] > 0.0005);
  const production = -(row[`${PRODUCTION_KEY}__kwh`] ?? 0);
  return (
    <div className="bg-white p-3 border border-gray-100 shadow-xl rounded-lg text-sm min-w-[180px]">
      <p className="text-gray-500 font-medium mb-2">
        {RESOLUTION_PREFIX[resolution]} {label}
      </p>
      {items.length === 0 && production <= 0 && <p className="text-gray-400">Brak zużycia</p>}
      <ul className="space-y-1">
        {items.map((item) => (
          <li key={item.key} className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ backgroundColor: item.color }} />
            <span className="text-gray-700">{item.label}</span>
            <span className="ml-auto font-medium text-gray-900 whitespace-nowrap">
              {formatKwh(row[`${item.key}__kwh`])} · {formatPln(row[`${item.key}__pln`])}
            </span>
          </li>
        ))}
        {production > 0 && (
          <li className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ backgroundColor: PRODUCTION_COLOR }} />
            <span className="text-gray-700">Produkcja fotowoltaiki</span>
            <span className="ml-auto font-medium text-gray-900 whitespace-nowrap">{formatKwh(production)}</span>
          </li>
        )}
      </ul>
    </div>
  );
}

function Card({ label, value, hint, children }) {
  return (
    <div className="bg-white p-5 md:p-6 rounded-lg shadow-sm border-x border-x-gray-100 border-y-4 border-y-emerald-500">
      <p className="text-sm font-medium text-gray-500 mb-2">{label}</p>
      <p className="text-2xl md:text-3xl font-bold text-gray-900">{value}</p>
      {hint && <p className="mt-1 text-xs text-gray-500">{hint}</p>}
      {children}
    </div>
  );
}

function CardLine({ label, value, strong = false }) {
  return (
    <p className={`mt-2 text-sm ${strong ? "font-semibold text-emerald-700" : "text-gray-600"}`}>
      {label}: <span className="whitespace-nowrap">{value}</span>
    </p>
  );
}

/**
 * Widok „Urządzenia” na Dashboardzie (ZP-82): wykres skumulowany z podziałem na kategorie, typy
 * albo urządzenia, drill-down przez kliknięcie, okruszki z przyciskiem „Wstecz” i ranking udziałów.
 * `source` pochodzi z deviceUsageSource, a `toolbar` to przełączniki z nagłówka wykresu Dashboardu.
 * `gridImport` ({ kwh, cost, tariff }) to pobór z sieci z widoku „Łącznie” dla tego samego okresu.
 */
function DeviceUsagePanel({ source, metric, resolution, toolbar, gridImport = null }) {
  const sourceKey = `${source.sourceId}|${source.meter ?? ""}`;
  const [drill, setDrill] = useState({ sourceKey, path: [] });
  const [deviceFilter, setDeviceFilter] = useState("all");
  const flexibleOnly = deviceFilter === "flexible";
  // Zmiana źródła danych wraca do widoku wszystkich urządzeń.
  const path = drill.sourceKey === sourceKey ? drill.path : [];
  const setPath = (nextPath) => setDrill({ sourceKey, path: nextPath });

  const { data, error, isLoading } = useDeviceUsage({
    sourceId: source.sourceId,
    params: {
      ...usageQuery(path, { flexibleOnly }),
      resolution,
      from: source.range.from,
      to: source.range.to,
      ...(source.meter ? { meter: source.meter } : {}),
    },
  });

  const series = buildSeries(data, path, { flexibleOnly });
  const production = productionSeries(data, path);
  const rows = data ? buildChartRows(data.periods, series, production, resolution) : [];
  const sum = totals(series);
  const shares = ranking(series);
  const crumbs = breadcrumbs(path);
  const rest = data?.rest_of_house;
  const selection = path.length > 0 ? `: ${crumbs.at(-1).label}` : "";
  // Przy fotowoltaice zużycie urządzeń obejmuje energię zużytą od razu na miejscu, a pobór z sieci nie.
  const withPv = Boolean(production) && !source.meter && Boolean(gridImport);
  const selfConsumption = withPv ? Math.max(sum.kwh - gridImport.kwh, 0) : null;
  const gridCost = gridImport?.cost != null && gridImport.tariff === data?.tariff.name ? gridImport.cost : null;

  const select = (item) => {
    if (item.clickable) setPath([...path, { key: item.key, label: item.label }]);
  };

  if (error) {
    return <div className="p-4 text-sm text-red-700 bg-red-50 rounded-lg">{error}</div>;
  }
  if (!data) {
    return (
      <div className="bg-white p-8 rounded-lg border border-gray-100 text-center text-gray-500">
        Ładowanie zużycia urządzeń...
      </div>
    );
  }

  return (
    <div className={`transition-opacity ${isLoading ? "opacity-60" : ""}`} aria-busy={isLoading}>
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4 md:gap-6 mb-8">
        <Card
          label={`${withPv ? "Koszt zużycia urządzeń bez fotowoltaiki" : "Koszt"}${selection} (taryfa ${data.tariff.name})`}
          value={formatPln(sum.cost)}
          hint={data.tariff.note}
        />
        <Card label={`Zużycie urządzeń${selection}`} value={formatKwh(sum.kwh)}>
          {withPv && (
            <CardLine
              label="Pobór z sieci"
              value={`${formatKwh(gridImport.kwh)}${gridCost != null ? ` (${formatPln(gridCost)})` : ""}`}
            />
          )}
        </Card>
        {withPv ? (
          <Card label="Autokonsumpcja fotowoltaiki" value={formatKwh(selfConsumption)}>
            <CardLine label="Produkcja fotowoltaiki" value={formatKwh(production.total_kwh)} />
            {gridCost != null && <CardLine label="Zaoszczędzone" value={formatPln(Math.max(sum.cost - gridCost, 0))} strong />}
          </Card>
        ) : source.meter && path.length === 0 && rest && !flexibleOnly ? (
          <Card
            label="Reszta domu"
            value={formatKwh(rest.total_kwh)}
            hint="Licznik minus urządzenia: zużycie, którego nie opisują pliki urządzeń."
          />
        ) : production ? (
          <Card label="Produkcja fotowoltaiki" value={formatKwh(production.total_kwh)} />
        ) : (
          <Card label={`Urządzenia${selection}`} value={sum.devices} />
        )}
      </div>

      <div className="bg-white p-4 md:p-6 rounded-lg shadow-sm border border-gray-100 mb-8">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between mb-4 gap-4">
          <h3 className="text-lg font-bold text-gray-900">
            {metric === "kwh" ? "Zużycie" : "Koszt"} według {LEVEL_NAMES[path.length]}
          </h3>
          {toolbar}
        </div>

        <div className="mb-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <nav aria-label="Poziom szczegółowości" className="flex flex-wrap items-center gap-2 text-sm">
            {path.length > 0 && (
              <button
                type="button"
                onClick={() => setPath(path.slice(0, -1))}
                className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md border border-gray-200 bg-white font-medium text-gray-700 hover:bg-gray-50"
              >
                <FiArrowLeft aria-hidden="true" /> Wstecz
              </button>
            )}
            <ol className="flex flex-wrap items-center gap-1">
              {crumbs.map((crumb, index) => {
                const isLast = index === crumbs.length - 1;
                return (
                  <li key={crumb.depth} className="flex items-center gap-1">
                    {index > 0 && <span className="text-gray-400" aria-hidden="true">/</span>}
                    {isLast ? (
                      <span className="font-semibold text-gray-900" aria-current="page">
                        {crumb.label}
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setPath(path.slice(0, crumb.depth))}
                        className="font-medium text-emerald-700 hover:underline"
                      >
                        {crumb.label}
                      </button>
                    )}
                  </li>
                );
              })}
            </ol>
          </nav>
          <SegmentedControl label="Urządzenia" options={DEVICE_FILTER_OPTIONS} value={deviceFilter} onChange={setDeviceFilter} />
        </div>

        {resolution !== "1d" && (
          <p className="mb-4 text-xs md:text-sm text-gray-500">Średni profil doby w wybranym okresie.</p>
        )}
        {source.meter && rest && rest.common_days.length === 0 && (
          <p className="mb-4 p-3 text-sm text-amber-800 bg-amber-50 rounded-lg">
            Plik licznika i pliki urządzeń nie mają wspólnych dni z odczytami, więc nie da się policzyć reszty domu.
          </p>
        )}
        {path.length === 0 && !flexibleOnly && rest?.exceeded_days.length > 0 && (
          <p className="mb-4 p-3 text-sm text-amber-800 bg-amber-50 rounded-lg">
            W {rest.exceeded_days.length} dniach urządzenia zużyły więcej niż pokazał licznik – sprawdź, czy pliki dotyczą tego samego domu.
          </p>
        )}
        {data.missing_price_slots > 0 && (
          <p className="mb-4 text-xs md:text-sm text-gray-500">
            Część kwadransów nie ma ceny w taryfie {data.tariff.name}, więc koszt jest niepełny.
          </p>
        )}

        {series.length === 0 && !production ? (
          <div className="h-[200px] flex items-center justify-center text-gray-400 text-center px-4 text-sm">
            {flexibleOnly ? "Brak urządzeń przesuwalnych w wybranym okresie." : "Brak zużycia urządzeń w wybranym okresie."}
          </div>
        ) : (
          <>
            <div className="h-[300px] md:h-[400px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={rows} stackOffset="sign" margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                  <XAxis dataKey="label" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: "#64748b" }} dy={10} minTickGap={20} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: "#64748b" }} />
                  <ReferenceLine y={0} stroke="#94a3b8" />
                  <Tooltip
                    content={<UsageTooltip series={series} resolution={resolution} />}
                    cursor={{ fill: "#f8fafc" }}
                  />
                  {series.map((item) => (
                    <Bar
                      key={item.key}
                      dataKey={`${item.key}__${metric}`}
                      name={item.label}
                      stackId="usage"
                      fill={item.color}
                      cursor={item.clickable ? "pointer" : undefined}
                      onClick={() => select(item)}
                      isAnimationActive={false}
                    />
                  ))}
                  {production && metric === "kwh" && (
                    <Bar dataKey={`${PRODUCTION_KEY}__kwh`} name="Produkcja fotowoltaiki" stackId="usage" fill={PRODUCTION_COLOR} isAnimationActive={false} />
                  )}
                </BarChart>
              </ResponsiveContainer>
            </div>

            <ul aria-label="Legenda" className="mt-4 flex flex-wrap gap-x-4 gap-y-2 text-sm">
              {series.map((item) => (
                <li key={item.key}>
                  <button
                    type="button"
                    onClick={() => select(item)}
                    disabled={!item.clickable}
                    className="flex items-center gap-2 text-gray-700 enabled:hover:text-gray-900 enabled:hover:underline disabled:cursor-default"
                  >
                    <span className="w-3 h-3 rounded-sm" style={{ backgroundColor: item.color }} />
                    {item.label}
                    <FlexibleMark item={item} />
                  </button>
                </li>
              ))}
              {production && (
                <li className="flex items-center gap-2 text-gray-700">
                  <span className="w-3 h-3 rounded-sm" style={{ backgroundColor: PRODUCTION_COLOR }} />
                  Produkcja fotowoltaiki{metric === "pln" && " (tylko w widoku kWh)"}
                </li>
              )}
            </ul>
            <p className="mt-2 flex items-center gap-1 text-xs text-gray-500">
              <FiRepeat className="text-emerald-600" aria-hidden="true" /> {FLEXIBLE_HINT.toLowerCase()} (np. pralka, zmywarka, ładowarka)
            </p>
          </>
        )}
      </div>

      {shares.length > 0 && (
        <div className="bg-white p-4 md:p-6 rounded-lg shadow-sm border border-gray-100">
          <h3 className="text-lg font-bold text-gray-900 mb-4">Udział w zużyciu i koszcie</h3>
          <ol className="divide-y divide-gray-100">
            {shares.map((item) => (
              <li key={item.key} className="py-2">
                <button
                  type="button"
                  onClick={() => select(item)}
                  disabled={!item.clickable}
                  className="w-full grid grid-cols-[auto_1fr] sm:grid-cols-[auto_1fr_auto_auto] items-center gap-x-3 gap-y-1 text-left text-sm disabled:cursor-default enabled:hover:bg-gray-50 rounded"
                >
                  <span className="w-3 h-3 rounded-sm" style={{ backgroundColor: item.color }} />
                  <span className="flex items-center gap-2 font-medium text-gray-900">
                    {item.label}
                    <FlexibleMark item={item} />
                  </span>
                  <span className="col-start-2 sm:col-start-auto text-gray-600 whitespace-nowrap">
                    {formatKwh(item.totalKwh)} ({formatShare(item.kwhShare)})
                  </span>
                  <span className="col-start-2 sm:col-start-auto text-gray-600 whitespace-nowrap">
                    {formatPln(item.totalCost)} ({formatShare(item.costShare)})
                  </span>
                </button>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

export default DeviceUsagePanel;
