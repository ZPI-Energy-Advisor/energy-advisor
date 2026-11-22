// Logika formularza profilu: puste dane, liczby z przecinkiem, walidacja pól i błędy z backendu.

export const MAX_BUILD_YEAR = 2027;
export const MIN_BUILD_YEAR = 1850;

export const FIELD_LABELS = {
  "base_info.type_of_property": "Typ nieruchomości",
  "base_info.year_of_construction": "Rok budowy",
  "base_info.heating_area_m2": "Powierzchnia ogrzewana",
  "base_info.number_of_residents": "Liczba mieszkańców",
  "base_info.town": "Miejscowość",
  "base_info.postal_code": "Kod pocztowy",
  "base_info.distribution_operator": "Operator dystrybucyjny",
  "base_info.phase_type": "Liczba faz",
  "base_info.contracted_power_kw": "Moc umowna",
  "base_info.billing_cycle": "Cykl rozliczeniowy",
  "base_info.billing_period_start_date": "Początek okresu rozliczeniowego",
  "consumption_and_tariff.tariff_type": "Grupa taryfowa",
  "consumption_and_tariff.dynamic_price": "Umowa z ceną dynamiczną",
  "pv_config.mode": "Fotowoltaika",
  "pv_config.type_of_price": "Wycena energii oddanej",
  "pv_config.installation": "Instalacja PV",
  "pv_config.panel_power_w": "Moc jednego panelu",
  "pv_config.inverter_power_kw": "Moc falownika",
  "base_info.location": "Lokalizacja domu",
};

const ARRAY_FIELD_LABELS = { power_kwp: "moc", panel_count: "liczba paneli", tilt: "nachylenie", azimuth: "kierunek" };

export function fieldLabel(key) {
  const match = /^pv_config\.arrays\.(\d+)\.(\w+)$/.exec(key);
  if (match) return `Grupa paneli ${Number(match[1]) + 1}: ${ARRAY_FIELD_LABELS[match[2]] ?? match[2]}`;
  return FIELD_LABELS[key] ?? key;
}

export const MAX_PV_KWP = 50;
export const MAX_PV_ARRAYS = 4;
export const DEFAULT_PANEL_W = 430;
export const TYPICAL_INSTALLATION = { power_kwp: 6, azimuth: 0, tilt: 35 };
export const DIRECTIONS = [
  { value: 0, label: "Południe" },
  { value: -45, label: "Południowy wschód" },
  { value: 45, label: "Południowy zachód" },
  { value: -90, label: "Wschód" },
  { value: 90, label: "Zachód" },
  { value: -135, label: "Północny wschód" },
  { value: 135, label: "Północny zachód" },
  { value: 180, label: "Północ" },
];
export const POLAND_BOUNDS = { minLatitude: 49, maxLatitude: 55, minLongitude: 14, maxLongitude: 24.5 };

const decimalText = (value) => (value === null || value === undefined ? "" : String(value).replace(".", ","));

let arrayIds = 0;
const nextArrayId = () => {
  arrayIds += 1;
  return `array-${arrayIds}`;
};

export const createArray = (values = {}) => ({
  id: nextArrayId(),
  power_kwp: decimalText(values.power_kwp),
  panel_count: values.panel_count ? String(values.panel_count) : "",
  azimuth: DIRECTIONS.some((direction) => direction.value === values.azimuth) ? values.azimuth : 0,
  tilt: decimalText(values.tilt ?? TYPICAL_INSTALLATION.tilt),
});

export const typicalInstallation = () => ({
  estimated: true,
  input: "power",
  panel_power_w: String(DEFAULT_PANEL_W),
  inverter_power_kw: "",
  arrays: [createArray(TYPICAL_INSTALLATION)],
});

function installationFromSaved(pv) {
  const saved = pv?.installation;
  if (!saved?.arrays?.length) {
    if (pv?.power_of_pv_kwp) return { ...typicalInstallation(), estimated: false, arrays: [createArray({ power_kwp: pv.power_of_pv_kwp })] };
    return typicalInstallation();
  }
  return {
    estimated: Boolean(saved.estimated),
    input: saved.panel_power_w ? "panels" : "power",
    panel_power_w: String(saved.panel_power_w ?? DEFAULT_PANEL_W),
    inverter_power_kw: decimalText(saved.inverter_power_kw),
    arrays: saved.arrays.map(createArray),
  };
}

export const addressKey = (base) => `${base.postal_code} ${String(base.town ?? "").trim()}`;

export const plainText = (text) =>
  String(text ?? "").trim().toLocaleLowerCase("pl-PL").replaceAll("ł", "l").normalize("NFKD").replace(/[\u0300-\u036f]/g, "");

export function profileSnapshot(profile) {
  const payload = toPayload(profile);
  const location = payload.base_info.location;
  const manual = location?.source === "manual" ? [location.latitude, location.longitude] : null;
  return JSON.stringify({ ...payload, base_info: { ...payload.base_info, location: manual } });
}

export function withAddressLookup(base, lookup, request) {
  if (String(base.town ?? "").trim() !== request.town || (request.postalCode && base.postal_code !== request.postalCode)) {
    return base;
  }
  const next = { ...base };
  if (lookup.town && (!request.town || plainText(request.town) === plainText(lookup.town))) next.town = lookup.town;
  if (lookup.postal_code && !request.postalCode) next.postal_code = lookup.postal_code;
  const manualKept = base.location?.source === "manual" && base.location.address === addressKey(base);
  if (lookup.location && !manualKept) next.location = { ...lookup.location, address: addressKey(next) };
  return next;
}

export const createEmptyProfile = () => ({
  base_info: {
    type_of_property: "single_family_house",
    year_of_construction: "",
    heating_area_m2: "",
    number_of_residents: 1,
    town: "",
    postal_code: "",
    distribution_operator: "PGE",
    phase_type: "3_phase",
    contracted_power_kw: "",
    billing_cycle: 2,
    billing_period_start_date: "",
    location: null,
  },
  consumption_and_tariff: { tariff_type: "G11", dynamic_price: false },
  pv_config: { mode: "none" },
});

// Zapisany profil (także w starszym formacie) uzupełniony domyślnymi wartościami brakujących pól.
export function profileFromSaved(saved) {
  const empty = createEmptyProfile();
  const tariff = { ...empty.consumption_and_tariff, ...(saved?.consumption_and_tariff ?? {}) };
  // Dawniej „dynamic” było taryfą: to G11 z ceną dynamiczną.
  if (tariff.tariff_type === "dynamic") Object.assign(tariff, { tariff_type: "G11", dynamic_price: true });
  const base = { ...empty.base_info };
  for (const [name, value] of Object.entries(saved?.base_info ?? {})) {
    if (value !== null && value !== undefined) base[name] = value;
  }
  const pv = saved?.pv_config;
  return {
    base_info: base,
    consumption_and_tariff: tariff,
    pv_config: pv?.mode && pv.mode !== "none"
      ? { mode: pv.mode, type_of_price: pv.type_of_price ?? "RCE", installation: installationFromSaved(pv) }
      : empty.pv_config,
  };
}

// Liczba wpisana z przecinkiem albo kropką; pusty lub błędny tekst daje NaN.
export function parseDecimal(value) {
  const text = String(value ?? "").trim().replace(/\s/g, "").replace(",", ".");
  if (text === "" || !/^\d+(\.\d+)?$/.test(text)) return Number.NaN;
  return Number(text);
}

// Wpisywanie kodu pocztowego: tylko cyfry, myślnik po dwóch pierwszych.
export function formatPostalCode(value) {
  const digits = String(value ?? "").replace(/\D/g, "").slice(0, 5);
  return digits.length > 2 ? `${digits.slice(0, 2)}-${digits.slice(2)}` : digits;
}

// Liczba dodatnia nie większa niż max.
function rangeError(value, { max, unit }) {
  const number = parseDecimal(value);
  if (Number.isNaN(number)) return "Podaj liczbę.";
  if (number <= 0) return "Wartość musi być większa od 0.";
  if (number > max) return `Maksymalnie ${max.toLocaleString("pl-PL")} ${unit}.`;
  return null;
}

export const arrayPowerKwp = (installation, array) => {
  if (installation.input === "panels") {
    const count = Number(array.panel_count);
    const watts = Number(installation.panel_power_w);
    return Number.isInteger(count) && count > 0 && watts > 0 ? Math.round(count * watts) / 1000 : Number.NaN;
  }
  return parseDecimal(array.power_kwp);
};

export const totalKwp = (installation) =>
  Math.round(installation.arrays.reduce((sum, array) => sum + arrayPowerKwp(installation, array), 0) * 1000) / 1000;

function integerError(value, { min, max, unit }) {
  const text = String(value ?? "").trim();
  if (!/^\d+$/.test(text)) return "Podaj liczbę całkowitą.";
  const number = Number(text);
  if (number < min || number > max) return `Od ${min} do ${max}${unit ?? ""}.`;
  return null;
}

function installationErrors(installation) {
  const errors = {};
  if (installation.estimated) return errors;
  if (installation.input === "panels") {
    const watts = integerError(installation.panel_power_w, { min: 50, max: 1000, unit: " W" });
    if (watts) errors["pv_config.panel_power_w"] = watts;
  }
  installation.arrays.forEach((array, index) => {
    const prefix = `pv_config.arrays.${index}`;
    if (installation.input === "panels") {
      const count = integerError(array.panel_count, { min: 1, max: 200 });
      if (count) errors[`${prefix}.panel_count`] = count;
    } else {
      const power = rangeError(array.power_kwp, { max: MAX_PV_KWP, unit: "kWp" });
      if (power) errors[`${prefix}.power_kwp`] = power;
    }
    const tilt = integerError(array.tilt, { min: 0, max: 90, unit: "°" });
    if (tilt) errors[`${prefix}.tilt`] = tilt;
  });
  if (Object.keys(errors).length === 0 && totalKwp(installation) > MAX_PV_KWP) {
    errors["pv_config.installation"] = `Łączna moc paneli to najwyżej ${MAX_PV_KWP} kWp (mikroinstalacja).`;
  }
  if (String(installation.inverter_power_kw ?? "").trim()) {
    const inverter = rangeError(installation.inverter_power_kw, { max: MAX_PV_KWP, unit: "kW" });
    if (inverter) errors["pv_config.inverter_power_kw"] = inverter;
  }
  return errors;
}

// Błędy pól przed wysłaniem: klucz „sekcja.pole” → komunikat.
export function validateProfile(profile, { offeredTariffs } = {}) {
  const { base_info: base, consumption_and_tariff: tariff, pv_config: pv } = profile;
  const errors = {};
  const year = Number(base.year_of_construction);
  if (!base.year_of_construction) errors["base_info.year_of_construction"] = "Wybierz rok budowy.";
  else if (!Number.isInteger(year) || year <= 1800 || year > MAX_BUILD_YEAR) {
    errors["base_info.year_of_construction"] = `Rok budowy musi być z przedziału 1801–${MAX_BUILD_YEAR}.`;
  }
  const area = rangeError(base.heating_area_m2, { max: 10000, unit: "m²" });
  if (area) errors["base_info.heating_area_m2"] = area;
  if (!(Number(base.number_of_residents) >= 1)) errors["base_info.number_of_residents"] = "Co najmniej 1 osoba.";
  if (!String(base.town ?? "").trim()) errors["base_info.town"] = "Podaj miejscowość.";
  if (!/^\d{2}-\d{3}$/.test(base.postal_code ?? "")) errors["base_info.postal_code"] = "Kod pocztowy w formacie 00-000.";
  const power = rangeError(base.contracted_power_kw, { max: 10000, unit: "kW" });
  if (power) errors["base_info.contracted_power_kw"] = power;
  if (!base.billing_period_start_date) errors["base_info.billing_period_start_date"] = "Wybierz datę początku okresu.";
  if (offeredTariffs && !offeredTariffs.includes(tariff.tariff_type)) {
    errors["consumption_and_tariff.tariff_type"] = `Taryfa ${tariff.tariff_type} jest niedostępna u tego operatora.`;
  }
  if (pv.mode !== "none" && pv.installation) Object.assign(errors, installationErrors(pv.installation));
  return errors;
}

// Dane do wysłania: liczby zamiast tekstu z formularza.
export function toPayload(profile) {
  const { base_info: base, consumption_and_tariff: tariff, pv_config: pv } = profile;
  return {
    base_info: {
      ...base,
      year_of_construction: Number(base.year_of_construction),
      heating_area_m2: parseDecimal(base.heating_area_m2),
      number_of_residents: Number(base.number_of_residents),
      town: String(base.town).trim(),
      contracted_power_kw: parseDecimal(base.contracted_power_kw),
    },
    consumption_and_tariff: { ...tariff },
    pv_config: pv.mode === "none"
      ? { mode: "none" }
      : {
          mode: pv.mode,
          ...(pv.mode === "net_billing" ? { type_of_price: pv.type_of_price ?? "RCE" } : {}),
          installation: installationPayload(pv.installation ?? typicalInstallation()),
        },
  };
}

function installationPayload(installation) {
  if (installation.estimated) return { arrays: [{ ...TYPICAL_INSTALLATION }], estimated: true };
  const panels = installation.input === "panels";
  const inverter = String(installation.inverter_power_kw ?? "").trim();
  return {
    arrays: installation.arrays.map((array) => ({
      azimuth: array.azimuth,
      tilt: Number(array.tilt),
      ...(panels ? { panel_count: Number(array.panel_count) } : { power_kwp: parseDecimal(array.power_kwp) }),
    })),
    panel_power_w: panels ? Number(installation.panel_power_w) : null,
    inverter_power_kw: inverter ? parseDecimal(inverter) : null,
    estimated: false,
  };
}

// Komunikaty zamiast angielskich opisów walidacji FastAPI (dla typów innych niż value_error z naszym tekstem).
const FIELD_MESSAGES = {
  "base_info.year_of_construction": `Rok budowy musi być z przedziału 1801–${MAX_BUILD_YEAR}.`,
  "base_info.heating_area_m2": "Powierzchnia musi być większa niż 0 i najwyżej 10 000 m².",
  "base_info.number_of_residents": "Co najmniej 1 osoba.",
  "base_info.town": "Podaj miejscowość (do 100 znaków).",
  "base_info.postal_code": "Kod pocztowy w formacie 00-000.",
  "base_info.contracted_power_kw": "Moc umowna musi być większa niż 0 kW.",
  "base_info.billing_period_start_date": "Wybierz datę początku okresu.",
  "pv_config.panel_power_w": "Moc panelu od 50 do 1000 W.",
  "pv_config.inverter_power_kw": "Moc falownika musi być większa niż 0 i najwyżej 50 kW.",
  "base_info.location": "Lokalizacja musi leżeć w Polsce.",
};

function fieldKey(loc) {
  const path = loc[0] === "body" ? loc.slice(1) : loc;
  // pv_config to unia po „mode”: FastAPI dodaje nazwę wariantu, np. ["pv_config", "net_billing", "installation", ...].
  if (path[0] === "pv_config" && path.length > 2) {
    const rest = path.slice(2);
    if (rest[0] !== "installation") return `pv_config.${rest[rest.length - 1]}`;
    if (rest[1] === "arrays" && rest.length >= 4) return `pv_config.arrays.${rest[2]}.${rest[3]}`;
    if (rest.length === 2 && rest[1] !== "arrays") return `pv_config.${rest[1]}`;
    return "pv_config.installation";
  }
  return path.slice(0, 2).join(".");
}

// Błąd zapisu: { fields: {klucz: komunikat}, message: tekst ogólny albo null }.
export function parseSaveError(error) {
  const detail = error?.response?.data?.detail;
  if (Array.isArray(detail)) {
    const fields = {};
    for (const item of detail) {
      const key = fieldKey(item?.loc ?? []);
      if (!key || fields[key]) continue;
      fields[key] = item.type === "value_error" ? String(item.msg ?? "").replace(/^Value error, /, "") : FIELD_MESSAGES[key] ?? "Nieprawidłowa wartość.";
    }
    return { fields, message: Object.keys(fields).length ? null : "Nie udało się zapisać profilu." };
  }
  if (typeof detail === "string") return { fields: {}, message: detail };
  return { fields: {}, message: "Nie udało się zapisać profilu." };
}
