// Plan na jutro (ZP-111): przedziały godzin, walidacja wymagań urządzeń i energia do naładowania auta.

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

/** Energia z sieci do naładowania auta: wprost albo z różnicy poziomu baterii i strat ładowania. */
export const energyNeeded = (preference, efficiency) => {
  if (preference.energy_input === "kwh") return preference.energy_kwh > 0 ? Number(preference.energy_kwh) : null;
  const { battery_kwh: battery, current_percent: current, target_percent: target } = preference;
  if (!(battery > 0) || current == null || target == null || current === "" || target === "") return null;
  if (Number(target) <= Number(current)) return null;
  return Math.round(((Number(target) - Number(current)) / 100) * Number(battery) / efficiency * 100) / 100;
};

/** Błędy jednego urządzenia przed zapisem: pole → komunikat (ten sam tekst co z backendu). */
export const validateDevice = (device, preference, efficiency) => {
  const errors = {};
  const levels = preference.energy_input === "percent";
  if (device.is_ev && levels && preference.current_percent !== "" && preference.target_percent !== ""
      && preference.current_percent != null && preference.target_percent != null
      && Number(preference.target_percent) <= Number(preference.current_percent)) {
    errors.target_percent = "Docelowy poziom baterii musi być wyższy niż obecny.";
  }
  if (!preference.enabled) return errors;
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

  if (device.is_ev) {
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

/** Ile najwyżej może minąć od końca poprzednika do startu urządzenia „Wykonaj po” (jak suszarka po pralce). */
export const AFTER_MAX_GAP_MIN = 60;

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

/** Treść zapisu: liczby z pól formularza (puste pole → null). */
export const toPayload = (devices) => ({
  devices: devices.map(({ preference }) => {
    const number = (value) => (value === "" || value == null ? null : Number(value));
    return {
      ...preference,
      program_id: preference.program_id || null,
      after_device_id: preference.after_device_id || null,
      finish_by: preference.finish_by || null,
      energy_kwh: number(preference.energy_kwh),
      battery_kwh: number(preference.battery_kwh),
      current_percent: number(preference.current_percent),
      target_percent: number(preference.target_percent),
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
