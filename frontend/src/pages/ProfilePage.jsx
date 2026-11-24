import { useEffect, useRef, useState } from "react";
import { FiAlertCircle, FiCheckCircle } from "react-icons/fi";
import apiClient from "../api/client";
import SegmentedControl from "../components/SegmentedControl";
import DeleteAccount from "../components/profile/DeleteAccount";
import HomeLocationField from "../components/profile/HomeLocationField";
import PvInstallationFields from "../components/profile/PvInstallationFields";
import { ChoiceCards, Field, Section, Stepper, UnitInput, inputClass } from "../components/profile/ProfileControls";
import { useCurrentUser } from "../hooks/useCurrentUser";
import { useUnsavedChangesWarning } from "../hooks/useUnsavedChangesWarning";
import {
  FIELD_LABELS,
  MAX_BUILD_YEAR,
  MIN_BUILD_YEAR,
  createEmptyProfile,
  fieldLabel,
  formatPostalCode,
  parseSaveError,
  profileFromSaved,
  profileSnapshot,
  toPayload,
  typicalInstallation,
  validateProfile,
  withAddressLookup,
} from "../utils/profileForm";

// Grupy taryfowe, gdy operator nie ma stawek w cenniku.
const FALLBACK_TARIFFS = ["G11", "G12", "G12w", "G12n", "G12r", "G13"];
const FALLBACK_CYCLES = [1, 2, 6, 12];

const PROPERTY_TYPES = [
  ["single_family_house", "Dom jednorodzinny"],
  ["terrace_house", "Dom szeregowy"],
  ["apartment", "Mieszkanie"],
  ["recreational_cottage", "Domek letniskowy"],
  ["other", "Inny"],
];
const OPERATORS = [
  ["PGE", "PGE Dystrybucja"],
  ["TAURON", "TAURON Dystrybucja"],
  ["ENEA", "Enea Operator"],
  ["ENERGA", "Energa-Operator"],
  ["STOEN", "Stoen Operator"],
];
const BUILD_YEARS = Array.from({ length: MAX_BUILD_YEAR - MIN_BUILD_YEAR + 1 }, (_, index) => MAX_BUILD_YEAR - index);

const PV_MODES = [
  { value: "none", label: "Brak", description: "Bez instalacji fotowoltaicznej." },
  {
    value: "net_billing",
    label: "Net-billing",
    description: "Oddana energia rozliczana w złotówkach przez depozyt prosumencki. Instalacje od 1.04.2022.",
  },
  {
    value: "net_metering",
    label: "Net-metering (system opustów)",
    description: "Oddana energia odbierana w kWh: 80% do 10 kWp, 70% powyżej. Instalacje sprzed 1.04.2022.",
  },
];
const PRICE_TYPES = [
  { value: "RCE", label: "RCE", description: "Cena rynkowa z każdego kwadransa." },
  { value: "RCEm", label: "RCEm", description: "Średnia miesięczna cena rynkowa." },
];

const fieldId = (key) => `profile-${key.replaceAll(".", "-")}`;
const POSTAL_CODE = /^\d{2}-\d{3}$/;
const LOOKUP_UNAVAILABLE = "Nie udało się teraz sprawdzić adresu. Sprawdzimy go przy zapisie profilu.";
const cycleLabel = (months) => `${months} mies.`;

function ProfilePage() {
  const { me, refresh: refreshCurrentUser } = useCurrentUser();
  const [profile, setProfile] = useState(createEmptyProfile);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [saveError, setSaveError] = useState(null);
  const [fieldErrors, setFieldErrors] = useState({});
  const [missingFields, setMissingFields] = useState([]);
  const [successMessage, setSuccessMessage] = useState(null);
  const [optionsState, setOptionsState] = useState({ operator: null, data: null });
  const [scrollRequest, setScrollRequest] = useState(0);
  const [savedProfile, setSavedProfile] = useState(null);
  const [lookup, setLookup] = useState(null);
  const lookupRef = useRef({ key: null, id: 0 });
  const errorSummaryRef = useRef(null);

  const dirty = savedProfile !== null && profileSnapshot(profile) !== profileSnapshot(savedProfile);
  useUnsavedChangesWarning(dirty);

  // Po nieudanym zapisie przewijamy do listy błędów nad formularzem (przycisk jest na dole strony).
  useEffect(() => {
    if (scrollRequest) errorSummaryRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }, [scrollRequest]);

  const operator = profile.base_info.distribution_operator;
  useEffect(() => {
    let cancelled = false;
    apiClient.get("/tariffs/options", { params: { operator } })
      .then(({ data }) => {
        if (!cancelled) setOptionsState({ operator, data: data?.has_rates ? data : null });
      })
      .catch(() => {
        if (!cancelled) setOptionsState({ operator, data: null });
      });
    return () => {
      cancelled = true;
    };
  }, [operator]);

  useEffect(() => {
    const loaded = (next) => {
      setProfile(next);
      setSavedProfile(next);
    };
    apiClient.get("/users/me/profile")
      .then(({ data }) => loaded(profileFromSaved(data)))
      .catch((err) => {
        const { status, data } = err.response ?? {};
        if (status === 404) {
          loaded(createEmptyProfile());
          return;
        }
        if (status === 409 && data?.detail?.profile) {
          // Profil w starszym formacie: wczytujemy, co jest, i oznaczamy pola do uzupełnienia.
          loaded(profileFromSaved(data.detail.profile));
          setMissingFields(data.detail.fields ?? []);
          return;
        }
        setLoadError(typeof data?.detail === "string" ? data.detail : "Nie udało się pobrać danych profilu.");
      })
      .finally(() => setIsLoading(false));
  }, []);

  const clearField = (key) => {
    setFieldErrors((current) => {
      if (!(key in current)) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
    setMissingFields((current) => current.filter((item) => item !== key));
    setSaveError(null);
    setSuccessMessage(null);
  };

  const update = (section, name, value) => {
    setProfile((current) => ({ ...current, [section]: { ...current[section], [name]: value } }));
    clearField(`${section}.${name}`);
  };

  const updateAddress = (name, value) => {
    update("base_info", name, value);
    lookupRef.current.key = null;
    setLookup(null);
  };

  const checkAddress = () => {
    const base = profile.base_info;
    const town = String(base.town ?? "").trim();
    const postalCode = POSTAL_CODE.test(base.postal_code ?? "") ? base.postal_code : "";
    if (!town && !postalCode) return;
    const key = `${postalCode}|${town}`;
    if (lookupRef.current.key === key) return;
    const id = lookupRef.current.id + 1;
    lookupRef.current = { key, id };
    setLookup({ status: "loading" });
    const params = { ...(town ? { town } : {}), ...(postalCode ? { postal_code: postalCode } : {}) };
    apiClient.get("/users/me/profile/address-lookup", { params })
      .then(({ data }) => {
        if (lookupRef.current.id !== id) return;
        // Pole uzupełnione automatycznie (z samego kodu albo samej miejscowości): komunikat idzie pod nie.
        const filled =
          data.status !== "found" ? null : !town && data.town ? "town" : !postalCode && data.postal_code ? "postal_code" : null;
        setLookup({ status: data.status, message: data.message, filled });
        setFieldErrors((current) => {
          const next = { ...current };
          delete next["base_info.town"];
          delete next["base_info.postal_code"];
          for (const [field, message] of Object.entries(data.errors ?? {})) next[`base_info.${field}`] = message;
          return next;
        });
        if (data.status === "found") {
          setProfile((current) => ({ ...current, base_info: withAddressLookup(current.base_info, data, { town, postalCode }) }));
        }
      })
      .catch(() => {
        if (lookupRef.current.id === id) setLookup({ status: "unavailable", message: LOOKUP_UNAVAILABLE });
      });
  };

  const checkAddressOnEnter = (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    checkAddress();
  };

  const optionsLoaded = optionsState.operator === operator;
  const options = optionsLoaded ? optionsState.data : null;
  const offeredTariffs = options ? options.tariffs.map((item) => item.code) : null;
  const offeredCycles = options ? options.billing_cycles : FALLBACK_CYCLES;
  const dynamicOffer = options?.dynamic_offer ?? null;

  const handleTariffChange = (tariffType) => {
    const dynamicGroups = dynamicOffer?.distribution_groups ?? [];
    setProfile((current) => ({
      ...current,
      consumption_and_tariff: {
        ...current.consumption_and_tariff,
        tariff_type: tariffType,
        // Oferta dynamiczna nie dla każdej grupy: przy grupie spoza oferty zostaje zwykła umowa.
        dynamic_price: Boolean(current.consumption_and_tariff.dynamic_price) && dynamicGroups.includes(tariffType),
      },
    }));
    clearField("consumption_and_tariff.tariff_type");
    clearField("consumption_and_tariff.dynamic_price");
  };

  const handleDynamicPriceChange = (event) => {
    const dynamicPrice = event.target.checked;
    // Umowa z ceną dynamiczną ma okres rozliczeniowy narzucony przez ofertę (zwykle 1 miesiąc).
    const offerCycle = dynamicOffer?.billing_cycle_months;
    setProfile((current) => ({
      ...current,
      base_info: dynamicPrice && offerCycle ? { ...current.base_info, billing_cycle: offerCycle } : current.base_info,
      consumption_and_tariff: { ...current.consumption_and_tariff, dynamic_price: dynamicPrice },
    }));
    clearField("consumption_and_tariff.dynamic_price");
    clearField("base_info.billing_cycle");
  };

  const handlePvModeChange = (mode) => {
    setProfile((current) => ({
      ...current,
      pv_config: {
        mode,
        type_of_price: current.pv_config.type_of_price ?? "RCE",
        installation: current.pv_config.installation ?? typicalInstallation(),
      },
    }));
    clearField("pv_config.mode");
  };

  const handleInstallationChange = (installation, keys) => {
    setProfile((current) => ({ ...current, pv_config: { ...current.pv_config, installation } }));
    keys.forEach(clearField);
  };

  const discardChanges = () => {
    setProfile(savedProfile);
    setFieldErrors({});
    setSaveError(null);
    setSuccessMessage(null);
    setLookup(null);
    lookupRef.current.key = null;
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSaveError(null);
    setSuccessMessage(null);
    const errors = validateProfile(profile, { offeredTariffs });
    setFieldErrors(errors);
    if (Object.keys(errors).length) {
      setScrollRequest((count) => count + 1);
      return;
    }

    setIsSaving(true);
    try {
      const response = await apiClient.put("/users/me/profile", toPayload(profile));
      const saved = profileFromSaved(response.data);
      setProfile(saved);
      setSavedProfile(saved);
      setLookup(null);
      setMissingFields([]);
      setSuccessMessage("Profil zapisany.");
      await refreshCurrentUser();
    } catch (err) {
      const { fields, message } = parseSaveError(err);
      setFieldErrors(fields);
      setSaveError(message);
      setScrollRequest((count) => count + 1);
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoading) return <div className="mx-auto max-w-4xl text-gray-500">Ładowanie profilu...</div>;
  if (loadError) return <div className="mx-auto max-w-4xl"><p className="rounded bg-red-50 p-3 text-red-700">{loadError}</p></div>;

  const { base_info: base, consumption_and_tariff: tariff, pv_config: pv } = profile;
  const currentTariff = tariff.tariff_type;
  const currentCycle = base.billing_cycle;
  const dynamicAllowed = Boolean(dynamicOffer?.distribution_groups.includes(currentTariff));
  const cycleFixedByOffer = Boolean(tariff.dynamic_price && dynamicOffer?.billing_cycle_months);
  const operatorName = OPERATORS.find(([value]) => value === operator)?.[1] ?? operator;

  // Wspólne właściwości pola: identyfikator, błąd i oznaczenie braku w starym profilu.
  const field = (key, extra = {}) => ({
    id: fieldId(key),
    label: FIELD_LABELS[key],
    error: fieldErrors[key],
    missing: missingFields.includes(key),
    ...extra,
  });

  const tariffOptions = offeredTariffs
    ? [
        ...options.tariffs.map((item) => ({ value: item.code, label: item.code, description: item.zones_description })),
        ...(offeredTariffs.includes(currentTariff)
          ? []
          : [{ value: currentTariff, label: currentTariff, warning: `Niedostępna u operatora ${operatorName}.` }]),
      ]
    : FALLBACK_TARIFFS.map((code) => ({ value: code, label: code }));
  const cycleOptions = [...offeredCycles, ...(offeredCycles.includes(currentCycle) ? [] : [currentCycle])].map((months) => ({
    value: months,
    label: cycleLabel(months),
    disabled: cycleFixedByOffer && months !== currentCycle,
  }));
  const yearOptions = BUILD_YEARS.includes(Number(base.year_of_construction)) || !base.year_of_construction
    ? BUILD_YEARS
    : [Number(base.year_of_construction), ...BUILD_YEARS];
  const errorList = Object.entries(fieldErrors);
  const failed = !isSaving && (errorList.length > 0 || Boolean(saveError));

  return (
    <div className="mx-auto max-w-4xl pb-12">
      <h2 className="text-xl font-bold text-gray-900">Profil użytkownika</h2>
      <p className="mb-6 mt-1 border-b border-gray-200 pb-4 text-sm text-gray-500">
        Dane do wyliczenia kosztów i porównania taryf.
      </p>

      {missingFields.length > 0 && (
        <div className="mb-4 rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          Profil wymaga uzupełnienia: {missingFields.map(fieldLabel).join(", ")}.
        </div>
      )}
      <div ref={errorSummaryRef} className="scroll-mt-4" />
      {saveError && <p role="alert" className="mb-4 rounded bg-red-50 p-3 text-sm text-red-700">{saveError}</p>}
      {errorList.length > 0 && (
        <div role="alert" className="mb-4 rounded bg-red-50 p-3 text-sm text-red-700">
          <p className="font-medium">Popraw pola:</p>
          <ul className="mt-1 list-disc pl-5">
            {errorList.map(([key, message]) => (
              <li key={key}><a className="underline" href={`#${fieldId(key)}`}>{fieldLabel(key)}</a>: {message}</li>
            ))}
          </ul>
        </div>
      )}

      <form onSubmit={handleSubmit} noValidate className="space-y-6">
        <Section title="Dom">
          <Field {...field("base_info.type_of_property")}>
            {(f) => (
              <select id={f.id} className={`${inputClass} ${f.borderClass}`} value={base.type_of_property} onChange={(e) => update("base_info", "type_of_property", e.target.value)}>
                {PROPERTY_TYPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            )}
          </Field>
          <Field {...field("base_info.year_of_construction")}>
            {(f) => (
              <select id={f.id} className={`${inputClass} ${f.borderClass}`} value={base.year_of_construction} aria-invalid={f.invalid} aria-describedby={f.describedBy} onChange={(e) => update("base_info", "year_of_construction", e.target.value)}>
                <option value="">Wybierz rok</option>
                {yearOptions.map((year) => <option key={year} value={year}>{year}</option>)}
              </select>
            )}
          </Field>
          <Field {...field("base_info.heating_area_m2", { hint: "Bez nieogrzewanych pomieszczeń, np. garażu." })}>
            {(f) => <UnitInput field={f} unit="m²" placeholder="np. 120" value={base.heating_area_m2} onChange={(value) => update("base_info", "heating_area_m2", value)} />}
          </Field>
          <Field {...field("base_info.number_of_residents", { group: true })}>
            {(f) => <Stepper field={f} value={base.number_of_residents} onChange={(value) => update("base_info", "number_of_residents", value)} />}
          </Field>
          <Field {...field("base_info.town", { notice: lookup?.filled === "town" ? lookup.message : null })}>
            {(f) => (
              <input
                id={f.id}
                className={`${inputClass} ${f.borderClass}`}
                autoComplete="address-level2"
                value={base.town}
                aria-invalid={f.invalid}
                aria-describedby={f.describedBy}
                onChange={(e) => updateAddress("town", e.target.value)}
                onBlur={checkAddress}
                onKeyDown={checkAddressOnEnter}
              />
            )}
          </Field>
          <Field {...field("base_info.postal_code", { notice: lookup?.filled === "postal_code" ? lookup.message : null })}>
            {(f) => (
              <input
                id={f.id}
                className={`${inputClass} ${f.borderClass}`}
                inputMode="numeric"
                autoComplete="postal-code"
                placeholder="00-000"
                maxLength={6}
                value={base.postal_code}
                aria-invalid={f.invalid}
                aria-describedby={f.describedBy}
                onChange={(e) => updateAddress("postal_code", formatPostalCode(e.target.value))}
                onBlur={checkAddress}
                onKeyDown={checkAddressOnEnter}
              />
            )}
          </Field>
          <HomeLocationField
            id={fieldId("base_info.location")}
            base={base}
            lookup={lookup?.filled ? { ...lookup, message: null } : lookup}
            error={fieldErrors["base_info.location"]}
            onChange={(location) => update("base_info", "location", location)}
          />
        </Section>

        <Section title="Przyłącze i rozliczenie" description="Dane z faktury za prąd.">
          <Field {...field("base_info.distribution_operator", { hint: "Podany na fakturze w części za dystrybucję." })}>
            {(f) => (
              <select id={f.id} className={`${inputClass} ${f.borderClass}`} value={base.distribution_operator} aria-describedby={f.describedBy} onChange={(e) => update("base_info", "distribution_operator", e.target.value)}>
                {OPERATORS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            )}
          </Field>
          <Field {...field("base_info.phase_type", { group: true, hint: "Podana na fakturze lub na liczniku." })}>
            {(f) => (
              <div id={f.id}>
                <SegmentedControl
                  label={FIELD_LABELS["base_info.phase_type"]}
                  options={[{ value: "1_phase", label: "1 faza" }, { value: "3_phase", label: "3 fazy" }]}
                  value={base.phase_type}
                  onChange={(value) => update("base_info", "phase_type", value)}
                />
              </div>
            )}
          </Field>
          <Field {...field("base_info.contracted_power_kw", { hint: "Faktura, dane punktu poboru: „Moc umowna”." })}>
            {(f) => <UnitInput field={f} unit="kW" placeholder="np. 11" value={base.contracted_power_kw} onChange={(value) => update("base_info", "contracted_power_kw", value)} />}
          </Field>
          <Field
            {...field("base_info.billing_cycle", {
              group: true,
              hint: cycleFixedByOffer
                ? `Oferta z ceną dynamiczną rozlicza się co ${dynamicOffer.billing_cycle_months} mies.`
                : "Długość okresu rozliczeniowego z faktury.",
            })}
            error={fieldErrors["base_info.billing_cycle"] ?? (options && !offeredCycles.includes(currentCycle) && !cycleFixedByOffer
              ? `Ten operator nie oferuje cyklu ${currentCycle} mies. Dostępne: ${offeredCycles.join(", ")}.`
              : undefined)}
          >
            {(f) => (
              <div id={f.id}>
                <SegmentedControl
                  label={FIELD_LABELS["base_info.billing_cycle"]}
                  options={cycleOptions}
                  value={currentCycle}
                  onChange={(value) => update("base_info", "billing_cycle", value)}
                />
              </div>
            )}
          </Field>
          <Field {...field("base_info.billing_period_start_date", { hint: "Data „od” okresu rozliczeniowego z ostatniej faktury." })}>
            {(f) => <input id={f.id} type="date" className={`${inputClass} ${f.borderClass}`} value={base.billing_period_start_date} aria-invalid={f.invalid} aria-describedby={f.describedBy} onChange={(e) => update("base_info", "billing_period_start_date", e.target.value)} />}
          </Field>
        </Section>

        <Section title="Taryfa" description={`Grupa taryfowa z faktury, np. G11 lub G12w. Lista obejmuje taryfy ${operatorName} dostępne w kalkulatorze.`}>
          <Field {...field("consumption_and_tariff.tariff_type", { group: true, wide: true })}>
            {(f) => !optionsLoaded
              ? <p className="text-gray-500">Ładowanie taryf operatora...</p>
              : (
                <ChoiceCards
                  field={f}
                  name="tariff_type"
                  options={tariffOptions}
                  value={currentTariff}
                  onChange={handleTariffChange}
                  columns="sm:grid-cols-2 lg:grid-cols-3"
                />
              )}
          </Field>
          {optionsLoaded && options?.unsupported?.length > 0 && (
            <p className="text-xs text-gray-500 sm:col-span-2">
              U tego operatora są też: {options.unsupported.map((item, index) => <span key={item.code}>{index > 0 && ", "}<span title={item.reason} className="cursor-help underline decoration-dotted">{item.code}</span></span>)}. Jeszcze ich nie liczymy.
            </p>
          )}
          {optionsLoaded && !options && (
            <p className="text-xs text-gray-500 sm:col-span-2">Brak cennika tego operatora w kalkulatorze.</p>
          )}
          {dynamicOffer && (
            <Field {...field("consumption_and_tariff.dynamic_price", { wide: true, group: true, label: "Rodzaj umowy na energię" })}>
              {(f) => (
                <>
                  <label className="flex items-start gap-2 font-medium text-gray-700">
                    <input id={f.id} type="checkbox" className="mt-0.5 accent-emerald-600" checked={Boolean(tariff.dynamic_price)} onChange={handleDynamicPriceChange} disabled={!dynamicAllowed && !tariff.dynamic_price} />
                    Umowa z ceną dynamiczną ({dynamicOffer.name})
                  </label>
                  {tariff.dynamic_price && dynamicAllowed && (
                    <p className="mt-2 text-xs text-gray-500">
                      Energia po cenie z każdego kwadransa (cena rynkowa + marża sprzedawcy), dystrybucja według grupy {currentTariff}.
                      {dynamicOffer.billing_cycle_months && ` Oferta rozlicza się co ${dynamicOffer.billing_cycle_months} mies.`}
                    </p>
                  )}
                  {!dynamicAllowed && (
                    <p className={`mt-2 text-xs ${tariff.dynamic_price ? "text-amber-700" : "text-gray-500"}`}>
                      Oferta z ceną dynamiczną obejmuje grupy: {dynamicOffer.distribution_groups.join(", ")}.
                    </p>
                  )}
                </>
              )}
            </Field>
          )}
        </Section>

        <Section title="Fotowoltaika" description="Rozliczenie energii oddanej do sieci i panele do prognozy produkcji.">
          <Field {...field("pv_config.mode", { group: true, wide: true })}>
            {(f) => <ChoiceCards field={f} name="pv_mode" options={PV_MODES} value={pv.mode} onChange={handlePvModeChange} columns="sm:grid-cols-3" />}
          </Field>
          {pv.mode === "net_billing" && (
            <Field {...field("pv_config.type_of_price", { group: true, wide: true, hint: "Podana w umowie prosumenckiej." })}>
              {(f) => <ChoiceCards field={f} name="type_of_price" options={PRICE_TYPES} value={pv.type_of_price ?? "RCE"} onChange={(value) => update("pv_config", "type_of_price", value)} />}
            </Field>
          )}
          {pv.mode !== "none" && pv.installation && (
            <PvInstallationFields
              installation={pv.installation}
              netMetering={pv.mode === "net_metering"}
              field={field}
              onChange={handleInstallationChange}
            />
          )}
        </Section>

        <div
          className={`sticky bottom-0 z-10 flex flex-col gap-3 rounded-xl border bg-white px-4 py-3 shadow-lg sm:flex-row sm:items-center sm:justify-between ${
            dirty ? "border-amber-300" : "border-gray-200"
          }`}
        >
          <p role="status" className="flex items-center gap-1.5 text-sm font-medium">
            {failed
              ? <span className="flex items-center gap-1.5 text-red-600"><FiAlertCircle aria-hidden="true" />Nie zapisano – popraw błędy powyżej.</span>
              : dirty
                ? <span className="flex items-center gap-1.5 text-amber-700"><span aria-hidden="true" className="h-2 w-2 rounded-full bg-amber-500" />Masz niezapisane zmiany.</span>
                : successMessage
                  ? <span className="flex items-center gap-1.5 text-emerald-700"><FiCheckCircle aria-hidden="true" />{successMessage}</span>
                  : <span className="text-gray-500">Wszystkie zmiany są zapisane.</span>}
          </p>
          <div className="flex gap-2">
            {dirty && (
              <button type="button" onClick={discardChanges} disabled={isSaving} className="flex-1 rounded-md border border-gray-300 px-4 py-2.5 font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 sm:flex-none">
                Cofnij zmiany
              </button>
            )}
            <button className="flex-1 rounded-md bg-emerald-600 px-5 py-2.5 font-semibold text-white hover:bg-emerald-700 disabled:opacity-50 sm:flex-none" disabled={isSaving}>
              {isSaving ? "Zapisywanie..." : "Zapisz profil"}
            </button>
          </div>
        </div>
      </form>

      {me?.email && <DeleteAccount email={me.email} />}
    </div>
  );
}

export default ProfilePage;
