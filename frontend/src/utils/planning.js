// Plan na jutro (ZP-111, ZP-112): przedziały godzin, walidacja wymagań urządzeń, energia auta, pompa ciepła i bojler.

export const MAX_WINDOWS = 4;
const DAY_MINUTES = 24 * 60;

const minutesOf = (clock) => {
  const [hours, minutes] = clock.split(":").map(Number);
  return hours * 60 + minutes;
};

/** Minuty od północy jutra [start, koniec); koniec nie później niż start przechodzi przez północ. */
export const windowSpan = (window) => {
  const start = minutesOf(window.start);
  const end = minutesOf(window.end);
  return [start, end > start ? end : end + DAY_MINUTES];
};

export const windowLength = (window) => {
  const [start, end] = windowSpan(window);
  return end - start;
};

export const crossesMidnight = (window) => windowSpan(window)[1] > DAY_MINUTES;

export const durationText = (minutes) => {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (!hours) return `${rest} min`;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
};

const kwhText = (value) => value.toFixed(1).replace(".", ",");

export const windowsText = (windows) => windows.map((window) => `${window.start}–${window.end}`).join(", ");

export const sameWindows = (first, second) =>
  first.length === second.length && first.every((window, index) => window.start === second[index].start && window.end === second[index].end);

const clockOf = (minutes) => {
  const value = ((minutes % DAY_MINUTES) + DAY_MINUTES) % DAY_MINUTES;
  return `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
};

/** Nowy przedział: od końca ostatniego, na 2 h (pierwszy: 08:00–10:00). */
export const nextWindow = (windows) => {
  if (!windows.length) return { start: "08:00", end: "10:00" };
  const [, end] = windowSpan(windows[windows.length - 1]);
  return { start: clockOf(end), end: clockOf(end + 120) };
};

const isQuarter = (clock) => /^([01]\d|2[0-3]):(00|15|30|45)$/.test(clock ?? "");

const isPercent = (value) => value !== "" && value != null && Number(value) >= 0 && Number(value) <= 100;

/** Energia z sieci do naładowania auta: wprost albo z różnicy poziomu baterii i strat ładowania. */
export const energyNeeded = (preference, efficiency) => {
  if (preference.energy_input === "kwh") return preference.energy_kwh > 0 ? Number(preference.energy_kwh) : null;
  const { battery_kwh: battery, current_percent: current, target_percent: target } = preference;
  if (!(battery > 0) || !isPercent(current) || !isPercent(target)) return null;
  if (Number(target) <= Number(current)) return null;
  return Math.round(((Number(target) - Number(current)) / 100) * Number(battery) / efficiency * 100) / 100;
};

const isEmpty = (value) => value === "" || value == null;

/** Pola energii auta widoczne przy wybranym sposobie podania (poziom baterii albo kWh). */
export const energyFields = (preference) =>
  preference.energy_input === "percent" ? ["current_percent", "target_percent", "battery_kwh"] : ["energy_kwh"];

/** Zakresy jak w backendzie (schemas/planning.py): procent całkowity 0–100, kWh powyżej 0 i najwyżej 200. */
export const energyFieldError = (field, value) => {
  if (isEmpty(value)) return null;
  const number = Number(value);
  if (field.endsWith("_percent")) {
    return Number.isInteger(number) && number >= 0 && number <= 100 ? null : "Podaj liczbę całkowitą od 0 do 100.";
  }
  return Number.isFinite(number) && number > 0 && number <= 200 ? null : "Podaj wartość większą od 0, najwyżej 200 kWh.";
};

/** Błędy jednego urządzenia przed zapisem: pole → komunikat (ten sam tekst co z backendu). */
export const validateDevice = (device, preference, efficiency) => {
  const errors = {};
  // Wyłączone urządzenie ma zwiniętą kartę: nie sprawdzamy go, a błędne ukryte wartości pomija toPayload.
  if (!preference.enabled) return errors;
  const levels = preference.energy_input === "percent";
  if (device.kind === "heat_pump") {
    if (!preference.shift_hours) errors.shift_hours = "Wybierz, o ile można przesunąć grzanie.";
    return errors;
  }
  if (device.kind === "water_heater") {
    const times = preference.ready_times ?? [];
    const liters = preference.tank_liters;
    if (liters === "" || liters == null || Number(liters) < 30 || Number(liters) > 500) {
      errors.tank_liters = "Podaj pojemność zbiornika od 30 do 500 l.";
    }
    if (!times.length) errors.ready_times = "Dodaj co najmniej jedną godzinę.";
    else if (times.some((time) => !isQuarter(time))) errors.ready_times = "Godziny ustaw co kwadrans, np. 06:00 albo 17:45.";
    else if (new Set(times).size !== times.length) errors.ready_times = "Godziny się powtarzają.";
    return errors;
  }
  if (device.is_ev) {
    for (const field of energyFields(preference)) {
      const message = energyFieldError(field, preference[field]);
      if (message) errors[field] = message;
    }
    if (levels && !errors.current_percent && !errors.target_percent
        && !isEmpty(preference.current_percent) && !isEmpty(preference.target_percent)
        && Number(preference.target_percent) <= Number(preference.current_percent)) {
      errors.target_percent = "Docelowy poziom baterii musi być wyższy niż obecny.";
    }
  }
  const energyInvalid = Object.keys(errors).length > 0;
  if (preference.after_device_id && device.programs.length) {
    // Start wyznacza poprzednik: zamiast przedziałów tylko opcjonalne „skończ najpóźniej o”.
    if (!device.programs.some((item) => item.program_id === preference.program_id)) errors.program_id = "Wybierz program.";
    if (preference.finish_by && !isQuarter(preference.finish_by)) errors.finish_by = "Godziny ustaw co kwadrans, np. 08:00 albo 17:45.";
    return errors;
  }

  const windows = preference.windows;
  if (!windows.length) return { ...errors, windows: "Dodaj co najmniej jeden przedział godzin." };
  if (windows.some((window) => !isQuarter(window.start) || !isQuarter(window.end))) {
    return { ...errors, windows: "Godziny ustaw co kwadrans, np. 08:00 albo 17:45." };
  }
  const spans = windows.map(windowSpan).sort((a, b) => a[0] - b[0]);
  if (spans.some((span, index) => index > 0 && span[0] < spans[index - 1][1])) {
    return { ...errors, windows: "Przedziały godzin nachodzą na siebie." };
  }
  const longest = Math.max(...windows.map(windowLength));

  if (device.programs.length) {
    const program = device.programs.find((item) => item.program_id === preference.program_id);
    if (!program) errors.program_id = "Wybierz program.";
    else if (program.duration_min > longest) {
      errors.windows =
        `Najdłuższy przedział (${durationText(longest)}) jest krótszy niż program ` +
        `${program.program_name} (${durationText(program.duration_min)}).`;
    }
  }

  if (device.is_ev && !energyInvalid) {
    const energy = energyNeeded(preference, efficiency);
    if (energy == null) {
      if (!errors.target_percent) errors[levels ? "battery_kwh" : "energy_kwh"] = "Podaj, ile energii potrzebuje auto.";
    } else if (device.max_power_kw) {
      const minutes = windows.reduce((sum, window) => sum + windowLength(window), 0);
      const capacity = (device.max_power_kw * minutes) / 60;
      if (energy > capacity + 1e-9) {
        errors.windows =
          `W przedziałach zmieści się najwyżej ${kwhText(capacity)} kWh ` +
          `(${kwhText(device.max_power_kw)} kW × ${durationText(minutes)}), a auto potrzebuje ${kwhText(energy)} kWh.`;
      }
    }
  }
  return errors;
};

const waitsFor = (devices, deviceId, otherId) => {
  // Czy deviceId (pośrednio) czeka na otherId: idziemy po kolejnych poprzednikach.
  const byId = Object.fromEntries(devices.map((device) => [device.device_id, device]));
  const seen = new Set();
  let current = byId[deviceId]?.preference.after_device_id;
  while (current && !seen.has(current)) {
    if (current === otherId) return true;
    seen.add(current);
    current = byId[current]?.preference.after_device_id;
  }
  return false;
};

/**
 * Pierwsze urządzenie łańcucha „Wykonaj po” (np. pralka dla urządzenia po suszarce, która czeka na pralkę).
 * Od początku jego przedziałów backend liczy, czy „skończ najpóźniej o” to ten sam dzień, czy rano następnego.
 */
export const chainRoot = (devices, device) => {
  const byId = Object.fromEntries(devices.map((item) => [item.device_id, item]));
  const seen = new Set();
  let current = device;
  while (current.preference.after_device_id && !seen.has(current.device_id)) {
    seen.add(current.device_id);
    const previous = byId[current.preference.after_device_id];
    if (!previous) break;
    current = previous;
  }
  return current;
};

/** Najwcześniejszy początek przedziałów urządzenia jako godzina (null bez przedziałów). */
export const earliestStart = (windows) => {
  const starts = windows.filter((window) => isQuarter(window.start) && isQuarter(window.end)).map((window) => windowSpan(window)[0]);
  return starts.length ? clockOf(Math.min(...starts)) : null;
};

/** Urządzenia do wyboru w „Wykonaj po”: z programem, bez samego siebie i bez tych, które już czekają na to urządzenie. */
export const afterOptions = (devices, device) =>
  device.programs.length
    ? devices.filter((other) =>
      other.device_id !== device.device_id && other.programs.length && !waitsFor(devices, other.device_id, device.device_id))
    : [];

/** Błąd „Wykonaj po” przed zapisem: poprzednik musi jutro pracować. Miejsce w przedziałach sprawdza backend. */
export const orderError = (devices, device) => {
  const after = device.preference.after_device_id;
  if (!device.preference.enabled || !after) return null;
  const other = devices.find((item) => item.device_id === after);
  if (other && !other.preference.enabled) return `${other.device_name} nie pracuje jutro. Zaznacz je albo usuń „Wykonaj po”.`;
  return null;
};

/**
 * Treść zapisu: liczby z pól formularza (puste pole → null).
 *
 * Pola ukryte na ekranie (zwinięta karta wyłączonego urządzenia, przedziały przy „Wykonaj po”, drugi sposób
 * podania energii auta) wysyłamy bez błędnych wartości, bo użytkownik nie zobaczyłby błędu i nie mógłby go
 * poprawić. Poprawne ukryte ustawienia zostają, żeby wróciły po ponownym włączeniu.
 */
export const toPayload = (devices) => ({
  devices: devices.map(({ preference, programs = [] }) => {
    const number = (value) => (isEmpty(value) ? null : Number(value));
    const shownEnergy = new Set(preference.enabled ? energyFields(preference) : []);
    const energy = (field) =>
      !shownEnergy.has(field) && energyFieldError(field, preference[field]) ? null : number(preference[field]);
    const runsAfter = Boolean(preference.after_device_id) && programs.length > 0;
    const windowsShown = preference.enabled && !runsAfter;
    const finishShown = preference.enabled && runsAfter;
    return {
      ...preference,
      program_id: preference.program_id || null,
      after_device_id: preference.after_device_id || null,
      windows: windowsShown
        ? preference.windows
        : preference.windows.filter((window) => isQuarter(window.start) && isQuarter(window.end)),
      finish_by: preference.finish_by && (finishShown || isQuarter(preference.finish_by)) ? preference.finish_by : null,
      energy_kwh: energy("energy_kwh"),
      battery_kwh: energy("battery_kwh"),
      current_percent: energy("current_percent"),
      target_percent: energy("target_percent"),
      shift_hours: number(preference.shift_hours),
      tank_liters: number(preference.tank_liters),
      ready_times: preference.ready_times ?? [],
    };
  }),
});

/** Błędy 422 z backendu jako {device_id: {pole: komunikat}}. */
export const errorsFromResponse = (error, devices) => {
  const detail = error?.response?.data?.detail;
  if (!Array.isArray(detail)) return null;
  const result = {};
  for (const item of detail) {
    const [, , index, field] = item.loc ?? [];
    const device = devices[index];
    if (!device || !field) continue;
    result[device.device_id] = { ...result[device.device_id], [field]: String(item.msg).replace(/^Value error, /, "") };
  }
  return result;
};

/**
 * Kolejna godzina „woda gotowa na”: środek najdłuższej przerwy między podanymi godzinami, licząc w kółko
 * przez dobę (06:00 → 18:00; 06:00 i 18:00 → 12:00; dalej 00:00), zaokrąglony do kwadransa. Nie powtarza
 * godziny, bo środek przerwy dłuższej niż kwadrans nie trafia w żadną z nich. Pola puste albo niepełne
 * pomijamy (bez nich: 06:00), więc nie powstaje „NaN:NaN”.
 */
export const nextReadyTime = (times) => {
  const taken = [...new Set(times.filter(isQuarter).map(minutesOf))].sort((a, b) => a - b);
  if (!taken.length) return "06:00";
  let longest = { gap: 0, from: taken[0] };
  taken.forEach((minute, index) => {
    const next = index + 1 < taken.length ? taken[index + 1] : taken[0] + DAY_MINUTES;
    if (next - minute > longest.gap) longest = { gap: next - minute, from: minute };
  });
  return clockOf(longest.from + Math.round(longest.gap / 2 / 15) * 15);
};
