import { Link } from "react-router-dom";
import { FiSun } from "react-icons/fi";
import { formatDateTime, formatKwh, formatPercent, formatPln } from "../utils/format";
import { CARD, alertClass } from "./uiStyles";
import MoreInfo from "./MoreInfo";

const kwh = formatKwh;
const fetchedText = formatDateTime;

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
function ProfileLink({ children }) {
  return <Link to="/profile" className="font-medium text-emerald-700 underline hover:text-emerald-800">{children}</Link>;
}

function PvPlanCard({ pv, weather = null }) {
  const fetched = pv.weather_fetched_at ?? weather?.fetched_at;
  const { before, after } = pv;
  const settlement = pv.settlement === "net_billing" ? "do depozytu" : "w opuście";
  return (
    <section className={CARD} aria-label="Prąd z paneli">
      <h4 className="flex items-center gap-2 font-semibold text-gray-900">
        <FiSun aria-hidden="true" className="text-amber-500" /> Prąd z paneli
      </h4>
      <p className="mt-1 text-sm text-gray-600">
        {pv.uncertainty_source === "archive" ? (
          <>Z pogody z archiwum {kwh(pv.forecast_kwh)}. To pogoda, która naprawdę była, więc plan liczy na całą produkcję.</>
        ) : (
          <>
            Prognoza {kwh(pv.forecast_kwh)}, plan liczy na {kwh(pv.planned_kwh)} (o {formatPercent(pv.uncertainty)} mniej,{" "}
            {pv.uncertainty_source === "history" ? "tyle średnio myli się prognoza dla Twoich paneli" : "prognoza nie jest jeszcze dopasowana do Twoich paneli"}).
          </>
        )}
      </p>
      {fetched && (
        <p className="mt-1 text-xs text-gray-500">
          {weather?.past ? "Pogoda z archiwum" : "Prognoza pogody"} pobrana {fetchedText(fetched)}.
        </p>
      )}
      {pv.export_beats_grid && (
        <p className={`${alertClass("info")} mt-2`}>
          W godzinach ze słońcem prąd oddany do sieci jest wart więcej niż prąd z sieci, więc plan nie przesuwa urządzeń
          pod słońce: nadwyżkę lepiej oddać do depozytu, a urządzenia włączyć, gdy prąd z sieci jest tani.
        </p>
      )}
      {pv.estimated_installation && (
        <p className="mt-1 text-xs text-amber-800">
          Prognoza orientacyjna: panele w profilu są szacunkowe. <ProfileLink>Uzupełnij panele w profilu</ProfileLink>
        </p>
      )}
      {weather?.approximate_location && (
        <p className="mt-1 text-xs text-amber-800">
          Pogoda dla regionu: lokalizacja domu jest przybliżona. <ProfileLink>Podaj adres w profilu</ProfileLink>
        </p>
      )}
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
      <MoreInfo className="mt-3">
        <p>
          Operator rozlicza pobór i oddanie w każdej godzinie, więc urządzenie w godzinie z nadwyżką kosztuje tyle, ile
          dom traci na oddaniu prądu do sieci, a nie pełną cenę z sieci. Koszty planu powyżej już to uwzględniają.
        </p>
        <p>
          Panele najpierw pokrywają zwykłe zużycie reszty domu
          {pv.rest_source === "meter" ? " (z licznika, bez urządzeń z planu)" : " (urządzenia stałe z plików)"}, a plan
          liczy na prognozę pomniejszoną o jej średni błąd. Oddanie wyceniamy {pv.settlement === "net_billing"
            ? "po RCE × 1,23 do depozytu, który pokrywa tylko część rachunku za energię"
            : "opustem od ceny z sieci"}.
        </p>
        {pv.export_estimated && <p>Cen RCE na ten dzień jeszcze nie ma, więc wartość oddania to średnia z ostatnich dni.</p>}
        {pv.export_unpriced && <p>Nie ma cen RCE, więc oddania nie wyceniamy.</p>}
      </MoreInfo>
    </section>
  );
}

export default PvPlanCard;
