import { formatDegrees, formatKwh, formatNumber, formatPercent } from "./format";
import { onDay } from "./dayPlan";

export { formatDegrees };

// Zakres doby w nawiasie; bez nawiasu, gdy najniższa i najwyższa są takie same (wtedy wystarczy średnia).
export const temperatureRange = (temperature) =>
  Math.round(temperature.min_c) === Math.round(temperature.max_c)
    ? ""
    : ` (od ${formatNumber(Math.round(temperature.min_c), 0)} do ${formatDegrees(temperature.max_c)})`;

const kwh = formatKwh;

const days = (count) => (count === 1 ? "1 dnia" : `${count} dni`);

export const describeHeatModel = (model) => {
  const perDegreeDay = `ok. ${kwh(model.heat_per_hdd)} ciepła na stopniodzień`;
  if (model.source === "history") {
    const error = model.mape != null ? `; dobowe zużycie myli średnio o ${formatPercent(model.mape)}` : "";
    return `Dopasowane do zużycia pompy z Twoich plików (${days(model.days)}, w tym ${model.heating_days} z ogrzewaniem): `
      + `dom potrzebuje ${perDegreeDay}${error}.`;
  }
  if (model.source === "mixed") {
    return `W plikach jest za mało zimnych dni, więc ogrzewanie liczymy z profilu (${perDegreeDay}), `
      + "a ciepłą wodę z zużycia pompy w plikach.";
  }
  return `Liczone z profilu (rok budowy i metraż): ${perDegreeDay}. Wgraj plik urządzeń z pompą z chłodnych dni, `
    + "żeby dopasować to do Twojego domu.";
};

const capitalize = (text) => text.charAt(0).toUpperCase() + text.slice(1);

export const heatPumpReference = (pump) =>
  pump.reference_temperature
    ? `${capitalize(onDay(pump.reference_day))}, z którego bierzemy godziny grzania, było średnio `
      + `${formatDegrees(pump.reference_temperature.mean_c)} i pompa zużyła ${kwh(pump.reference_kwh)}.`
    : "";

// Dom jako magazyn ciepła: jak szybko stygnie bez grzania (plan pilnujący temperatury w domu).
export const describeCooling = (pump) =>
  `Bez grzania dom stygnie przy tej pogodzie o ok. ${formatDegrees(pump.cooling_per_hour, 1)} na godzinę, `
  + "więc plan może grzeć na zapas w tanich godzinach i przerwać grzanie, kiedy prąd jest drogi.";

// Doba planu z przeszłości (plan demo) ma pogodę z archiwum, a nie z prognozy.
export const weatherOfPlanDay = (pump) => {
  const plan = pump.plan_temperature;
  const label = plan.source === "archive" ? "Pogoda z archiwum" : "Prognoza na ten dzień";
  return `${label}: średnio ${formatDegrees(plan.mean_c)}${temperatureRange(plan)}.`;
};

const SAME_DEGREES = 0.5;
const SAME_KWH = 0.1;

// Wniosek karty w planie pilnującym temperatury w domu: pogoda, zakres w domu i ile prądu.
const indoorHeadline = (pump, planDate) => {
  const day = planDate ? capitalize(onDay(planDate)) : "W dniu planu";
  const [low, high] = pump.band;
  return `${day} średnio ${formatDegrees(pump.plan_temperature.mean_c)}. Plan trzyma w domu `
    + `${formatNumber(low, 0)}–${formatDegrees(high)} i zużyje ok. ${kwh(pump.kwh)} prądu, grzejąc głównie w tańszych godzinach.`;
};

// Wniosek karty: dzień planu wobec dnia referencyjnego i ile przez to prądu pompy.
export const heatPumpHeadline = (pump, planDate) => {
  if (pump.mode === "indoor") return indoorHeadline(pump, planDate);
  const plan = pump.plan_temperature.mean_c;
  const reference = pump.reference_temperature.mean_c;
  const day = planDate ? capitalize(onDay(planDate)) : "W dniu planu";
  const comparison = plan < reference - SAME_DEGREES ? "zimniej" : plan > reference + SAME_DEGREES ? "cieplej" : "podobnie";
  const temperatures = `(${formatDegrees(plan)} zamiast ${formatDegrees(reference)} ${onDay(pump.reference_day)})`;
  const change = pump.kwh - pump.reference_kwh;
  const amount = Math.abs(change) < SAME_KWH
    ? "tyle samo co wtedy"
    : `o ${kwh(Math.abs(change))} ${change > 0 ? "więcej" : "mniej"}`;
  const indoor = pump.indoor_c != null && pump.indoor_c !== 21 ? ` przy ${formatDegrees(pump.indoor_c)} w domu` : "";
  return `${day} ${comparison} ${temperatures}, więc pompa zużyje ok. ${kwh(pump.kwh)} prądu${indoor}, ${amount}.`;
};

// Ciepła woda z pompy planowana osobno (godziny „ciepła woda gotowa na”).
export const heatPumpWater = (pump) => {
  if (!pump.water) return null;
  const times = pump.water.ready_times;
  const ready = times.length === 1 ? times[0] : `${times.slice(0, -1).join(", ")} i ${times[times.length - 1]}`;
  return `Ciepła woda w zasobniku ${pump.water.tank_liters} l będzie gotowa na ${ready}: pompa nagrzeje ją, kiedy prąd `
    + `jest tani (${kwh(pump.water.kwh)} prądu, wliczone wyżej).`;
};

// Dopasowanie z plików słabo tłumaczy zużycie temperaturą (np. dane, w których pompa nie zależy od pogody).
const POOR_FIT_MAPE = 0.2;
export const isPoorFit = (model) => model.source === "history" && model.mape != null && model.mape > POOR_FIT_MAPE;

export const heatingSystem = (model) => (model.floor_heating ? "ogrzewanie podłogowe" : "grzejniki");
