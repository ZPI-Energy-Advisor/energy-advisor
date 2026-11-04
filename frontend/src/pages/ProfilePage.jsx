import { useEffect, useState } from "react";
import apiClient from "../api/client";
import { useCurrentUser } from "../hooks/useCurrentUser";

const tariffTypes = ["G11", "G12", "G12w", "G13", "G13s", "G14d", "dynamic"];

const createEmptyProfile = () => ({
  base_info: {
    type_of_property: "single_family_house",
    year_of_construction: "",
    heating_area_m2: "",
    number_of_residents: "",
    town: "",
    postal_code: "",
    distribution_operator: "PGE",
    phase_type: "3_phase",
    contracted_power_kw: "",
    billing_cycle: 2,
    billing_period_start_date: "",
  },
  consumption_and_tariff: {
    tariff_type: "G11",
  },
  pv_config: { mode: "none" },
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
  const { refresh: refreshCurrentUser } = useCurrentUser();
  const [profile, setProfile] = useState(createEmptyProfile);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);

  useEffect(() => {
    apiClient.get("/users/me/profile")
      .then(({ data }) => {
        setProfile(data);
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

  const handleTariffChange = (event) => {
    const tariffType = event.target.value;
    setProfile((current) => ({
      ...current,
      consumption_and_tariff: {
        ...current.consumption_and_tariff,
        tariff_type: tariffType,
      },
    }));
  };

  const handlePvModeChange = (event) => {
    const mode = event.target.value;
    setProfile((current) => ({
      ...current,
      pv_config: mode === "none"
        ? { mode }
        : mode === "net_billing"
          ? { mode, type_of_price: "RCEm" }
          : { mode, power_of_pv_kwp: "" },
    }));
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setIsSaving(true);
    setError(null);
    setSuccessMessage(null);
    const { base_info, consumption_and_tariff, pv_config } = profile;
    const profileData = {
      base_info: {
        ...base_info,
        year_of_construction: Number(base_info.year_of_construction),
        heating_area_m2: Number(base_info.heating_area_m2),
        number_of_residents: Number(base_info.number_of_residents),
        contracted_power_kw: Number(base_info.contracted_power_kw),
      },
      consumption_and_tariff: {
        ...consumption_and_tariff,
      },
      pv_config: pv_config.mode === "none"
        ? { mode: "none" }
        : pv_config.mode === "net_billing"
          ? { mode: "net_billing", type_of_price: pv_config.type_of_price }
          : {
              mode: "net_metering",
              power_of_pv_kwp: Number(pv_config.power_of_pv_kwp),
            },
    };
    try {
      const response = await apiClient.put("/users/me/profile", profileData);
      setProfile(response.data);
      setSuccessMessage("Profil został zapisany.");
      refreshCurrentUser();
    } catch (err) {
      setError(err.response?.data?.detail || "Nie udało się zapisać profilu.");
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoading) return <div className="mx-auto max-w-5xl text-gray-500">Ładowanie profilu...</div>;
  const { base_info, consumption_and_tariff, pv_config } = profile;

  return (
    <div className="mx-auto max-w-5xl pb-12">
      <h2 className="mb-2 border-b border-gray-200 pb-4 text-xl font-bold text-gray-900">Profil kalkulatora</h2>
      {error && <p className="mb-4 rounded bg-red-50 p-3 text-red-700">{error}</p>}
      {successMessage && <p className="mb-4 rounded bg-emerald-50 p-3 text-emerald-700">{successMessage}</p>}
      <form onSubmit={handleSubmit} className="space-y-6">
        <section className="grid gap-5 rounded-lg border border-gray-200 bg-white p-6 shadow-sm md:grid-cols-3">
          <Field label="Typ nieruchomości">
            <select className={inputClass} value={base_info.type_of_property} onChange={(e) => updateSection("base_info", "type_of_property", e.target.value)}>
              <option value="apartment">Mieszkanie</option><option value="single_family_house">Dom jednorodzinny</option>
              <option value="terrace_house">Dom szeregowy</option><option value="recreational_cottage">Domek letniskowy</option><option value="other">Inny</option>
            </select>
          </Field>
          <Field label="Rok budowy"><input className={inputClass} type="number" min="1801" max="2027" value={base_info.year_of_construction} onChange={(e) => updateSection("base_info", "year_of_construction", e.target.value)} required /></Field>
          <Field label="Powierzchnia ogrzewana (m²)"><input className={inputClass} type="number" min="0.01" max="10000" step="0.01" value={base_info.heating_area_m2} onChange={(e) => updateSection("base_info", "heating_area_m2", e.target.value)} required /></Field>
          <Field label="Liczba mieszkańców"><input className={inputClass} type="number" min="1" value={base_info.number_of_residents} onChange={(e) => updateSection("base_info", "number_of_residents", e.target.value)} required /></Field>
          <Field label="Miejscowość"><input className={inputClass} value={base_info.town} onChange={(e) => updateSection("base_info", "town", e.target.value)} required /></Field>
          <Field label="Kod pocztowy"><input className={inputClass} value={base_info.postal_code} onChange={(e) => updateSection("base_info", "postal_code", e.target.value)} placeholder="00-000" required /></Field>
          <Field label="Operator dystrybucyjny">
            <select className={inputClass} value={base_info.distribution_operator} onChange={(e) => updateSection("base_info", "distribution_operator", e.target.value)}>
              <option value="PGE">PGE Dystrybucja</option><option value="TAURON">TAURON Dystrybucja</option><option value="ENEA">Enea Operator</option><option value="ENERGA">Energa-Operator</option><option value="STOEN">Stoen Operator</option>
            </select>
          </Field>
          <Field label="Faza"><select className={inputClass} value={base_info.phase_type} onChange={(e) => updateSection("base_info", "phase_type", e.target.value)}><option value="1_phase">1 faza</option><option value="3_phase">3 fazy</option></select></Field>
          <Field label="Moc umowna (kW)"><input className={inputClass} type="number" min="0.01" max="10000" step="0.01" value={base_info.contracted_power_kw} onChange={(e) => updateSection("base_info", "contracted_power_kw", e.target.value)} required /></Field>
          <Field label="Cykl rozliczeniowy"><select className={inputClass} value={base_info.billing_cycle} onChange={(e) => updateSection("base_info", "billing_cycle", Number(e.target.value))}>{[1, 2, 6, 12].map((value) => <option key={value} value={value}>{value} {value === 1 ? "miesiąc" : "miesięcy"}</option>)}</select></Field>
          <Field label="Początek okresu rozliczeniowego"><input className={inputClass} type="date" value={base_info.billing_period_start_date} onChange={(e) => updateSection("base_info", "billing_period_start_date", e.target.value)} required /></Field>
        </section>
        <section className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
          <Field label="Taryfa"><select className={inputClass} value={consumption_and_tariff.tariff_type} onChange={handleTariffChange}>{tariffTypes.map((value) => <option key={value} value={value}>{value === "dynamic" ? "Dynamiczna" : value}</option>)}</select></Field>
        </section>
        <section className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
          <Field label="Fotowoltaika"><select className={inputClass} value={pv_config.mode} onChange={handlePvModeChange}><option value="none">Brak</option><option value="net_billing">Net-billing</option><option value="net_metering">Net-metering</option></select></Field>
          {pv_config.mode === "net_billing" && <Field label="Typ ceny energii"><select className={inputClass} value={pv_config.type_of_price} onChange={(e) => updateSection("pv_config", "type_of_price", e.target.value)}><option value="RCE">RCE</option><option value="RCEm">RCEm</option></select></Field>}
          {pv_config.mode === "net_metering" && <div className="mt-5"><Field label="Moc instalacji (kWp)"><input className={inputClass} type="number" min="0.01" max="50" step="0.01" value={pv_config.power_of_pv_kwp} onChange={(e) => updateSection("pv_config", "power_of_pv_kwp", e.target.value)} required /></Field></div>}
        </section>
        <button className="rounded-md bg-emerald-600 px-5 py-2.5 font-semibold text-white disabled:opacity-50" disabled={isSaving}>{isSaving ? "Zapisywanie..." : "Zapisz profil"}</button>
      </form>
    </div>
  );
}

export default ProfilePage;
