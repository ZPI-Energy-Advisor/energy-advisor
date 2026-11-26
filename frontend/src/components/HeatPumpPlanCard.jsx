import { FiThermometer } from "react-icons/fi";
import { formatNumber } from "../utils/format";
import { describeHeatModel, formatDegrees, heatPumpSummary, heatingSystem, temperatureRange } from "../utils/heatPump";

function Figure({ label, value, hint }) {
  return (
    <div className="rounded-lg bg-gray-50 p-3">
      <p className="text-xs text-gray-500">{label}</p>
      <p className="mt-0.5 text-lg font-bold text-gray-900">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-gray-500">{hint}</p>}
    </div>
  );
}

// Pompa ciepła w planie (ZP-119): pogoda dnia planu, ile ciepła potrzebuje dom i ile prądu zużyje pompa.
function HeatPumpPlanCard({ pump }) {
  const plan = pump.plan_temperature;
  const short = pump.kwh < pump.target_kwh - 0.05;
  return (
    <section className="bg-white border border-gray-200 rounded-lg p-4 md:p-5 shadow-sm" aria-label={`Ogrzewanie: ${pump.device_name}`}>
      <h4 className="flex items-center gap-2 font-semibold text-gray-900">
        <FiThermometer aria-hidden="true" className="text-orange-500" /> Ogrzewanie: {pump.device_name}
      </h4>
      <p className="mt-1 text-sm text-gray-600">
        Prognoza na ten dzień: średnio {formatDegrees(plan.mean_c)} ({temperatureRange(plan)}). {heatPumpSummary(pump)}
      </p>
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Figure
          label="Ciepło dla domu"
          value={`${formatNumber(pump.heat_kwh, 0)} kWh`}
          hint={pump.hdd > 0 ? `${formatNumber(pump.hdd, 1)} stopniodni` : "bez ogrzewania, tylko woda"}
        />
        <Figure label="Z tego ciepła woda" value={`${formatNumber(pump.hot_water_heat_kwh, 1)} kWh`} />
        <Figure label="Sprawność pompy (COP)" value={formatNumber(pump.cop, 1)} hint={heatingSystem(pump.model)} />
        <Figure
          label="Prąd pompy"
          value={`${formatNumber(pump.kwh, 1)} kWh`}
          hint={`wtedy ${formatNumber(pump.reference_kwh, 1)} kWh`}
        />
      </div>
      {short && (
        <p className="mt-3 text-sm text-amber-800">
          Przy tej pogodzie dom potrzebuje ok. {formatNumber(pump.target_kwh, 1)} kWh prądu pompy, ale przy jej mocy zmieści
          się {formatNumber(pump.kwh, 1)} kWh.
        </p>
      )}
      <p className="mt-3 text-xs text-gray-500">{describeHeatModel(pump.model)}</p>
    </section>
  );
}

export default HeatPumpPlanCard;
