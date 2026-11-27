import { useState } from "react";
import { FiActivity } from "react-icons/fi";
import WeatherBadge from "../WeatherBadge";
import { formatKwh, formatNumber, formatPln, formatSimTime } from "../../utils/home";

const degrees = (value) => `${formatNumber(value, 1)}°C`;
const perKwh = (value) => `${formatNumber(value, 2)} zł/kWh`;

function Tile({ label, value, children = null, tone = "text-gray-900" }) {
  return (
    <div className="rounded-lg bg-gray-50 p-3 min-w-0">
      <p className="text-xs font-medium uppercase tracking-wide text-gray-500">{label}</p>
      <div className={`mt-1 text-lg font-bold tabular-nums ${tone}`}>{value}</div>
      {children && <div className="mt-0.5 text-xs text-gray-600">{children}</div>}
    </div>
  );
}

function Indoor({ pump }) {
  const [low, high] = pump.band;
  const outside = pump.temp_c < low - 0.05 || pump.temp_c > high + 0.05;
  return (
    <Tile label={`W domu · ${pump.device_name}`} value={degrees(pump.temp_c)} tone={outside ? "text-amber-700" : "text-gray-900"}>
      ustawiona {formatNumber(pump.set_c, 0)}°C, zakres {formatNumber(low, 0)}–{formatNumber(high, 0)}°C
      {pump.plan_c != null && <> · według planu {degrees(pump.plan_c)}</>} · o {formatSimTime(pump.at)}
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
        {nowWeather && (
          <Tile label="Na dworze" value={<WeatherBadge quarter={nowWeather} label="Pogoda teraz" />}>
            {live?.weather ? (live.weather.past ? "pogoda z archiwum z planu" : "prognoza z planu") : "pogoda doby symulacji"}
          </Tile>
        )}
        {live?.pv ? (
          <Tile label="Panele od początku planu" value={formatKwh(live.pv.production_kwh)} tone="text-emerald-700">
            w domu {formatKwh(live.pv.self_kwh)}, do sieci {formatKwh(live.pv.export_kwh)}
            {live.pv.export_pln != null && <> · oddanie {formatPln(live.pv.export_pln)}</>}
          </Tile>
        ) : !live && production > 0 ? (
          <Tile label="Panele w tej dobie" value={formatKwh(production)} tone="text-emerald-700" />
        ) : null}
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
