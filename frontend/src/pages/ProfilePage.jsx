import { useEffect, useMemo, useState } from "react";
import apiClient from "../api/client";

const tariffZones = {
  G11: 1,
  G12: 2,
  G12w: 2,
  G13: 3,
  G13s: 3,
  G14d: 4,
};

const propertyTypes = [
  ["apartment", "Mieszkanie"],
  ["single_family_house", "Dom jednorodzinny"],
  ["terrace_house", "Dom szeregowy"],
  ["recreational_cottage", "Domek letniskowy"],
  ["other", "Inny"],
];

const tariffTypes = [
  ["G11", "G11"],
  ["G12", "G12"],
  ["G12w", "G12w"],
  ["G13", "G13"],
  ["G13s", "G13s"],
  ["G14d", "G14d"],
];

const makeZones = (count, value = "") => Array.from({ length: count }, () => value);

const createEmptyProfile = () => ({
  base_info: {
    type_of_property: "apartment",
    year_of_construction: "",
    heating_area_m2: "",
    number_of_residents: "",
    town: "",
  },
  consumption_and_tariff: {
    tariff_type: "G11",
    imported_energy_per_zone_kwh: makeZones(1),
    ure_price_per_zone_kwh: makeZones(1),
  },
  pv_config: {
    mode: "none",
    exported_energy_total_kwh: "",
    self_consumed_energy_kwh: "0",
    type_of_price: "RCEm",
    estimated_buyback_price_per_kwh: "",
    power_of_pv_kwp: "",
    exported_energy_per_zone_kwh: makeZones(1),
    custom_k_factor: "",
  },
  commercial_offer: null,
  distribution_fees: {
    fixed_monthly_osd_fee_pln: "0",
    variable_osd_fee_per_zone_kwh: null,
  },
});

const numberOrZero = (value) => (value === "" ? 0 : Number(value));
const numberOrNull = (value) => (value === "" ? null : Number(value));

function Field({ label, hint, children, className = "" }) {
  return (
    <label className={`text-sm font-medium text-gray-700 ${className}`}>
      <span>{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs font-normal text-gray-500">{hint}</span>}
    </label>
  );
}

const inputClass =
  "mt-2 w-full rounded-md border border-gray-300 bg-white px-3 py-2.5 font-normal text-gray-900 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500";

function ProfilePage() {
  const [profile, setProfile] = useState(createEmptyProfile);
  const [hasCommercialOffer, setHasCommercialOffer] = useState(false);
  const [hasVariableOsdFees, setHasVariableOsdFees] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);

  const zoneCount = useMemo(
    () => tariffZones[profile.consumption_and_tariff.tariff_type],
    [profile.consumption_and_tariff.tariff_type],
  );

  useEffect(() => {
    const loadProfile = async () => {
      try {
        const response = await apiClient.get("/upload/profile");
        const loaded = response.data;
        if (loaded?.base_info && loaded?.consumption_and_tariff) {
          setProfile((current) => ({
            ...current,
            ...loaded,
            base_info: { ...current.base_info, ...loaded.base_info },
            consumption_and_tariff: {
              ...current.consumption_and_tariff,
              ...loaded.consumption_and_tariff,
            },
            pv_config: { ...current.pv_config, ...loaded.pv_config },
            distribution_fees: {
              ...current.distribution_fees,
              ...loaded.distribution_fees,
            },
          }));
          setHasCommercialOffer(Boolean(loaded.commercial_offer));
          setHasVariableOsdFees(Boolean(loaded.distribution_fees?.variable_osd_fee_per_zone_kwh));
        }
      } catch (err) {
        if (err.response?.status !== 404) {
          setError(err.response?.data?.detail || "Nie udało się pobrać danych profilu.");
        }
      } finally {
        setIsLoading(false);
      }
    };

    loadProfile();
  }, []);

  const updateSection = (section, name, value) => {
    setProfile((current) => ({
      ...current,
      [section]: { ...current[section], [name]: value },
    }));
    setError(null);
    setSuccessMessage(null);
  };

  const updateZone = (section, name, index, value) => {
    setProfile((current) => {
      const values = [...current[section][name]];
      values[index] = value;
      return { ...current, [section]: { ...current[section], [name]: values } };
    });
    setError(null);
    setSuccessMessage(null);
  };

  const handleTariffChange = (event) => {
    const tariffType = event.target.value;
    const nextZoneCount = tariffZones[tariffType];
    setProfile((current) => ({
      ...current,
      consumption_and_tariff: {
        ...current.consumption_and_tariff,
        tariff_type: tariffType,
        imported_energy_per_zone_kwh: current.consumption_and_tariff.imported_energy_per_zone_kwh
          .slice(0, nextZoneCount)
          .concat(makeZones(Math.max(0, nextZoneCount - current.consumption_and_tariff.imported_energy_per_zone_kwh.length))),
        ure_price_per_zone_kwh: current.consumption_and_tariff.ure_price_per_zone_kwh
          .slice(0, nextZoneCount)
          .concat(makeZones(Math.max(0, nextZoneCount - current.consumption_and_tariff.ure_price_per_zone_kwh.length))),
      },
      pv_config: {
        ...current.pv_config,
        exported_energy_per_zone_kwh: current.pv_config.exported_energy_per_zone_kwh
          .slice(0, nextZoneCount)
          .concat(makeZones(Math.max(0, nextZoneCount - current.pv_config.exported_energy_per_zone_kwh.length))),
      },
      distribution_fees: {
        ...current.distribution_fees,
        variable_osd_fee_per_zone_kwh: current.distribution_fees.variable_osd_fee_per_zone_kwh
          ? current.distribution_fees.variable_osd_fee_per_zone_kwh
              .slice(0, nextZoneCount)
              .concat(makeZones(Math.max(0, nextZoneCount - current.distribution_fees.variable_osd_fee_per_zone_kwh.length)))
          : null,
      },
    }));
    setError(null);
    setSuccessMessage(null);
  };

  const handlePvModeChange = (event) => {
    const mode = event.target.value;
    setProfile((current) => ({
      ...current,
      pv_config:
        mode === "none"
          ? { mode }
          : { ...current.pv_config, mode },
    }));
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setIsSaving(true);
    setError(null);
    setSuccessMessage(null);

    const { base_info, consumption_and_tariff, pv_config, distribution_fees } = profile;
    const profileData = {
      base_info: {
        ...base_info,
        year_of_construction: Number(base_info.year_of_construction),
        heating_area_m2: Number(base_info.heating_area_m2),
        number_of_residents: Number(base_info.number_of_residents),
      },
      consumption_and_tariff: {
        ...consumption_and_tariff,
        imported_energy_per_zone_kwh: consumption_and_tariff.imported_energy_per_zone_kwh.map(numberOrZero),
        ure_price_per_zone_kwh: consumption_and_tariff.ure_price_per_zone_kwh.map(Number),
      },
      pv_config:
        pv_config.mode === "none"
          ? { mode: "none" }
          : pv_config.mode === "net_billing"
            ? {
                mode: "net_billing",
                exported_energy_total_kwh: Number(pv_config.exported_energy_total_kwh),
                self_consumed_energy_kwh: numberOrZero(pv_config.self_consumed_energy_kwh),
                type_of_price: pv_config.type_of_price,
                estimated_buyback_price_per_kwh: Number(pv_config.estimated_buyback_price_per_kwh),
              }
            : {
                mode: "net_metering",
                power_of_pv_kwp: Number(pv_config.power_of_pv_kwp),
                exported_energy_per_zone_kwh: pv_config.exported_energy_per_zone_kwh.map(numberOrZero),
                custom_k_factor: numberOrNull(pv_config.custom_k_factor),
              },
      commercial_offer: hasCommercialOffer
        ? {
            price_per_zone_kwh: profile.commercial_offer.price_per_zone_kwh.map(Number),
            monthly_commercial_fee_pln: numberOrZero(profile.commercial_offer.monthly_commercial_fee_pln),
            early_exit_penalty_pln: numberOrZero(profile.commercial_offer.early_exit_penalty_pln),
          }
        : null,
      distribution_fees: {
        fixed_monthly_osd_fee_pln: numberOrZero(distribution_fees.fixed_monthly_osd_fee_pln),
        variable_osd_fee_per_zone_kwh: hasVariableOsdFees
          ? distribution_fees.variable_osd_fee_per_zone_kwh.map(numberOrZero)
          : null,
      },
    };

    try {
      const response = await apiClient.post("/upload/profile", profileData);
      setProfile(response.data);
      setSuccessMessage("Profil został zapisany.");
    } catch (err) {
      setError(err.response?.data?.detail || "Nie udało się zapisać profilu.");
    } finally {
      setIsSaving(false);
    }
  };

  const enableCommercialOffer = (enabled) => {
    setHasCommercialOffer(enabled);
    if (enabled) {
      setProfile((current) => ({
        ...current,
        commercial_offer: {
          price_per_zone_kwh: makeZones(zoneCount),
          monthly_commercial_fee_pln: "0",
          early_exit_penalty_pln: "0",
        },
      }));
    } else {
      setProfile((current) => ({ ...current, commercial_offer: null }));
    }
  };

  const enableVariableOsdFees = (enabled) => {
    setHasVariableOsdFees(enabled);
    setProfile((current) => ({
      ...current,
      distribution_fees: {
        ...current.distribution_fees,
        variable_osd_fee_per_zone_kwh: enabled ? makeZones(zoneCount) : null,
      },
    }));
  };

  if (isLoading) {
    return <div className="mx-auto max-w-5xl text-gray-500">Ładowanie profilu...</div>;
  }

  const tariff = profile.consumption_and_tariff;
  const pv = profile.pv_config;
  const distribution_fees = profile.distribution_fees;

  return (
    <div className="mx-auto max-w-5xl pb-12">
      <h2 className="mb-2 border-b border-gray-200 pb-4 text-xl font-bold text-gray-900">Profil</h2>
      <p className="mb-6 text-gray-600">
        Uzupełnij dane nieruchomości i energii, aby przygotować dokładne porównanie taryf.
      </p>

      <form onSubmit={handleSubmit} className="space-y-6">
        <section className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm md:p-8">
          <h3 className="mb-1 text-lg font-semibold text-gray-900">Podstawowe informacje o budynku</h3>
          <p className="mb-6 text-sm text-gray-500">Dane potrzebne do dopasowania analizy do Twojej nieruchomości.</p>
          <div className="grid gap-5 md:grid-cols-2">
            <Field label="Typ nieruchomości">
              <select className={inputClass} value={profile.base_info.type_of_property} onChange={(e) => updateSection("base_info", "type_of_property", e.target.value)}>
                {propertyTypes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </Field>
            <Field label="Rok budowy" hint="Zakres: 1801–2027">
              <input className={inputClass} type="number" min="1801" max="2027" value={profile.base_info.year_of_construction} onChange={(e) => updateSection("base_info", "year_of_construction", e.target.value)} required />
            </Field>
            <Field label="Powierzchnia ogrzewana (m²)">
              <input className={inputClass} type="number" min="0.01" max="10000" step="0.01" value={profile.base_info.heating_area_m2} onChange={(e) => updateSection("base_info", "heating_area_m2", e.target.value)} required />
            </Field>
            <Field label="Liczba mieszkańców">
              <input className={inputClass} type="number" min="1" step="1" value={profile.base_info.number_of_residents} onChange={(e) => updateSection("base_info", "number_of_residents", e.target.value)} required />
            </Field>
            <Field label="Miejscowość">
              <input className={inputClass} type="text" maxLength="100" value={profile.base_info.town} onChange={(e) => updateSection("base_info", "town", e.target.value)} required />
            </Field>
          </div>
        </section>

        <section className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm md:p-8">
          <h3 className="mb-1 text-lg font-semibold text-gray-900">Zużycie i taryfa</h3>
          <p className="mb-6 text-sm text-gray-500">Podaj wartości osobno dla każdej strefy wybranej taryfy.</p>
          <Field label="Obecna taryfa">
            <select className={inputClass} value={tariff.tariff_type} onChange={handleTariffChange}>
              {tariffTypes.map(([value, label]) => <option key={value} value={value}>{label} ({tariffZones[value]} {tariffZones[value] === 1 ? "strefa" : "strefy"})</option>)}
            </select>
          </Field>
          <div className="mt-6 border-t border-gray-200 pt-6">
            <h4 className="mb-4 text-sm font-semibold uppercase tracking-wide text-gray-700">
              Zużycie energii w strefach
            </h4>
            <div className="grid gap-5 md:grid-cols-2">
              {tariff.imported_energy_per_zone_kwh.map((value, index) => (
                <Field key={`energy-${index}`} label={`Zużycie energii — strefa ${index + 1} (kWh)`}>
                  <input className={inputClass} type="number" min="0" step="0.01" value={value} onChange={(e) => updateZone("consumption_and_tariff", "imported_energy_per_zone_kwh", index, e.target.value)} required />
                </Field>
              ))}
            </div>
          </div>
          <div className="mt-6 border-t border-gray-200 pt-6">
            <h4 className="mb-4 text-sm font-semibold uppercase tracking-wide text-gray-700">
              Ceny URE w strefach
            </h4>
            <div className="grid gap-5 md:grid-cols-2">
              {tariff.ure_price_per_zone_kwh.map((value, index) => (
                <Field key={`ure-${index}`} label={`Cena URE — strefa ${index + 1} (zł/kWh)`}>
                  <input className={inputClass} type="number" min="0.01" max="10" step="0.0001" value={value} onChange={(e) => updateZone("consumption_and_tariff", "ure_price_per_zone_kwh", index, e.target.value)} required />
                </Field>
              ))}
            </div>
          </div>
        </section>

        <section className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm md:p-8">
          <h3 className="mb-1 text-lg font-semibold text-gray-900">Fotowoltaika</h3>
          <p className="mb-6 text-sm text-gray-500">Wybierz system rozliczania albo zaznacz brak instalacji.</p>
          <Field label="Konfiguracja PV">
            <select className={inputClass} value={pv.mode} onChange={handlePvModeChange}>
              <option value="none">Brak fotowoltaiki</option>
              <option value="net_billing">Net-billing</option>
              <option value="net_metering">System opustów (net-metering)</option>
            </select>
          </Field>
          {pv.mode === "net_billing" && (
            <div className="mt-5 grid gap-5 md:grid-cols-2">
              <Field label="Roczna energia oddana do sieci (kWh)"><input className={inputClass} type="number" min="0.01" step="0.01" value={pv.exported_energy_total_kwh} onChange={(e) => updateSection("pv_config", "exported_energy_total_kwh", e.target.value)} required /></Field>
              <Field label="Autokonsumpcja (kWh)"><input className={inputClass} type="number" min="0" step="0.01" value={pv.self_consumed_energy_kwh} onChange={(e) => updateSection("pv_config", "self_consumed_energy_kwh", e.target.value)} /></Field>
              <Field label="Typ ceny odkupu"><select className={inputClass} value={pv.type_of_price} onChange={(e) => updateSection("pv_config", "type_of_price", e.target.value)}><option value="RCEm">RCEm</option><option value="RCE">RCE</option></select></Field>
              <Field label="Szacowana cena odkupu (zł/kWh)"><input className={inputClass} type="number" min="0.01" max="10" step="0.0001" value={pv.estimated_buyback_price_per_kwh} onChange={(e) => updateSection("pv_config", "estimated_buyback_price_per_kwh", e.target.value)} required /></Field>
            </div>
          )}
          {pv.mode === "net_metering" && (
            <div className="mt-5 grid gap-5 md:grid-cols-2">
              <Field label="Moc instalacji (kWp)" hint="Maksymalnie 50 kWp"><input className={inputClass} type="number" min="0.01" max="50" step="0.01" value={pv.power_of_pv_kwp} onChange={(e) => updateSection("pv_config", "power_of_pv_kwp", e.target.value)} required /></Field>
              <Field label="Własny współczynnik k" hint="Opcjonalnie, zakres: 0–1"><input className={inputClass} type="number" min="0.01" max="1" step="0.01" value={pv.custom_k_factor} onChange={(e) => updateSection("pv_config", "custom_k_factor", e.target.value)} /></Field>
              {pv.exported_energy_per_zone_kwh.map((value, index) => <Field key={`export-${index}`} label={`Energia oddana — strefa ${index + 1} (kWh)`}><input className={inputClass} type="number" min="0" step="0.01" value={value} onChange={(e) => updateZone("pv_config", "exported_energy_per_zone_kwh", index, e.target.value)} required /></Field>)}
            </div>
          )}
        </section>

        <section className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm md:p-8">
          <h3 className="mb-1 text-lg font-semibold text-gray-900">Oferta i opłaty</h3>
          <p className="mb-6 text-sm text-gray-500">Pola opcjonalne pozwalają porównać taryfę URE z ofertą sprzedawcy i pełnym kosztem dystrybucji.</p>
          <div className="space-y-4">
            <label className="flex items-center gap-3 text-sm font-medium text-gray-700">
              <input type="checkbox" checked={hasCommercialOffer} onChange={(e) => enableCommercialOffer(e.target.checked)} className="h-4 w-4 accent-emerald-500" />
              Mam ofertę komercyjną do porównania
            </label>
            {hasCommercialOffer && profile.commercial_offer && (
              <div className="grid gap-5 border-l-2 border-emerald-100 pl-4 md:grid-cols-2">
                {profile.commercial_offer.price_per_zone_kwh.map((value, index) => <Field key={`commercial-${index}`} label={`Cena oferty — strefa ${index + 1} (zł/kWh)`}><input className={inputClass} type="number" min="0.01" max="10" step="0.0001" value={value} onChange={(e) => updateZone("commercial_offer", "price_per_zone_kwh", index, e.target.value)} required /></Field>)}
                <Field label="Miesięczna opłata handlowa (zł/m-c)"><input className={inputClass} type="number" min="0" step="0.01" value={profile.commercial_offer.monthly_commercial_fee_pln} onChange={(e) => updateSection("commercial_offer", "monthly_commercial_fee_pln", e.target.value)} /></Field>
                <Field label="Kara za wcześniejsze zerwanie umowy (zł)"><input className={inputClass} type="number" min="0" step="0.01" value={profile.commercial_offer.early_exit_penalty_pln} onChange={(e) => updateSection("commercial_offer", "early_exit_penalty_pln", e.target.value)} /></Field>
              </div>
            )}
            <Field label="Stałe opłaty OSD (zł/m-c)"><input className={inputClass} type="number" min="0" step="0.01" value={distribution_fees.fixed_monthly_osd_fee_pln} onChange={(e) => updateSection("distribution_fees", "fixed_monthly_osd_fee_pln", e.target.value)} /></Field>
            <label className="flex items-center gap-3 text-sm font-medium text-gray-700">
              <input type="checkbox" checked={hasVariableOsdFees} onChange={(e) => enableVariableOsdFees(e.target.checked)} className="h-4 w-4 accent-emerald-500" />
              Podaj zmienne stawki dystrybucyjne dla stref
            </label>
            {hasVariableOsdFees && distribution_fees.variable_osd_fee_per_zone_kwh && (
              <div className="grid gap-5 border-l-2 border-emerald-100 pl-4 md:grid-cols-2">
                {distribution_fees.variable_osd_fee_per_zone_kwh.map((value, index) => <Field key={`osd-${index}`} label={`Zmienna stawka OSD — strefa ${index + 1} (zł/kWh)`}><input className={inputClass} type="number" min="0" max="5" step="0.0001" value={value} onChange={(e) => updateZone("distribution_fees", "variable_osd_fee_per_zone_kwh", index, e.target.value)} required /></Field>)}
              </div>
            )}
          </div>
        </section>

        {(error || successMessage) && (
          <div
            className={`rounded-lg border p-4 text-sm ${
              error
                ? "border-red-200 bg-red-50 text-red-700"
                : "border-emerald-200 bg-emerald-50 text-emerald-700"
            }`}
          >
            {error || successMessage}
          </div>
        )}

        <div className="flex justify-end">
          <button type="submit" disabled={isSaving} className="rounded-md bg-emerald-500 px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-emerald-600 disabled:cursor-not-allowed disabled:opacity-60">
            {isSaving ? "Zapisywanie..." : "Zapisz profil"}
          </button>
        </div>
      </form>
    </div>
  );
}

export default ProfilePage;
