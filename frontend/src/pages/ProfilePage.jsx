import { useEffect, useMemo, useState } from "react";
import apiClient from "../api/client";

const tariffZones = { G11: 1, G12: 2, G12w: 2, G13: 3, G13s: 3, G14d: 4 };
const tariffTypes = Object.keys(tariffZones);
const makeZones = (count, value = "") => Array.from({ length: count }, () => value);
const numberOrNull = (value) => (value === "" ? null : Number(value));

const createEmptyProfile = () => ({
  connection: { postal_code: "", phase_type: "3_phase", billing_cycle: 2 },
  consumption: { tariff_type: "G11", annual_imported_kwh_per_zone: makeZones(1) },
  pv_config: { mode: "none" },
  commercial_offer: null,
});

function Field({ label, children }) {
  return (
    <label className="text-sm font-medium text-gray-700">
      <span>{label}</span>
      {children}
    </label>
  );
}

const inputClass =
  "mt-2 w-full rounded-md border border-gray-300 bg-white px-3 py-2.5 font-normal text-gray-900 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500";

function ProfilePage() {
  const [profile, setProfile] = useState(createEmptyProfile);
  const [hasCommercialOffer, setHasCommercialOffer] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);
  const zoneCount = useMemo(
    () => tariffZones[profile.consumption.tariff_type],
    [profile.consumption.tariff_type],
  );

  useEffect(() => {
    apiClient.get("/upload/profile")
      .then(({ data }) => {
        setProfile(data);
        setHasCommercialOffer(Boolean(data.commercial_offer));
      })
      .catch((err) => {
        if (err.response?.status !== 404) {
          setError(err.response?.data?.detail || "Nie udało się pobrać danych profilu.");
        }
      })
      .finally(() => setIsLoading(false));
  }, []);

  const updateSection = (section, name, value) => {
    setProfile((current) => ({
      ...current,
      [section]: { ...current[section], [name]: value },
    }));
    setError(null);
    setSuccessMessage(null);
  };

  const updateZone = (index, value) => {
    setProfile((current) => {
      const values = [...current.consumption.annual_imported_kwh_per_zone];
      values[index] = value;
      return { ...current, consumption: { ...current.consumption, annual_imported_kwh_per_zone: values } };
    });
  };

  const handleTariffChange = (event) => {
    const tariffType = event.target.value;
    const nextZoneCount = tariffZones[tariffType];
    setProfile((current) => ({
      ...current,
      consumption: {
        ...current.consumption,
        tariff_type: tariffType,
        annual_imported_kwh_per_zone: current.consumption.annual_imported_kwh_per_zone
          .slice(0, nextZoneCount)
          .concat(makeZones(Math.max(0, nextZoneCount - current.consumption.annual_imported_kwh_per_zone.length))),
      },
      pv_config: current.pv_config.mode === "net_metering"
        ? {
            ...current.pv_config,
            annual_exported_energy_per_zone_kwh: current.pv_config.annual_exported_energy_per_zone_kwh
              .slice(0, nextZoneCount)
              .concat(makeZones(Math.max(0, nextZoneCount - current.pv_config.annual_exported_energy_per_zone_kwh.length))),
          }
        : current.pv_config,
    }));
  };

  const handlePvModeChange = (event) => {
    const mode = event.target.value;
    setProfile((current) => ({
      ...current,
      pv_config: mode === "none"
        ? { mode }
        : mode === "net_billing"
          ? { mode, annual_exported_energy_kwh: "", self_consumed_energy_kwh: "0", custom_buyback_price_per_kwh: null }
          : { mode, power_of_pv_kwp: "", annual_exported_energy_per_zone_kwh: makeZones(zoneCount), custom_k_factor: null },
    }));
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setIsSaving(true);
    setError(null);
    setSuccessMessage(null);
    const { connection, consumption, pv_config, commercial_offer } = profile;
    const profileData = {
      connection,
      consumption: {
        ...consumption,
        annual_imported_kwh_per_zone: consumption.annual_imported_kwh_per_zone.map((value) => Number(value)),
      },
      pv_config: pv_config.mode === "none"
        ? { mode: "none" }
        : pv_config.mode === "net_billing"
          ? {
              mode: "net_billing",
              annual_exported_energy_kwh: Number(pv_config.annual_exported_energy_kwh),
              self_consumed_energy_kwh: Number(pv_config.self_consumed_energy_kwh),
              custom_buyback_price_per_kwh: numberOrNull(pv_config.custom_buyback_price_per_kwh),
            }
          : {
              mode: "net_metering",
              power_of_pv_kwp: Number(pv_config.power_of_pv_kwp),
              annual_exported_energy_per_zone_kwh: pv_config.annual_exported_energy_per_zone_kwh.map((value) => Number(value)),
              custom_k_factor: numberOrNull(pv_config.custom_k_factor),
            },
      commercial_offer: hasCommercialOffer
        ? {
            ...commercial_offer,
            price_per_zone_kwh: commercial_offer.price_per_zone_kwh.map(Number),
            monthly_commercial_fee_pln: Number(commercial_offer.monthly_commercial_fee_pln),
            contract_duration_months: Number(commercial_offer.contract_duration_months),
            early_exit_penalty_pln: Number(commercial_offer.early_exit_penalty_pln),
          }
        : null,
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
    setProfile((current) => ({
      ...current,
      commercial_offer: enabled
        ? { price_per_zone_kwh: makeZones(zoneCount), monthly_commercial_fee_pln: "0", contract_duration_months: "24", early_exit_penalty_pln: "0" }
        : null,
    }));
  };

  if (isLoading) return <div className="mx-auto max-w-5xl text-gray-500">Ładowanie profilu...</div>;
  const { connection, consumption, pv_config, commercial_offer } = profile;

  return (
    <div className="mx-auto max-w-5xl pb-12">
      <h2 className="mb-2 border-b border-gray-200 pb-4 text-xl font-bold text-gray-900">Profil kalkulatora</h2>
      {error && <p className="mb-4 rounded bg-red-50 p-3 text-red-700">{error}</p>}
      {successMessage && <p className="mb-4 rounded bg-emerald-50 p-3 text-emerald-700">{successMessage}</p>}
      <form onSubmit={handleSubmit} className="space-y-6">
        <section className="grid gap-5 rounded-lg border border-gray-200 bg-white p-6 shadow-sm md:grid-cols-3">
          <Field label="Kod pocztowy"><input className={inputClass} value={connection.postal_code} onChange={(e) => updateSection("connection", "postal_code", e.target.value)} placeholder="00-000" required /></Field>
          <Field label="Faza"><select className={inputClass} value={connection.phase_type} onChange={(e) => updateSection("connection", "phase_type", e.target.value)}><option value="1_phase">1 faza</option><option value="3_phase">3 fazy</option></select></Field>
          <Field label="Cykl rozliczeniowy"><select className={inputClass} value={connection.billing_cycle} onChange={(e) => updateSection("connection", "billing_cycle", Number(e.target.value))}>{[1, 2, 6, 12].map((value) => <option key={value} value={value}>{value} {value === 1 ? "miesiąc" : "miesięcy"}</option>)}</select></Field>
        </section>
        <section className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
          <Field label="Taryfa"><select className={inputClass} value={consumption.tariff_type} onChange={handleTariffChange}>{tariffTypes.map((value) => <option key={value} value={value}>{value}</option>)}</select></Field>
          <div className="mt-5 grid gap-5 md:grid-cols-2">{consumption.annual_imported_kwh_per_zone.map((value, index) => <Field key={index} label={`Roczne zużycie — strefa ${index + 1} (kWh)`}><input className={inputClass} type="number" min="0" step="0.01" value={value} onChange={(e) => updateZone(index, e.target.value)} required /></Field>)}</div>
        </section>
        <section className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
          <Field label="Fotowoltaika"><select className={inputClass} value={pv_config.mode} onChange={handlePvModeChange}><option value="none">Brak</option><option value="net_billing">Net-billing</option><option value="net_metering">Net-metering</option></select></Field>
          {pv_config.mode === "net_billing" && <div className="mt-5 grid gap-5 md:grid-cols-3"><Field label="Eksport roczny (kWh)"><input className={inputClass} type="number" min="0" value={pv_config.annual_exported_energy_kwh} onChange={(e) => updateSection("pv_config", "annual_exported_energy_kwh", e.target.value)} required /></Field><Field label="Autokonsumpcja (kWh)"><input className={inputClass} type="number" min="0" value={pv_config.self_consumed_energy_kwh} onChange={(e) => updateSection("pv_config", "self_consumed_energy_kwh", e.target.value)} /></Field><Field label="Cena odkupu (zł/kWh)"><input className={inputClass} type="number" min="0" max="10" step="0.0001" value={pv_config.custom_buyback_price_per_kwh ?? ""} onChange={(e) => updateSection("pv_config", "custom_buyback_price_per_kwh", e.target.value)} /></Field></div>}
          {pv_config.mode === "net_metering" && <div className="mt-5 grid gap-5 md:grid-cols-2"><Field label="Moc instalacji (kWp)"><input className={inputClass} type="number" min="0.01" max="50" step="0.01" value={pv_config.power_of_pv_kwp} onChange={(e) => updateSection("pv_config", "power_of_pv_kwp", e.target.value)} required /></Field>{pv_config.annual_exported_energy_per_zone_kwh.map((value, index) => <Field key={index} label={`Eksport — strefa ${index + 1} (kWh)`}><input className={inputClass} type="number" min="0" value={value} onChange={(e) => { const values = [...pv_config.annual_exported_energy_per_zone_kwh]; values[index] = e.target.value; updateSection("pv_config", "annual_exported_energy_per_zone_kwh", values); }} required /></Field>)}</div>}
        </section>
        <section className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
          <label className="flex items-center gap-2 text-sm font-medium text-gray-700"><input type="checkbox" checked={hasCommercialOffer} onChange={(e) => enableCommercialOffer(e.target.checked)} /> Porównaj ofertę komercyjną</label>
          {commercial_offer && <div className="mt-5 grid gap-5 md:grid-cols-2">{commercial_offer.price_per_zone_kwh.map((value, index) => <Field key={index} label={`Cena — strefa ${index + 1} (zł/kWh)`}><input className={inputClass} type="number" min="0" max="10" step="0.0001" value={value} onChange={(e) => { const values = [...commercial_offer.price_per_zone_kwh]; values[index] = e.target.value; updateSection("commercial_offer", "price_per_zone_kwh", values); }} required /></Field>)}<Field label="Opłata miesięczna (zł)"><input className={inputClass} type="number" min="0" value={commercial_offer.monthly_commercial_fee_pln} onChange={(e) => updateSection("commercial_offer", "monthly_commercial_fee_pln", e.target.value)} /></Field><Field label="Okres umowy (miesiące)"><input className={inputClass} type="number" min="1" max="36" value={commercial_offer.contract_duration_months} onChange={(e) => updateSection("commercial_offer", "contract_duration_months", e.target.value)} /></Field><Field label="Kara za wcześniejsze wyjście (zł)"><input className={inputClass} type="number" min="0" value={commercial_offer.early_exit_penalty_pln} onChange={(e) => updateSection("commercial_offer", "early_exit_penalty_pln", e.target.value)} /></Field></div>}
        </section>
        <button className="rounded-md bg-emerald-600 px-5 py-2.5 font-semibold text-white disabled:opacity-50" disabled={isSaving}>{isSaving ? "Zapisywanie..." : "Zapisz profil"}</button>
      </form>
    </div>
  );
}

export default ProfilePage;
