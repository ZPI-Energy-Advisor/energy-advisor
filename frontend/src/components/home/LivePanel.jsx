import { useState } from "react";
import { FiActivity } from "react-icons/fi";
import {
  Bar, BarChart, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import WeatherBadge from "../WeatherBadge";
import { formatKwh, formatNumber, formatPln, formatSimTime } from "../../utils/home";

const degrees = (value) => `${formatNumber(value, 1)}°C`;
const perKwh = (value) => `${formatNumber(value, 2)} zł/kWh`;
const PLAN_COLOR = "#9ca3af";
const SIM_COLOR = "#f97316";
const PV_PLAN_COLOR = "#fde68a";
const PV_COLOR = "#f59e0b";

function Tile({ label, value, children = null, chart = null, tone = "text-gray-900" }) {
  return (
    <div className="rounded-lg bg-gray-50 p-3 min-w-0">
      <p className="text-xs font-medium uppercase tracking-wide text-gray-500">{label}</p>
      <div className={`mt-1 text-lg font-bold tabular-nums ${tone}`}>{value}</div>
      {children && <div className="mt-0.5 text-xs text-gray-600">{children}</div>}
      {chart}
    </div>
  );
}

function ChartTip({ active, payload, label, unit, names }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded border border-gray-200 bg-white px-2 py-1 text-xs shadow-sm">
      <p className="font-medium text-gray-700">{label}</p>
      {payload.filter((entry) => entry.value != null).map((entry) => (
        <p key={entry.dataKey} style={{ color: entry.color }}>
          {names[entry.dataKey]}: {formatNumber(entry.value, unit === "°C" ? 1 : 2)} {unit}
        </p>
      ))}
    </div>
  );
}

function IndoorChart({ pump }) {
  const data = pump.points.map((point) => ({ time: formatSimTime(point.start), plan: point.plan_c, sim: point.temp_c }));
  const values = data.flatMap((point) => [point.plan, point.sim]).filter((value) => value != null);
  const [low, high] = pump.band;
  const domain = [Math.floor(Math.min(low, ...values) - 0.5), Math.ceil(Math.max(high, ...values) + 0.5)];
  return (
    <div className="mt-2 h-24" aria-label={`Temperatura w domu w dobie: ${pump.device_name}`}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
          <ReferenceArea y1={low} y2={high} fill="#d1fae5" fillOpacity={0.6} />
          <XAxis dataKey="time" interval={23} tick={{ fontSize: 10 }} tickLine={false} />
          <YAxis domain={domain} tick={{ fontSize: 10 }} tickLine={false} width={28} tickFormatter={(value) => formatNumber(value, 0)} />
          <Tooltip content={<ChartTip unit="°C" names={{ plan: "według planu", sim: "w symulacji" }} />} />
          <Line dataKey="plan" stroke={PLAN_COLOR} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
          <Line dataKey="sim" stroke={SIM_COLOR} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function PvChart({ hours }) {
  const data = hours.map((hour) => ({ time: formatSimTime(hour.start), plan: hour.planned_kwh, actual: hour.actual_kwh }));
  return (
    <div className="mt-2 h-24" aria-label="Produkcja paneli w godzinach: plan i symulacja">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }} barGap={0}>
          <XAxis dataKey="time" tick={{ fontSize: 10 }} tickLine={false} interval="preserveStartEnd" />
          <YAxis tick={{ fontSize: 10 }} tickLine={false} width={28} tickFormatter={(value) => formatNumber(value, 1)} />
          <Tooltip content={<ChartTip unit="kWh" names={{ plan: "plan", actual: "w symulacji" }} />} />
          <Bar dataKey="plan" fill={PV_PLAN_COLOR} isAnimationActive={false} />
          <Bar dataKey="actual" fill={PV_COLOR} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function Legend({ items }) {
  return (
    <p className="mt-1 flex flex-wrap gap-x-3 text-[11px] text-gray-500">
      {items.map(([color, label, dashed]) => (
        <span key={label} className="inline-flex items-center gap-1">
          <i className={`inline-block h-0.5 w-3 ${dashed ? "border-t border-dashed" : ""}`}
            style={dashed ? { borderColor: color } : { backgroundColor: color, height: 6 }} />
          {label}
        </span>
      ))}
    </p>
  );
}

function Indoor({ pump }) {
  const [low, high] = pump.band;
  const outside = pump.temp_c < low - 0.05 || pump.temp_c > high + 0.05;
  return (
    <Tile
      label={`W domu · ${pump.device_name}`}
      value={degrees(pump.temp_c)}
      tone={outside ? "text-amber-700" : "text-gray-900"}
      chart={pump.points?.length > 0 && (
        <>
          <IndoorChart pump={pump} />
          <Legend items={[[SIM_COLOR, "w symulacji"], [PLAN_COLOR, "według planu", true], ["#a7f3d0", "zakres komfortu"]]} />
        </>
      )}
    >
      ustawiona {formatNumber(pump.set_c, 0)}°C, zakres {formatNumber(low, 0)}–{formatNumber(high, 0)}°C
      {pump.plan_c != null && <> · według planu {degrees(pump.plan_c)}</>} · o {formatSimTime(pump.at)}
    </Tile>
  );
}

function Panels({ pv }) {
  return (
    <Tile
      label="Panele od początku planu"
      value={formatKwh(pv.production_kwh)}
      tone="text-emerald-700"
      chart={pv.hours?.length > 0 && (
        <>
          <PvChart hours={pv.hours} />
          <Legend items={[[PV_COLOR, "w symulacji"], [PV_PLAN_COLOR, "plan"]]} />
        </>
      )}
    >
      {pv.planned_kwh != null && <>plan na dobę {formatKwh(pv.planned_kwh)} · </>}
      w domu {formatKwh(pv.self_kwh)}, do sieci {formatKwh(pv.export_kwh)}
      {pv.export_pln != null && <> · oddanie {formatPln(pv.export_pln)}</>}
      <span className="mt-0.5 block text-gray-500">
        W symulacji urządzenia stałe są wyłączone, dopóki ich nie włączysz, więc dom może oddawać więcej niż w planie.
      </span>
    </Tile>
  );
}

function Saving({ saving }) {
  const tone = saving.saving > 0 ? "text-emerald-700" : saving.saving < 0 ? "text-amber-700" : "text-gray-900";
  return (
    <Tile
      label="Oszczędność do teraz"
      value={<>{formatPln(saving.saving)}{saving.saving_percent != null && ` (${formatNumber(saving.saving_percent, 1)}%)`}</>}
      tone={tone}
    >
      bez planu {formatPln(saving.cost_before)}, z planem {formatPln(saving.cost_after)}
      {saving.excluded.length > 0 && (
        <> · bez {saving.excluded.map((device) => device.device_name).join(", ")} (odchylenie od planu)</>
      )}
      {saving.planned_saving != null && (
        <span className="mt-0.5 block text-gray-500">
          Plan na całą dobę: {formatPln(saving.planned_saving)}. Plan przesuwa pracę w czasie, więc w trakcie doby ta
          kwota może być większa albo mniejsza.
        </span>
      )}
    </Tile>
  );
}

const startsOpen = () => {
  try {
    return window.matchMedia?.("(min-width: 640px)")?.matches ?? true;
  } catch {
    return true;
  }
};

// Statystyki na żywo nad przekrojem domu (ZP-153): z przebiegu planu (`live` z GET /home/plan-runs/latest),
// a bez przebiegu tylko pogoda i produkcja PV z bilansu domu. Na telefonie panel startuje zwinięty.
function LivePanel({ live = null, weather = null, today = null }) {
  const [open, setOpen] = useState(startsOpen);
  const nowWeather = live?.weather ?? weather;
  const production = today?.production_kwh;
  return (
    <details
      className="bg-white border border-gray-200 rounded-lg shadow-sm"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      aria-label="Na żywo"
    >
      <summary className="flex cursor-pointer items-center gap-2 px-4 py-3 font-semibold text-gray-900">
        <FiActivity aria-hidden="true" className="text-emerald-600" /> Na żywo
        {live && <span className="ml-auto text-xs font-normal text-gray-500">do {formatSimTime(live.until)}</span>}
      </summary>
      <div className="grid grid-cols-1 gap-3 px-4 pb-4 sm:grid-cols-2 lg:grid-cols-3">
        {(live?.indoor ?? []).map((pump) => <Indoor key={pump.device_id} pump={pump} />)}
        {live?.pv ? (
          <Panels pv={live.pv} />
        ) : !live && production > 0 ? (
          <Tile label="Panele w tej dobie" value={formatKwh(production)} tone="text-emerald-700" />
        ) : null}
        {nowWeather && (
          <Tile label="Na dworze" value={<WeatherBadge quarter={nowWeather} label="Pogoda teraz" />}>
            {live?.weather ? (live.weather.past ? "pogoda z archiwum z planu" : "prognoza z planu") : "pogoda doby symulacji"}
          </Tile>
        )}
        {live?.price_now != null && (
          <Tile label="Cena teraz" value={perKwh(live.price_now)}>
            {live.export_price_now != null ? <>oddanie {perKwh(live.export_price_now)}</> : "z sieci, w taryfie z planu"}
          </Tile>
        )}
        {live?.saving && <Saving saving={live.saving} />}
        {!live && (
          <p className="text-sm text-gray-600 sm:col-span-2 lg:col-span-3">
            Uruchom plan na stronie „Plan na jutro”, żeby zobaczyć oszczędność, temperaturę w domu i ceny na żywo.
          </p>
        )}
      </div>
    </details>
  );
}

export default LivePanel;
