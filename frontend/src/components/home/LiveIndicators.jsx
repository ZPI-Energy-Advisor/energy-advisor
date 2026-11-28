import { LuDroplet, LuHouse, LuPiggyBank, LuThermometer, LuZap } from "react-icons/lu";
import { TbSolarPanel2 } from "react-icons/tb";
import { priceNow, waterTemperaturesNow } from "../../utils/houseView";
import { formatDegrees, formatKwh, formatPln, formatPrice } from "../../utils/format";


function Item({ icon: Icon, iconClass, label, value, note = null, children = null }) {
  return (
    <li className="flex items-center gap-1.5" aria-label={`${label}: ${value}${note ? `, ${note}` : ""}`}>
      <Icon className={iconClass} aria-hidden="true" />
      <span className="font-semibold tabular-nums text-slate-900">{value}</span>
      {note && <span className="text-xs text-slate-500">{note}</span>}
      {children}
    </li>
  );
}

/**
 * Wskaźniki domu zmieniające się z zegarem symulacji (ZP-110, ZP-153), zwięźle, bez wykresów: w rogu przekroju
 * domu, a na telefonie i w widoku listy jako pasek. Woda i cena z migawki przebiegu planu, temperatura w domu,
 * panele i oszczędność z sekcji `live` przebiegu, pogoda z planu albo doby symulacji. Bez danych wskaźnika nie ma.
 *
 * Oszczędność do teraz rośnie w miarę pracy urządzeń (każde dokłada swoją oszczędność z planu w proporcji do
 * zużytej już energii), obok oszczędności planu na całą dobę; nie spada poniżej zera od przesunięcia pracy w czasie.
 */
// `side`: na przekroju domu wskaźniki dzielą się na dwa rogi nad dachem, żeby nie zasłaniać pokoi: „home” (w domu,
// woda, cena) po lewej i „outside” (pogoda, panele, oszczędność) po prawej; „all” to pasek na telefonie i nad listą.
const PLACES = {
  all: "flex flex-wrap gap-x-4 gap-y-1.5 rounded-xl bg-slate-50 px-3 py-2 text-sm",
  home: "absolute left-0 top-2 z-[1] space-y-1.5 rounded-xl bg-white/90 px-3 py-2 text-sm shadow-sm ring-1 ring-slate-900/5",
  outside: "absolute right-0 top-2 z-[1] space-y-1.5 rounded-xl bg-white/90 px-3 py-2 text-sm shadow-sm ring-1 ring-slate-900/5",
};
const LABELS = { all: "Wskaźniki domu", home: "Wskaźniki: w domu", outside: "Wskaźniki: na zewnątrz i wynik planu" };

function LiveIndicators({ run = null, live = null, weather = null, simTime, side = "all" }) {
  const home = side !== "outside";
  const away = side !== "home";
  const water = home ? waterTemperaturesNow(run, simTime) : [];
  const price = home ? priceNow(run, simTime) : null;
  const indoor = home ? live?.indoor ?? [] : [];
  const outside = away ? live?.weather ?? weather : null;
  const pv = away ? live?.pv : null;
  const saving = away ? live?.saving : null;
  if (!water.length && !price && !indoor.length && !outside && !pv && !saving) return null;

  return (
    <ul className={PLACES[side]} aria-label={LABELS[side]}>
      {indoor.map((pump) => (
        <Item
          key={pump.device_id}
          icon={LuHouse}
          iconClass="text-orange-500"
          label={`W domu (${pump.device_name})`}
          value={formatDegrees(pump.temp_c, 1)}
          note={indoor.length > 1 ? pump.device_name : "w domu"}
        />
      ))}
      {outside && outside.temperature_c != null && (
        // Stały podpis zamiast opisu chmur: zmieniający się tekst („bezchmurnie”, „częściowe zachmurzenie”)
        // zmieniał szerokość ramki w trakcie symulacji.
        <Item icon={LuThermometer} iconClass="text-sky-600" label="Na dworze" value={formatDegrees(outside.temperature_c)} note="na dworze" />
      )}
      {water.map((heater) => (
        <Item
          key={heater.deviceId}
          icon={LuDroplet}
          iconClass="text-sky-600"
          label={`Temperatura wody (${heater.name}, według planu)`}
          value={formatDegrees(heater.tempC)}
          note={water.length > 1 ? heater.name : null}
        />
      ))}
      {price && (
        // Bez „tanio / średnio / drogo”: zmieniający się dopisek zmieniał szerokość ramki (poziom cen widać na pasku
        // czasu nad domem); zostaje tylko dopisek o cenie przybliżonej.
        <Item
          icon={LuZap}
          iconClass="text-amber-500"
          label="Cena prądu teraz"
          value={formatPrice(price.price)}
          note={price.approximate ? "przybliżona" : null}
        />
      )}
      {pv && (
        <Item icon={TbSolarPanel2} iconClass="text-amber-500" label="Z paneli od początku planu" value={formatKwh(pv.production_kwh)} note="z paneli" />
      )}
      {saving && (
        <Item
          icon={LuPiggyBank}
          iconClass="text-emerald-600"
          label="Oszczędność do teraz"
          value={formatPln(saving.progress_saving)}
          note={saving.planned_saving != null ? `z ${formatPln(saving.planned_saving)} planu` : null}
        />
      )}
    </ul>
  );
}

export default LiveIndicators;
