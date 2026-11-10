// Elementy formularza profilu: sekcja, pole z podpowiedzią i błędem, pole liczby z jednostką, licznik, karty wyboru.

export const inputClass =
  "w-full rounded-md border bg-white px-3 py-2.5 font-normal text-gray-900 focus:outline-none focus:ring-1 disabled:bg-gray-100";

function borderClass(error, missing) {
  if (error) return "border-red-400 focus:border-red-500 focus:ring-red-500";
  if (missing) return "border-amber-400 focus:border-amber-500 focus:ring-amber-500";
  return "border-gray-300 focus:border-emerald-500 focus:ring-emerald-500";
}

export function Section({ title, description, children }) {
  return (
    <section className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm sm:p-6">
      <h3 className="text-base font-semibold text-gray-900">{title}</h3>
      {description && <p className="mt-1 text-sm text-gray-500">{description}</p>}
      <div className="mt-5 grid gap-5 sm:grid-cols-2">{children}</div>
    </section>
  );
}

// Pole formularza. `group` – kontrolka z kilku przycisków (bez <label for>), `wide` – na całą szerokość sekcji.
export function Field({ id, label, hint, error, missing, wide, group, children }) {
  const hintId = hint ? `${id}-hint` : undefined;
  const messageId = error || missing ? `${id}-message` : undefined;
  const describedBy = [messageId, hintId].filter(Boolean).join(" ") || undefined;
  const LabelTag = group ? "span" : "label";
  return (
    <div className={`text-sm ${wide ? "sm:col-span-2" : ""}`}>
      <LabelTag id={`${id}-label`} {...(group ? {} : { htmlFor: id })} className="mb-2 block font-medium text-gray-700">
        {label}
      </LabelTag>
      {children({ id, describedBy, invalid: Boolean(error), borderClass: borderClass(error, missing) })}
      {error && <p id={messageId} className="mt-1.5 text-xs text-red-600">{error}</p>}
      {!error && missing && <p id={messageId} className="mt-1.5 text-xs text-amber-700">Brak w zapisanym profilu.</p>}
      {hint && <p id={hintId} className="mt-1.5 text-xs text-gray-500">{hint}</p>}
    </div>
  );
}

// Pole liczby (także z przecinkiem) z jednostką po prawej, bez strzałek +/-.
export function UnitInput({ field, unit, value, onChange, placeholder }) {
  return (
    <div className="relative">
      <input
        id={field.id}
        className={`${inputClass} ${field.borderClass} pr-12`}
        type="text"
        inputMode="decimal"
        autoComplete="off"
        value={value}
        placeholder={placeholder}
        aria-invalid={field.invalid}
        aria-describedby={field.describedBy}
        onChange={(event) => onChange(event.target.value.replace(/[^\d.,]/g, ""))}
      />
      <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-gray-500">{unit}</span>
    </div>
  );
}

// Licznik małych liczb całkowitych z dużymi przyciskami (wygodny na telefonie).
export function Stepper({ field, value, onChange, min = 1, max = 20 }) {
  const number = Number(value) || min;
  const buttonClass =
    "h-11 w-11 rounded-md border border-gray-300 bg-white text-lg font-semibold text-gray-700 hover:bg-gray-50 disabled:opacity-40";
  return (
    <div className="flex items-center gap-2" role="group" aria-labelledby={`${field.id}-label`} aria-describedby={field.describedBy}>
      <button type="button" className={buttonClass} aria-label="Mniej" disabled={number <= min} onClick={() => onChange(number - 1)}>−</button>
      <output id={field.id} aria-live="polite" className="w-12 text-center text-base font-semibold text-gray-900">{number}</output>
      <button type="button" className={buttonClass} aria-label="Więcej" disabled={number >= max} onClick={() => onChange(number + 1)}>+</button>
    </div>
  );
}

// Karty jednokrotnego wyboru z opisem (radio). Opcja może mieć oznaczenie `warning`.
export function ChoiceCards({ field, name, options, value, onChange, columns = "sm:grid-cols-2" }) {
  return (
    <div id={field.id} role="radiogroup" aria-labelledby={`${field.id}-label`} aria-describedby={field.describedBy} className={`grid gap-2 ${columns}`}>
      {options.map((option) => {
        const checked = value === option.value;
        const tone = option.warning
          ? "border-amber-400 bg-amber-50"
          : checked
            ? "border-emerald-500 bg-emerald-50 ring-1 ring-emerald-500"
            : "border-gray-200 hover:border-gray-300";
        const optionId = `${field.id}-${option.value}`;
        // Nazwa opcji to sam tytuł; opis i ostrzeżenie są dodatkowym opisem pola wyboru.
        const details = [option.description && `${optionId}-description`, option.warning && `${optionId}-warning`].filter(Boolean);
        return (
          <label key={option.value} className={`flex cursor-pointer gap-3 rounded-md border p-3 ${tone}`}>
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={checked}
              onChange={() => onChange(option.value)}
              aria-labelledby={`${optionId}-title`}
              aria-describedby={details.join(" ") || undefined}
              className="mt-0.5 accent-emerald-600"
            />
            <span>
              <span id={`${optionId}-title`} className="block font-medium text-gray-900">{option.label}</span>
              {option.description && <span id={`${optionId}-description`} className="mt-0.5 block text-xs text-gray-500">{option.description}</span>}
              {option.warning && <span id={`${optionId}-warning`} className="mt-0.5 block text-xs font-medium text-amber-700">{option.warning}</span>}
            </span>
          </label>
        );
      })}
    </div>
  );
}
