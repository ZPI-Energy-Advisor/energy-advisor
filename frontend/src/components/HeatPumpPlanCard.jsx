import { FiThermometer } from "react-icons/fi";
import { formatNumber } from "../utils/format";
import { formatPln } from "../utils/schedule";
import {
  describeCooling,
  describeHeatModel,
  heatPumpHeadline,
  heatPumpReference,
  heatPumpWater,
  heatingSystem,
  isPoorFit,
  weatherOfPlanDay,
} from "../utils/heatPump";

function Figure({ label, value, hint }) {
  return (
    <div className="rounded-lg bg-gray-50 p-3">
      <p className="text-xs text-gray-500">{label}</p>
      <p className="mt-0.5 text-lg font-bold text-gray-900">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-gray-500">{hint}</p>}
    </div>
  );
}

// Pompa ciepła w planie (ZP-119): najpierw wniosek (ile prądu przy pogodzie dnia planu), a szczegóły modelu
// (ciepło, woda, COP, stopniodni, trafność) zwinięte pod „Jak to liczymy”.
function HeatPumpPlanCard({ pump, planDate }) {
  const short = pump.kwh < pump.target_kwh - 0.05;
  const cold = pump.shortfall_reason ?? (pump.shortfall_reason === undefined && pump.shortfall > 0.3 ? "power" : null);
  const water = heatPumpWater(pump);
  return (
    <section className="bg-white border border-gray-200 rounded-lg p-4 md:p-5 shadow-sm" aria-label={`Ogrzewanie: ${pump.device_name}`}>
      <h4 className="flex items-center gap-2 font-semibold text-gray-900">
        <FiThermometer aria-hidden="true" className="text-orange-500" /> Ogrzewanie: {pump.device_name}
      </h4>
      <p className="mt-1 text-gray-900">{heatPumpHeadline(pump, planDate)}</p>
      {water && <p className="mt-1 text-sm text-gray-600">{water}</p>}
      {pump.mode !== "indoor" && short && (
        <p className="mt-2 text-sm text-amber-800">
          Przy tej pogodzie dom potrzebuje ok. {formatNumber(pump.target_kwh, 1)} kWh prądu pompy, ale przy jej mocy zmieści
          się {formatNumber(pump.kwh, 1)} kWh. W domu może być trochę chłodniej.
        </p>
      )}
      {pump.mode === "indoor" && cold && (
        <p className="mt-2 text-sm text-amber-800">
          {cold === "grid"
            ? "Limit mocy przyłącza nie zostawia pompie miejsca, żeby utrzymać"
            : "Przy tej pogodzie pompa nie utrzyma"}{" "}
          w domu {formatNumber(pump.band[0], 0)}°C (zabraknie ok. {formatNumber(pump.shortfall, 1)}°C). W domu może być
          chłodniej.
        </p>
      )}
      {pump.water?.shortfall > 0.5 && (
        <p className="mt-2 text-sm text-amber-800">
          Pompa nie zdąży nagrzać tyle wody, ile zwykle zużywacie. Pomoże większy zasobnik albo godziny dalej od siebie.
        </p>
      )}
      {isPoorFit(pump.model) && (
        <p className="mt-2 text-sm text-amber-800">
          Zużycie pompy w Twoich plikach słabo zależy od temperatury (dobowe zużycie myli średnio o{" "}
          {formatNumber(pump.model.mape * 100, 0)}%), więc ta prognoza jest orientacyjna.
        </p>
      )}
      <details className="mt-3 group">
        <summary className="cursor-pointer text-sm font-medium text-emerald-700 hover:text-emerald-800">Jak to liczymy</summary>
        <p className="mt-2 text-sm text-gray-600">
          {weatherOfPlanDay(pump)} {pump.mode === "indoor" ? describeCooling(pump) : heatPumpReference(pump)}
        </p>
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <Figure
            label="Ciepło dla domu"
            value={`${formatNumber(pump.heat_kwh, 0)} kWh`}
            hint={pump.hdd > 0 ? `${formatNumber(pump.hdd, 1)} stopniodni` : "bez ogrzewania, tylko woda"}
          />
          {pump.hot_water_heat_kwh > 0 && (
            <Figure label="Z tego ciepła woda" value={`${formatNumber(pump.hot_water_heat_kwh, 1)} kWh`} />
          )}
          <Figure label="Sprawność pompy (COP)" value={formatNumber(pump.cop, 1)} hint={heatingSystem(pump.model)} />
          <Figure
            label="Prąd pompy"
            value={`${formatNumber(pump.kwh, 1)} kWh`}
            hint={pump.mode === "indoor" ? null : `wtedy ${formatNumber(pump.reference_kwh, 1)} kWh`}
          />
          {pump.mode === "indoor" && pump.cost_pln != null && (
            <Figure
              label="Koszt ogrzewania"
              value={formatPln(pump.cost_pln)}
              hint={`ze stałą temperaturą ${formatPln(pump.thermostat_cost_pln)}`}
            />
          )}
        </div>
        <p className="mt-3 text-xs text-gray-500">
          Stopniodni mówią, jak zimny jest dzień: 18°C minus średnia temperatura doby (przy 21°C w domu). COP to ile
          kWh ciepła pompa robi z 1 kWh prądu; im zimniej na dworze, tym mniej.
        </p>
        <p className="mt-2 text-xs text-gray-500">{describeHeatModel(pump.model)}</p>
      </details>
    </section>
  );
}

export default HeatPumpPlanCard;
