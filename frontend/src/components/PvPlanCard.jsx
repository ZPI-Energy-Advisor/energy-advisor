import { FiSun } from "react-icons/fi";
import { formatNumber } from "../utils/format";
import { formatPln } from "../utils/schedule";

const kwh = (value) => `${formatNumber(value, 1)} kWh`;

function Row({ label, before, after }) {
  return (
    <tr className="border-b border-gray-50 last:border-0">
      <td className="py-1.5 pr-3 text-gray-600">{label}</td>
      <td className="py-1.5 px-3 text-right whitespace-nowrap">{before}</td>
      <td className="py-1.5 pl-3 text-right font-medium text-gray-900 whitespace-nowrap">{after}</td>
    </tr>
  );
}

// Prąd z paneli w planie (ZP-121): prognoza, na ile plan liczy, i bilans paneli bez planu i według planu.
function PvPlanCard({ pv }) {
  const { before, after } = pv;
  const settlement = pv.settlement === "net_billing" ? "do depozytu" : "w opuście";
  return (
    <section className="bg-white border border-gray-200 rounded-lg p-4 md:p-5 shadow-sm" aria-label="Prąd z paneli">
      <h4 className="flex items-center gap-2 font-semibold text-gray-900">
        <FiSun aria-hidden="true" className="text-amber-500" /> Prąd z paneli
      </h4>
      <p className="mt-1 text-sm text-gray-600">
        Prognoza {kwh(pv.forecast_kwh)}, plan liczy na {kwh(pv.planned_kwh)} (o {formatNumber(pv.uncertainty * 100, 0)}% mniej,{" "}
        {pv.uncertainty_source === "history" ? "tyle średnio myli się prognoza dla Twoich paneli" : "prognoza nie jest jeszcze dopasowana do Twoich paneli"}).
      </p>
      {before && after && (
        <table className="mt-3 w-full text-sm">
          <thead className="text-xs text-gray-500">
            <tr>
              <th className="pb-1 pr-3 text-left font-medium" />
              <th className="pb-1 px-3 text-right font-medium">Bez planu</th>
              <th className="pb-1 pl-3 text-right font-medium">Według planu</th>
            </tr>
          </thead>
          <tbody>
            <Row label="Urządzenia z planu biorą z paneli" before={kwh(before.plan_from_pv_kwh)} after={kwh(after.plan_from_pv_kwh)} />
            <Row label="Dom zużywa sam" before={kwh(before.self_kwh)} after={kwh(after.self_kwh)} />
            <Row label="Do sieci" before={kwh(before.export_kwh)} after={kwh(after.export_kwh)} />
            <Row label={`Wartość oddania ${settlement}`} before={formatPln(before.export_pln)} after={formatPln(after.export_pln)} />
          </tbody>
        </table>
      )}
      <p className="mt-3 text-xs text-gray-500">
        Operator rozlicza pobór i oddanie w każdej godzinie, więc urządzenie w godzinie z nadwyżką kosztuje tyle, ile dom
        traci na oddaniu prądu do sieci, a nie pełną cenę z sieci. Koszty planu powyżej już to uwzględniają.
        {pv.export_estimated && " Cen RCE na ten dzień jeszcze nie ma, więc wartość oddania to średnia z ostatnich dni."}
        {pv.export_unpriced && " Nie ma cen RCE, więc oddania nie wyceniamy."}
      </p>
    </section>
  );
}

export default PvPlanCard;
