import { formatNumber } from "./format";
import { onDay } from "./dayPlan";

export const formatDegrees = (value) => `${formatNumber(Math.round(value) + 0, 0)}°C`;

export const temperatureRange = (temperature) =>
  Math.round(temperature.min_c) === Math.round(temperature.max_c)
    ? formatDegrees(temperature.mean_c)
    : `od ${formatNumber(Math.round(temperature.min_c) + 0, 0)} do ${formatDegrees(temperature.max_c)}`;

const kwh = (value, digits = 1) => `${formatNumber(value, digits)} kWh`;

const days = (count) => (count === 1 ? "1 dnia" : `${count} dni`);

export const describeHeatModel = (model) => {
  const perDegreeDay = `ok. ${kwh(model.heat_per_hdd)} ciepła na stopniodzień`;
  if (model.source === "history") {
    const error = model.mape != null ? `; dobowe zużycie myli średnio o ${formatNumber(model.mape * 100, 0)}%` : "";
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

export const heatPumpSummary = (pump) =>
  `${capitalize(onDay(pump.reference_day))}, z którego bierzemy godziny grzania, było średnio `
  + `${formatDegrees(pump.reference_temperature.mean_c)} i pompa zużyła ${kwh(pump.reference_kwh)}.`;

export const heatingSystem = (model) => (model.floor_heating ? "ogrzewanie podłogowe" : "grzejniki");
