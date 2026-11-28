import { useEffect, useRef, useState } from "react";
import { FiCheckCircle, FiPlus, FiRotateCcw, FiTrash2 } from "react-icons/fi";
import { Link, useNavigate } from "react-router-dom";
import apiClient from "../api/client";
import DayPlanView, { FlatTariffNote } from "../components/DayPlanView";
import PastDayPlanner from "../components/PastDayPlanner";
import SegmentedControl from "../components/SegmentedControl";
import { useCurrentUser } from "../hooks/useCurrentUser";
import { noPricesFrom } from "../utils/dayPlan";
import { getApiErrorMessage } from "../utils/energyFiles";
import { formatDayMonth } from "../utils/schedule";
import { DEVICE_TYPE_LABELS } from "../utils/home";
import {
  MAX_WINDOWS,
  afterOptions,
  chainRoot,
  crossesMidnight,
  durationText,
  earliestStart,
  energyNeeded,
  errorsFromResponse,
  nextReadyTime,
  nextWindow,
  orderError,
  sameWindows,
  toPayload,
  validateDevice,
  windowsText,
} from "../utils/planning";
import { formatDateTime, formatKwh } from "../utils/format";
import { CARD, LINK_BUTTON, alertClass, buttonClass } from "../components/uiStyles";

const savedAtText = formatDateTime;

// Plan układa pracę w kwadransach, więc mówimy o tym przed wpisaniem godziny, a nie dopiero w błędzie.
const QUARTER_HINT = "Godziny co 15 minut, np. 08:00, 08:15, 08:30.";

const INPUT = "border border-gray-300 rounded px-2 py-1.5 text-sm bg-white focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500";

function FieldError({ message }) {
  return message ? <p className="mt-1 text-xs text-red-600">{message}</p> : null;
}

function WindowsEditor({ device, windows, error, onChange }) {
  const update = (index, field, value) =>
    onChange(windows.map((window, position) => (position === index ? { ...window, [field]: value } : window)));

  return (
    <div>
      <p className="text-sm font-medium text-gray-700">{device.is_ev ? "Kiedy auto jest podłączone" : "Kiedy może pracować"}</p>
      <p className="text-xs text-gray-500">{QUARTER_HINT}</p>
      <ul className="mt-2 space-y-2">
        {windows.map((window, index) => (
          <li key={index} className="flex flex-wrap items-center gap-2 text-sm">
            <input
              type="time"
              step={900}
              className={INPUT}
              aria-label={`${device.device_name}: od (przedział ${index + 1})`}
              value={window.start}
              onChange={(event) => update(index, "start", event.target.value)}
            />
            <span aria-hidden="true">–</span>
            <input
              type="time"
              step={900}
              className={INPUT}
              aria-label={`${device.device_name}: do (przedział ${index + 1})`}
              value={window.end}
              onChange={(event) => update(index, "end", event.target.value)}
            />
            {crossesMidnight(window) && <span className="text-xs text-gray-500">do rana następnego dnia</span>}
            {windows.length > 1 && (
              <button
                type="button"
                className="p-1.5 text-gray-400 hover:text-red-600"
                aria-label={`Usuń przedział ${index + 1}: ${device.device_name}`}
                onClick={() => onChange(windows.filter((_, position) => position !== index))}
              >
                <FiTrash2 aria-hidden="true" />
              </button>
            )}
          </li>
        ))}
      </ul>
      <FieldError message={error} />
      <div className="mt-2 flex flex-wrap gap-4">
        <button
          type="button"
          className={LINK_BUTTON}
          disabled={windows.length >= MAX_WINDOWS}
          onClick={() => onChange([...windows, nextWindow(windows)])}
        >
          <FiPlus aria-hidden="true" /> Dodaj przedział
        </button>
        {!sameWindows(windows, device.default_windows) && (
          <button type="button" className={LINK_BUTTON} onClick={() => onChange(device.default_windows)}>
            <FiRotateCcw aria-hidden="true" /> Przywróć z pliku ({windowsText(device.default_windows)})
          </button>
        )}
      </div>
    </div>
  );
}

const ENERGY_INPUTS = [
  { value: "percent", label: "poziom baterii" },
  { value: "kwh", label: "kWh" },
];

function EvEnergy({ device, preference, errors, efficiency, onChange }) {
  const levels = preference.energy_input === "percent";
  const energy = energyNeeded(preference, efficiency);
  // Stała szerokość pola: komunikat błędu zawija się pod polem zamiast rozpychać sąsiednie pola.
  const field = (name, label, unit, props = {}) => (
    <label className="w-40 shrink-0 text-sm text-gray-700">
      <span className="block font-medium mb-1">{label}</span>
      <span className="flex items-center gap-1.5">
        <input
          type="number"
          inputMode="decimal"
          className={`${INPUT} w-24`}
          aria-label={label}
          value={preference[name] ?? ""}
          onChange={(event) => onChange({ [name]: event.target.value })}
          {...props}
        />
        <span className="text-gray-500">{unit}</span>
      </span>
      <FieldError message={errors[name]} />
    </label>
  );

  return (
    <div className="space-y-3">
      <fieldset className="text-sm text-gray-700">
        <legend className="font-medium mb-1">Ile naładować</legend>
        <div className="flex flex-wrap gap-4">
          {ENERGY_INPUTS.map((option) => (
            <label key={option.value} className="inline-flex items-center gap-1.5">
              <input
                type="radio"
                name={`energy_input_${device.device_id}`}
                className="accent-emerald-600"
                checked={preference.energy_input === option.value}
                onChange={() => onChange({ energy_input: option.value })}
              />
              {option.label}
            </label>
          ))}
        </div>
      </fieldset>
      <div className="flex flex-wrap gap-4">
        {levels ? (
          <>
            {field("current_percent", "Teraz w baterii", "%", { min: 0, max: 100, step: 1 })}
            {field("target_percent", "Naładuj do", "%", { min: 0, max: 100, step: 1 })}
            {field("battery_kwh", "Pojemność baterii", "kWh", { min: 1, max: 200, step: 0.1 })}
          </>
        ) : (
          field("energy_kwh", "Energia", "kWh", { min: 0.1, max: 200, step: 0.1 })
        )}
      </div>
      {levels && energy != null && (
        <p className="text-xs text-gray-600">
          Z sieci auto pobierze ok. {formatKwh(energy)} (z uwzględnieniem ok.{" "}
          {Math.round((1 - efficiency) * 100)}% strat ładowania).
        </p>
      )}
    </div>
  );
}

const AUTO_KINDS = new Set(["heat_pump", "water_heater"]);
const DEFAULT_INDOOR_C = 21;
const INDOOR_OPTIONS = [18, 19, 20, 21, 22, 23, 24];

// Godziny „woda gotowa na”: bojler wymaga co najmniej jednej, pompa ciepła może nie mieć żadnej.
function ReadyTimesEditor({ device, times, error, required, onChange }) {
  const setTime = (index, value) => onChange(times.map((time, position) => (position === index ? value : time)));
  return (
    <>
      <ul className="mt-2 flex flex-wrap gap-3">
        {times.map((time, index) => (
          <li key={index} className="flex items-center gap-1">
            <input
              type="time"
              step={900}
              className={INPUT}
              aria-label={`${device.device_name}: woda gotowa na (${index + 1})`}
              value={time}
              onChange={(event) => setTime(index, event.target.value)}
            />
            {(times.length > 1 || !required) && (
              <button
                type="button"
                className="p-1.5 text-gray-400 hover:text-red-600"
                aria-label={`Usuń godzinę ${index + 1}: ${device.device_name}`}
                onClick={() => onChange(times.filter((_, position) => position !== index))}
              >
                <FiTrash2 aria-hidden="true" />
              </button>
            )}
          </li>
        ))}
      </ul>
      <FieldError message={error} />
      <button
        type="button"
        className={`${LINK_BUTTON} mt-2`}
        disabled={times.length >= MAX_WINDOWS}
        onClick={() => onChange([...times, nextReadyTime(times)])}
      >
        <FiPlus aria-hidden="true" /> Dodaj godzinę
      </button>
    </>
  );
}

// Pompa ciepła i bojler (ZP-112): bez przedziałów i programów, energia z historii zużycia w plikach.
function AutoDeviceCard({ device, preference, errors, hasWaterHeater, onChange }) {
  const typeLabel = DEVICE_TYPE_LABELS[device.device_type] ?? device.device_category;
  const times = preference.ready_times ?? [];
  const setTimes = (value) => onChange({ ready_times: value });

  return (
    <section className={CARD} aria-label={device.device_name} data-has-error={Object.keys(errors).length ? "" : undefined}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold text-gray-900">{device.device_name}</h3>
          <p className="text-xs text-gray-500">
            {typeLabel} ·{" "}
            {device.kind === "water_heater"
              ? device.hot_water_source === "history"
                ? "ile ciepłej wody zużywacie, bierzemy z historii"
                : `ciepłą wodę liczymy dla ${device.residents} ${device.residents === 1 ? "osoby" : "osób"} z profilu`
              : "plan trzyma temperaturę w domu według prognozy pogody"}
          </p>
        </div>
        <label className="inline-flex items-center gap-2 text-sm font-medium text-gray-700">
          <input
            type="checkbox"
            className="h-4 w-4 accent-emerald-600"
            checked={preference.enabled}
            onChange={(event) => onChange({ enabled: event.target.checked })}
          />
          Planuj automatycznie
        </label>
      </div>

      {preference.enabled && device.kind === "heat_pump" && (
        <div className="mt-4 space-y-4 text-sm text-gray-700">
          <label className="block">
            <span className="block font-medium mb-1">Temperatura w domu</span>
            <select
              className={`${INPUT} w-full sm:w-auto`}
              value={preference.indoor_temp_c ?? DEFAULT_INDOOR_C}
              onChange={(event) => onChange({ indoor_temp_c: Number(event.target.value) })}
            >
              {INDOOR_OPTIONS.map((degrees) => (
                <option key={degrees} value={degrees}>
                  {degrees}°C{degrees === DEFAULT_INDOOR_C ? " (jak zwykle)" : ""}
                </option>
              ))}
            </select>
            <span className="mt-1 block text-xs text-gray-500">
              Plan trzyma w domu tę temperaturę (± 1°C), a grzeje głównie w tańszych godzinach.
            </span>
            <FieldError message={errors.indoor_temp_c} />
          </label>
          {!hasWaterHeater && (
          <div>
            <p className="font-medium">Ciepła woda z pompy gotowa na</p>
            <p className="text-xs text-gray-500">
              Pompa nagrzeje wodę w zasobniku na te godziny, kiedy prąd jest tani.{" "}
              {times.length ? QUARTER_HINT : "Bez godzin woda będzie gotowa na 6:00 i 18:00."}
            </p>
            <ReadyTimesEditor device={device} times={times} error={errors.ready_times} onChange={setTimes} />
          </div>
          )}
        </div>
      )}

      {preference.enabled && device.kind === "water_heater" && (
        <div className="mt-4 text-sm text-gray-700">
          {device.tank_liters_from_file ? (
            <p className="mb-4">
              <span className="font-medium">Pojemność zbiornika:</span> {device.tank_liters_from_file} l
              <span className="text-xs text-gray-500"> (z pliku urządzeń)</span>
            </p>
          ) : (
          <label className="block mb-4">
            <span className="block font-medium mb-1">Pojemność zbiornika</span>
            <span className="flex items-center gap-1.5">
              <input
                type="number"
                inputMode="numeric"
                min={30}
                max={500}
                step={10}
                className={`${INPUT} w-24`}
                aria-label="Pojemność zbiornika"
                value={preference.tank_liters ?? ""}
                onChange={(event) => onChange({ tank_liters: event.target.value })}
              />
              <span className="text-gray-500">l</span>
            </span>
            <span className="mt-1 block text-xs text-gray-500">
              W większym zbiorniku zmieści się więcej wody nagrzanej na zapas.
            </span>
            <FieldError message={errors.tank_liters} />
          </label>
          )}
          <p className="font-medium">Woda gotowa na</p>
          <p className="text-xs text-gray-500">
            O tych godzinach woda będzie gorąca, a poza nimi nigdy zimna. Plan nagrzeje ją na zapas, kiedy prąd jest
            tani. {QUARTER_HINT}
          </p>
          <ReadyTimesEditor device={device} times={times} error={errors.ready_times} required onChange={setTimes} />
        </div>
      )}
    </section>
  );
}

function DeviceCard({ device, preference, errors, efficiency, afterGapMin, afterChoices, chainStart, onChange }) {
  const typeLabel = DEVICE_TYPE_LABELS[device.device_type] ?? device.device_category;
  const program = device.programs.find((item) => item.program_id === preference.program_id);
  const after = afterChoices.find((item) => item.device_id === preference.after_device_id);
  const rootStart = chainStart ? earliestStart(chainStart.preference.windows) : null;

  return (
    <section className={CARD} aria-label={device.device_name} data-has-error={Object.keys(errors).length ? "" : undefined}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold text-gray-900">{device.device_name}</h3>
          <p className="text-xs text-gray-500">
            {typeLabel} · {device.flexibility_mode === "interruptible" ? "pracę można dzielić" : "start można przesunąć"}
          </p>
        </div>
        <label className="inline-flex items-center gap-2 text-sm font-medium text-gray-700">
          <input
            type="checkbox"
            className="h-4 w-4 accent-emerald-600"
            checked={preference.enabled}
            onChange={(event) =>
              onChange({
                enabled: event.target.checked,
                // Po zaznaczeniu od razu pierwszy program, żeby nie trzeba go było wybierać za każdym razem.
                ...(event.target.checked && !preference.program_id && device.programs.length
                  ? { program_id: device.programs[0].program_id }
                  : {}),
              })
            }
          />
          Pracuje jutro
        </label>
      </div>

      {preference.enabled && (
        <div className="mt-4 space-y-4">
          {device.programs.length > 0 && (
            <label className="block text-sm text-gray-700">
              <span className="block font-medium mb-1">Program</span>
              <select
                className={`${INPUT} w-full sm:w-auto`}
                value={preference.program_id ?? ""}
                onChange={(event) => onChange({ program_id: event.target.value })}
              >
                <option value="">Wybierz program</option>
                {device.programs.map((item) => (
                  <option key={item.program_id} value={item.program_id}>
                    {item.program_name} ({durationText(item.duration_min)})
                  </option>
                ))}
              </select>
              <FieldError message={errors.program_id} />
            </label>
          )}
          {afterChoices.length > 0 && (
            <label className="block text-sm text-gray-700">
              <span className="block font-medium mb-1">Wykonaj po</span>
              <select
                className={`${INPUT} w-full sm:w-auto`}
                value={preference.after_device_id ?? ""}
                onChange={(event) => onChange({ after_device_id: event.target.value || null })}
              >
                <option value="">Nie czeka na inne urządzenie</option>
                {afterChoices.map((item) => (
                  <option key={item.device_id} value={item.device_id}>{item.device_name}</option>
                ))}
              </select>
              {after && (
                <span className="mt-1 block text-xs text-gray-500">
                  Ruszy po końcu: {after.device_name}, najwyżej {durationText(afterGapMin)} później.
                </span>
              )}
              <FieldError message={errors.after_device_id} />
            </label>
          )}
          {after ? (
            <label className="block text-sm text-gray-700">
              <span className="block font-medium mb-1">Skończ najpóźniej o</span>
              <input
                type="time"
                step={900}
                className={INPUT}
                value={preference.finish_by ?? ""}
                onChange={(event) => onChange({ finish_by: event.target.value || null })}
              />
              <span className="mt-1 block text-xs text-gray-500">
                Opcjonalnie, np. żeby nie hałasowało w nocy. {QUARTER_HINT}
                {chainStart && rootStart && (
                  <>
                    {" "}Godzina wcześniejsza niż {rootStart} (start urządzenia {chainStart.device_name}) oznacza rano
                    następnego dnia.
                  </>
                )}
              </span>
              <FieldError message={errors.finish_by} />
            </label>
          ) : (
            <WindowsEditor
              device={device}
              windows={preference.windows}
              error={errors.windows}
              onChange={(windows) => onChange({ windows })}
            />
          )}
          {program && !after && (
            <p className="text-xs text-gray-500">
              Program trwa {durationText(program.duration_min)} i musi zmieścić się w jednym przedziale.
            </p>
          )}
          {device.is_ev && (
            <EvEnergy device={device} preference={preference} errors={errors} efficiency={efficiency} onChange={onChange} />
          )}
        </div>
      )}
    </section>
  );
}

// Plan na jutro (ZP-111, ZP-112): ustawienia urządzeń z plików użytkownika, a po zapisie najtańszy plan pracy
// na jutro. Dla każdego zalogowanego; ustawienia zostają do następnego zapisu, który je nadpisuje.
function PlanningPage() {
  const [data, setData] = useState(null);
  const [devices, setDevices] = useState([]);
  const [plan, setPlan] = useState(null);
  const [view, setView] = useState("form");
  // „Jutro” albo plan idealny wybranego dnia z przeszłości (ZP-152), który ma swój widok.
  const [mode, setMode] = useState("tomorrow");
  const [pastDay, setPastDay] = useState(null);
  const [errors, setErrors] = useState({});
  const [loadError, setLoadError] = useState(null);
  const [saveError, setSaveError] = useState(null);
  // Plan wymaga uzupełnionego profilu (operator, taryfa): wtedy przy błędzie link do profilu.
  const [needsProfile, setNeedsProfile] = useState(false);
  const [isReplanning, setIsReplanning] = useState(false);
  const [noPrices, setNoPrices] = useState(null);
  // Brak cen na jutro przy „Ułóż plan na jutro” z widoku planu demo: komunikat w planie zamiast powrotu do
  // formularza, który znów proponowałby plan demo (pętla).
  const [replanNote, setReplanNote] = useState(null);
  const [saved, setSaved] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [approveError, setApproveError] = useState(null);
  const [isStartingRun, setIsStartingRun] = useState(false);
  const [runError, setRunError] = useState(null);
  const { me } = useCurrentUser();
  const navigate = useNavigate();
  const [scrollRequest, setScrollRequest] = useState(0);
  const formRef = useRef(null);
  const topRef = useRef(null);

  // Po nieudanym zapisie przewijamy do pierwszej karty z błędem (przy wielu urządzeniach może być poza ekranem).
  useEffect(() => {
    if (scrollRequest) formRef.current?.querySelector("[data-has-error]")?.scrollIntoView?.({ behavior: "smooth", block: "center" });
  }, [scrollRequest]);

  const apply = (body) => {
    setData(body);
    setDevices(body.devices);
  };

  const showPlan = (body) => {
    setPlan(body);
    setView("plan");
    setNoPrices(null);
    setApproveError(null);
    topRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  };

  useEffect(() => {
    // Ostatni plan jest dodatkiem: gdy nie da się go odczytać, ustawienia i tak muszą się pokazać.
    const current = apiClient.get("/planning/plans/current").catch(() => ({ data: null }));
    Promise.all([apiClient.get("/planning/preferences"), current])
      .then(([{ data: body }, { data: current }]) => {
        apply(body);
        setPlan(current);
        // Plan ułożony po ostatnim zapisie ustawień jest aktualny: pokazujemy go od razu.
        if (current && (!body.saved_at || new Date(current.created_at) >= new Date(body.saved_at))) setView("plan");
      })
      .catch((err) => setLoadError(getApiErrorMessage(err, "Nie udało się pobrać ustawień planu.")));
  }, []);

  const efficiency = data?.charging_efficiency ?? 0.9;
  const afterGapMin = data?.after_max_gap_min ?? 60;
  const changeDevice = (deviceId, change) => {
    setDevices((current) =>
      current.map((device) =>
        device.device_id === deviceId ? { ...device, preference: { ...device.preference, ...change } } : device,
      ),
    );
    setErrors((current) => ({ ...current, [deviceId]: {} }));
    setSaved(false);
    setSaveError(null);
  };

  const createPlan = async (planDate = null, { keepPlan = false } = {}) => {
    setNeedsProfile(false);
    setReplanNote(null);
    try {
      const { data: body } = await apiClient.post("/planning/plans", planDate ? { plan_date: planDate } : {});
      if (body.kind === "past_day") {
        // Plan demo na dzień z przeszłości to plan idealny: pokazujemy go w widoku wybranego dnia.
        setPastDay(body.plan_date);
        setMode("past");
        setNoPrices(null);
        return;
      }
      showPlan(body);
    } catch (err) {
      const missing = noPricesFrom(err);
      if (missing && keepPlan) {
        setReplanNote(missing.message);
        return;
      }
      // Błąd pokazujemy przy przycisku zapisu, także gdy plan układaliśmy z widoku planu.
      setView("form");
      if (missing) {
        setNoPrices(missing);
        return;
      }
      const detail = err?.response?.data?.detail;
      const status = err?.response?.status;
      setNeedsProfile(typeof detail === "string" && (status === 409 || detail.startsWith("Brak stawek")));
      setSaveError(getApiErrorMessage(err, "Ustawienia są zapisane, ale nie udało się ułożyć planu."));
    }
  };

  const replan = async () => {
    setIsReplanning(true);
    setSaveError(null);
    try {
      await createPlan(null, { keepPlan: true });
    } finally {
      setIsReplanning(false);
    }
  };

  const save = async (event) => {
    event.preventDefault();
    const found = Object.fromEntries(
      devices
        .map((device) => {
          const deviceErrors = validateDevice(device, device.preference, efficiency);
          const order = orderError(devices, device);
          return [device.device_id, order ? { ...deviceErrors, after_device_id: order } : deviceErrors];
        })
        .filter(([, deviceErrors]) => Object.keys(deviceErrors).length),
    );
    setErrors(found);
    setSaved(false);
    setSaveError(null);
    setNoPrices(null);
    if (Object.keys(found).length) {
      setScrollRequest((count) => count + 1);
      return;
    }

    setIsSaving(true);
    try {
      const { data: body } = await apiClient.put("/planning/preferences", toPayload(devices));
      apply(body);
      setSaved(true);
      await createPlan();
    } catch (err) {
      const fieldErrors = errorsFromResponse(err, devices);
      if (fieldErrors) {
        setErrors(fieldErrors);
        setScrollRequest((count) => count + 1);
      }
      else setSaveError(getApiErrorMessage(err, "Nie udało się zapisać ustawień."));
    } finally {
      setIsSaving(false);
    }
  };

  const demo = async () => {
    setIsSaving(true);
    try {
      await createPlan(noPrices.latest_price_date);
    } finally {
      setIsSaving(false);
    }
  };

  const approve = async () => {
    setIsApproving(true);
    setApproveError(null);
    try {
      const { data: body } = await apiClient.post(`/planning/plans/${plan.id}/approve`);
      setPlan(body);
    } catch (err) {
      setApproveError(getApiErrorMessage(err, "Nie udało się zatwierdzić planu."));
    } finally {
      setIsApproving(false);
    }
  };

  // Zatwierdzony plan trafia do symulacji domu; jego przebieg widać na ekranie „Mój dom”.
  const startRun = async () => {
    setIsStartingRun(true);
    setRunError(null);
    try {
      await apiClient.post("/home/plan-runs", { plan_id: plan.id });
      navigate("/home");
    } catch (err) {
      setRunError(getApiErrorMessage(err, "Nie udało się uruchomić planu w symulacji."));
      setIsStartingRun(false);
    }
  };

  const hasErrors = Object.values(errors).some((deviceErrors) => Object.keys(deviceErrors ?? {}).length);
  const scheduled = devices.filter((device) => !AUTO_KINDS.has(device.kind));
  const automatic = devices.filter((device) => AUTO_KINDS.has(device.kind));
  // W domu z bojlerem wodę grzeje bojler, więc przy pompie nie pytamy o godziny ciepłej wody.
  const hasWaterHeater = devices.some((device) => device.kind === "water_heater");
  const card = (device) => {
    const shared = {
      device,
      preference: device.preference,
      errors: errors[device.device_id] ?? {},
      onChange: (change) => changeDevice(device.device_id, change),
    };
    return AUTO_KINDS.has(device.kind)
      ? <AutoDeviceCard key={device.device_id} {...shared} hasWaterHeater={hasWaterHeater} />
      : (
        <DeviceCard
          key={device.device_id}
          {...shared}
          efficiency={efficiency}
          afterGapMin={afterGapMin}
          afterChoices={afterOptions(devices, device)}
          chainStart={device.preference.after_device_id ? chainRoot(devices, device) : null}
        />
      );
  };

  return (
    <div className="max-w-4xl mx-auto pb-12">
      <h2 ref={topRef} className="text-xl font-bold text-gray-900">Plan na jutro</h2>
      <div className="mt-1 mb-6 flex flex-col gap-3 border-b border-gray-200 pb-4 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-gray-500">
          {mode === "tomorrow"
            ? "Zaznacz, co ma jutro pracować i kiedy. Ułożymy najtańszy plan, a ustawienia zapamiętamy."
            : "Wybierz dzień z przeszłości. Plan idealny użyje tych samych ustawień urządzeń co plan na jutro."}
        </p>
        <SegmentedControl
          label="Dzień planu"
          options={[{ value: "tomorrow", label: "Jutro" }, { value: "past", label: "Wybrany dzień" }]}
          value={mode}
          onChange={setMode}
        />
      </div>

      {loadError && <p className={alertClass("error")} role="alert">{loadError}</p>}
      {!data && !loadError && <p className="text-sm text-gray-500" role="status">Ładowanie ustawień…</p>}

      {data && mode === "past" && (
        <PastDayPlanner
          flatTariff={data.flat_tariff}
          canRun={Boolean(me?.home_owner)}
          initialDay={pastDay}
          onEditSettings={() => {
            setMode("tomorrow");
            setView("form");
          }}
        />
      )}

      {data && mode === "tomorrow" && view === "plan" && plan && (
        <DayPlanView
          plan={plan}
          flatTariff={data.flat_tariff}
          onApprove={approve}
          onEdit={() => setView("form")}
          onReplan={replan}
          replanNote={replanNote}
          isApproving={isApproving}
          isReplanning={isReplanning}
          approveError={approveError}
          onRun={me?.home_owner ? startRun : null}
          isStartingRun={isStartingRun}
          runError={runError}
        />
      )}

      {data && mode === "tomorrow" && view === "form" && (
        <form ref={formRef} onSubmit={save} noValidate className="space-y-4">
          {!devices.length && (
            <p className={`${CARD} text-sm text-gray-600`}>
              W Twoich plikach nie ma urządzeń, które da się planować. Zaimportuj plik urządzeń z pralką, zmywarką,
              ładowarką EV, pompą ciepła albo bojlerem.
            </p>
          )}
          {scheduled.map(card)}
          {automatic.length > 0 && (
            <>
              <div className="pt-2">
                <h3 className="font-semibold text-gray-900">Ogrzewanie i ciepła woda</h3>
                <p className="text-sm text-gray-500">
                  Te urządzenia planujemy same, nie trzeba podawać godzin pracy.
                </p>
              </div>
              {automatic.map(card)}
            </>
          )}

          {data.flat_tariff && <FlatTariffNote />}

          {noPrices && (
            <div className={`${alertClass("warning")} space-y-2`} role="alert">
              <p>{noPrices.message}</p>
              {noPrices.latest_price_date && (
                <button
                  type="button"
                  className="rounded-md border border-amber-300 bg-white px-3 py-1.5 font-semibold text-amber-900 hover:bg-amber-100 disabled:opacity-50"
                  onClick={demo}
                  disabled={isSaving}
                >
                  Ułóż plan demo na {formatDayMonth(noPrices.latest_price_date)} (ostatni dzień z cenami)
                </button>
              )}
            </div>
          )}

          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <button
              className={`${buttonClass("primary", "lg")} w-full sm:w-auto`}
              disabled={isSaving || !devices.length}
            >
              {isSaving ? "Układanie planu..." : "Zapisz i ułóż plan"}
            </button>
            {plan && (
              <button type="button" className={LINK_BUTTON} onClick={() => setView("plan")}>
                Wróć do planu bez zmian
              </button>
            )}
            <p role="status" className="flex items-center gap-1.5 text-sm font-medium text-emerald-700">
              {saved && <><FiCheckCircle aria-hidden="true" />Zapisano.</>}
            </p>
            {!saved && data.saved_at && (
              <p className="text-sm text-gray-500">Ostatnio zapisano: {savedAtText(data.saved_at)}</p>
            )}
            {hasErrors && <p className="text-sm text-red-600">Nie zapisano – popraw zaznaczone pola.</p>}
            {saveError && (
              <p className="text-sm text-red-600" role="alert">
                {saveError}
                {needsProfile && <>{" "}<Link to="/profile" className="font-semibold underline">Przejdź do profilu</Link></>}
              </p>
            )}
          </div>
        </form>
      )}
    </div>
  );
}

export default PlanningPage;
