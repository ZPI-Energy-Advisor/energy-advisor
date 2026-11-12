import { useEffect, useRef, useState } from "react";
import { FiCheckCircle, FiPlus, FiRotateCcw, FiTrash2 } from "react-icons/fi";
import apiClient from "../api/client";
import { getApiErrorMessage } from "../utils/energyFiles";
import { DEVICE_TYPE_LABELS } from "../utils/home";
import {
  AFTER_MAX_GAP_MIN,
  MAX_WINDOWS,
  afterOptions,
  crossesMidnight,
  durationText,
  energyNeeded,
  errorsFromResponse,
  nextWindow,
  orderError,
  sameWindows,
  toPayload,
  validateDevice,
  windowsText,
} from "../utils/planning";

const savedAtText = (iso) =>
  new Intl.DateTimeFormat("pl-PL", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(iso));

// Plan układa pracę w kwadransach, więc mówimy o tym przed wpisaniem godziny, a nie dopiero w błędzie.
const QUARTER_HINT = "Godziny co 15 minut, np. 08:00, 08:15, 08:30.";

const CARD ="bg-white border border-gray-200 rounded-lg p-4 md:p-5 shadow-sm";
const INPUT = "border border-gray-300 rounded px-2 py-1.5 text-sm bg-white focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500";
const LINK_BUTTON = "inline-flex items-center gap-1 text-sm font-medium text-emerald-700 hover:text-emerald-800 disabled:opacity-40";

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
  const field = (name, label, unit, props = {}) => (
    <label className="text-sm text-gray-700">
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
          Z sieci auto pobierze ok. {energy.toFixed(1).replace(".", ",")} kWh (z uwzględnieniem ok.{" "}
          {Math.round((1 - efficiency) * 100)}% strat ładowania).
        </p>
      )}
    </div>
  );
}

function DeviceCard({ device, preference, errors, efficiency, afterChoices, onChange }) {
  const typeLabel = DEVICE_TYPE_LABELS[device.device_type] ?? device.device_category;
  const program = device.programs.find((item) => item.program_id === preference.program_id);
  const after = afterChoices.find((item) => item.device_id === preference.after_device_id);

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
                  Ruszy po końcu: {after.device_name}, najwyżej {durationText(AFTER_MAX_GAP_MIN)} później.
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
                Opcjonalnie, np. żeby nie hałasowało w nocy. {QUARTER_HINT} Godzina wcześniejsza niż przedziały
                urządzenia {after.device_name} oznacza rano następnego dnia.
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

// Plan na jutro: wymagania urządzeń z plików użytkownika, które da się przesuwać albo dzielić (ZP-111).
// Na ich podstawie powstanie najtańszy plan pracy urządzeń na jutro (ZP-112). Dla każdego zalogowanego;
// ustawienia zostają do następnego zapisu, który je nadpisuje.
function PlanningPage() {
  const [data, setData] = useState(null);
  const [devices, setDevices] = useState([]);
  const [errors, setErrors] = useState({});
  const [loadError, setLoadError] = useState(null);
  const [saveError, setSaveError] = useState(null);
  const [saved, setSaved] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [scrollRequest, setScrollRequest] = useState(0);
  const formRef = useRef(null);

  // Po nieudanym zapisie przewijamy do pierwszej karty z błędem (przy wielu urządzeniach może być poza ekranem).
  useEffect(() => {
    if (scrollRequest) formRef.current?.querySelector("[data-has-error]")?.scrollIntoView?.({ behavior: "smooth", block: "center" });
  }, [scrollRequest]);

  const apply = (body) => {
    setData(body);
    setDevices(body.devices);
  };

  useEffect(() => {
    apiClient.get("/planning/preferences")
      .then(({ data: body }) => apply(body))
      .catch((err) => setLoadError(getApiErrorMessage(err, "Nie udało się pobrać ustawień planu.")));
  }, []);

  const efficiency = data?.charging_efficiency ?? 0.9;
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
    if (Object.keys(found).length) {
      setScrollRequest((count) => count + 1);
      return;
    }

    setIsSaving(true);
    try {
      const { data: body } = await apiClient.put("/planning/preferences", toPayload(devices));
      apply(body);
      setSaved(true);
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

  const hasErrors = Object.values(errors).some((deviceErrors) => Object.keys(deviceErrors ?? {}).length);

  return (
    <div className="max-w-4xl mx-auto pb-12">
      <h2 className="text-xl font-bold text-gray-900">Plan na jutro</h2>
      <p className="mt-1 mb-6 border-b border-gray-200 pb-4 text-sm text-gray-500">
        Powiedz, które urządzenia mają jutro pracować i kiedy mogą to robić. Na tej podstawie ułożymy najtańszy plan.
        Ustawienia zapamiętamy, więc kolejnego dnia wystarczy zmienić to, co trzeba.
      </p>

      {loadError && <p className="p-3 rounded bg-red-50 text-sm text-red-700" role="alert">{loadError}</p>}
      {!data && !loadError && <p className="text-sm text-gray-500" role="status">Ładowanie ustawień…</p>}

      {data && (
        <form ref={formRef} onSubmit={save} noValidate className="space-y-4">
          {!devices.length && (
            <p className={`${CARD} text-sm text-gray-600`}>
              W Twoich plikach nie ma urządzeń, które da się przesuwać albo dzielić. Zaimportuj plik urządzeń
              z pralką, zmywarką albo ładowarką EV.
            </p>
          )}
          {devices.map((device) => (
            <DeviceCard
              key={device.device_id}
              device={device}
              preference={device.preference}
              errors={errors[device.device_id] ?? {}}
              efficiency={efficiency}
              afterChoices={afterOptions(devices, device)}
              onChange={(change) => changeDevice(device.device_id, change)}
            />
          ))}

          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <button
              className="w-full sm:w-auto rounded-md bg-emerald-600 px-5 py-3 font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
              disabled={isSaving || !devices.length}
            >
              {isSaving ? "Zapisywanie..." : "Zapisz ustawienia"}
            </button>
            <p role="status" className="flex items-center gap-1.5 text-sm font-medium text-emerald-700">
              {saved && <><FiCheckCircle aria-hidden="true" />Zapisano.</>}
            </p>
            {!saved && data.saved_at && (
              <p className="text-sm text-gray-500">Ostatnio zapisano: {savedAtText(data.saved_at)}</p>
            )}
            {hasErrors && <p className="text-sm text-red-600">Nie zapisano – popraw zaznaczone pola.</p>}
            {saveError && <p className="text-sm text-red-600" role="alert">{saveError}</p>}
          </div>
        </form>
      )}
    </div>
  );
}

export default PlanningPage;
