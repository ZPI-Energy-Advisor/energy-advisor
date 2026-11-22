import SegmentedControl from "../SegmentedControl";
import { Field, UnitInput, inputClass } from "./ProfileControls";
import {
  DIRECTIONS,
  MAX_PV_ARRAYS,
  TYPICAL_INSTALLATION,
  arrayPowerKwp,
  createArray,
  totalKwp,
} from "../../utils/profileForm";

const INPUT_OPTIONS = [
  { value: "panels", label: "Liczba paneli" },
  { value: "power", label: "Moc w kWp" },
];

const formatKwp = (value) =>
  Number.isFinite(value) ? `${value.toLocaleString("pl-PL", { maximumFractionDigits: 2 })} kWp` : "– kWp";

function PvInstallationFields({ installation, netMetering, field, onChange }) {
  const arrayKey = (index, name) => `pv_config.arrays.${index}.${name}`;
  const set = (changes, keys = []) => onChange({ ...installation, ...changes }, [...keys, "pv_config.installation"]);
  const setArray = (index, name, value) =>
    set({ arrays: installation.arrays.map((array, i) => (i === index ? { ...array, [name]: value } : array)) }, [arrayKey(index, name)]);
  const removeArray = (index) =>
    set(
      { arrays: installation.arrays.filter((_, i) => i !== index) },
      installation.arrays.flatMap((_, i) => ["power_kwp", "panel_count", "tilt"].map((name) => arrayKey(i, name))),
    );
  const panels = installation.input === "panels";
  const total = totalKwp(installation);
  const totalField = field("pv_config.installation");

  return (
    <>
      <div className="text-sm sm:col-span-2">
        <label className="flex items-start gap-2 font-medium text-gray-700">
          <input
            type="checkbox"
            className="mt-0.5 accent-emerald-600"
            checked={installation.estimated}
            onChange={(event) => set({ estimated: event.target.checked })}
          />
          Nie znam parametrów paneli, przyjmij typową instalację
        </label>
        <p className="ml-6 mt-1 text-xs text-gray-500">
          {installation.estimated
            ? `Liczymy dla ${TYPICAL_INSTALLATION.power_kwp} kWp skierowanych na południe pod kątem ${TYPICAL_INSTALLATION.tilt}° (typowa instalacja na domu). Prognoza produkcji będzie orientacyjna.`
            : "Parametry z umowy z instalatorem albo ze zgłoszenia instalacji do operatora."}
        </p>
        {netMetering && installation.estimated && (
          <p className="ml-6 mt-1 text-xs text-amber-700">
            Opust zależy od mocy: do 10 kWp odbierasz 80% energii, powyżej 70%. Jeśli masz więcej niż 10 kWp, podaj moc.
          </p>
        )}
      </div>

      {!installation.estimated && (
        <>
          <Field {...field("pv_config.input", { group: true, label: "Jak podajesz moc paneli" })}>
            {(f) => (
              <div id={f.id}>
                <SegmentedControl label="Jak podajesz moc paneli" options={INPUT_OPTIONS} value={installation.input} onChange={(value) => set({ input: value })} />
              </div>
            )}
          </Field>
          {panels ? (
            <Field {...field("pv_config.panel_power_w", { hint: "Z karty katalogowej panelu lub umowy; nowe panele mają zwykle 400–460 W." })}>
              {(f) => (
                <UnitInput field={f} unit="W" placeholder="np. 430" value={installation.panel_power_w} onChange={(value) => set({ panel_power_w: value }, ["pv_config.panel_power_w"])} />
              )}
            </Field>
          ) : (
            <div className="hidden sm:block" />
          )}

          {installation.arrays.map((array, index) => (
            <fieldset key={array.id} className="rounded-md border border-gray-200 p-3 sm:col-span-2">
              <legend className="px-1 text-sm font-semibold text-gray-900">
                Grupa paneli {index + 1}{" "}
                <span className="font-normal text-gray-500">· {formatKwp(arrayPowerKwp(installation, array))}</span>
              </legend>
              <div className="grid gap-4 sm:grid-cols-3">
                {panels ? (
                  <Field {...field(arrayKey(index, "panel_count"), { label: "Liczba paneli" })}>
                    {(f) => (
                      <input
                        id={f.id}
                        className={`${inputClass} ${f.borderClass}`}
                        inputMode="numeric"
                        placeholder="np. 8"
                        value={array.panel_count}
                        aria-invalid={f.invalid}
                        aria-describedby={f.describedBy}
                        onChange={(event) => setArray(index, "panel_count", event.target.value.replace(/\D/g, ""))}
                      />
                    )}
                  </Field>
                ) : (
                  <Field {...field(arrayKey(index, "power_kwp"), { label: "Moc" })}>
                    {(f) => <UnitInput field={f} unit="kWp" placeholder="np. 4,3" value={array.power_kwp} onChange={(value) => setArray(index, "power_kwp", value)} />}
                  </Field>
                )}
                <Field {...field(arrayKey(index, "azimuth"), { label: "Kierunek" })}>
                  {(f) => (
                    <select id={f.id} className={`${inputClass} ${f.borderClass}`} value={array.azimuth} onChange={(event) => setArray(index, "azimuth", Number(event.target.value))}>
                      {DIRECTIONS.map((direction) => <option key={direction.value} value={direction.value}>{direction.label}</option>)}
                    </select>
                  )}
                </Field>
                <Field {...field(arrayKey(index, "tilt"), { label: "Nachylenie" })}>
                  {(f) => <UnitInput field={f} unit="°" placeholder="np. 35" value={array.tilt} onChange={(value) => setArray(index, "tilt", value.replace(/\D/g, ""))} />}
                </Field>
              </div>
              {installation.arrays.length > 1 && (
                <button type="button" onClick={() => removeArray(index)} className="mt-3 text-sm font-medium text-red-600 hover:underline">
                  Usuń grupę
                </button>
              )}
            </fieldset>
          ))}

          <div className="text-sm sm:col-span-2">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <button
                type="button"
                disabled={installation.arrays.length >= MAX_PV_ARRAYS}
                onClick={() => set({ arrays: [...installation.arrays, createArray()] })}
                className="font-medium text-emerald-700 hover:underline disabled:text-gray-400 disabled:no-underline"
              >
                + Dodaj grupę paneli
              </button>
              <p id={totalField.id} className="font-semibold text-gray-900">Razem: {formatKwp(total)}</p>
            </div>
            {totalField.error && <p className="mt-1.5 text-xs text-red-600">{totalField.error}</p>}
            <p className="mt-1.5 text-xs text-gray-500">
              Osobna grupa dla każdej połaci dachu, np. 4 panele na wschód i 3 na zachód. Nachylenie: dach skośny zwykle
              30–45°, dach płaski z konstrukcją 10–15°, ściana 90°.
            </p>
          </div>

          <Field {...field("pv_config.inverter_power_kw", { hint: "Opcjonalnie. Z tabliczki falownika; ogranicza produkcję w słoneczne południe." })}>
            {(f) => (
              <UnitInput field={f} unit="kW" placeholder="np. 5" value={installation.inverter_power_kw} onChange={(value) => set({ inverter_power_kw: value }, ["pv_config.inverter_power_kw"])} />
            )}
          </Field>
        </>
      )}
    </>
  );
}

export default PvInstallationFields;
