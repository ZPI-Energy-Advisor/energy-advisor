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
  "pv_config.power_of_pv_kwp": "Moc instalacji",
};

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
  return {
    base_info: base,
    consumption_and_tariff: tariff,
    pv_config: saved?.pv_config?.mode ? saved.pv_config : empty.pv_config,
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
  if (pv.mode === "net_metering") {
    const pvPower = rangeError(pv.power_of_pv_kwp, { max: 50, unit: "kWp" });
    if (pvPower) errors["pv_config.power_of_pv_kwp"] = pvPower;
  }
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
      : pv.mode === "net_billing"
        ? { mode: "net_billing", type_of_price: pv.type_of_price ?? "RCE" }
        : { mode: "net_metering", power_of_pv_kwp: parseDecimal(pv.power_of_pv_kwp) },
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
  "pv_config.power_of_pv_kwp": "Moc instalacji musi być większa niż 0 i najwyżej 50 kWp.",
};

function fieldKey(loc) {
  const path = loc[0] === "body" ? loc.slice(1) : loc;
  // pv_config to unia po „mode”: FastAPI dodaje nazwę wariantu, np. ["pv_config", "net_metering", "power_of_pv_kwp"].
  if (path[0] === "pv_config" && path.length > 2) return `pv_config.${path[path.length - 1]}`;
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
