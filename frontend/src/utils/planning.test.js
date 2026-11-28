import { describe, expect, it } from "vitest";
import {
  afterOptions, chainRoot, crossesMidnight, earliestStart, energyNeeded, errorsFromResponse, nextReadyTime, nextWindow,
  orderError, toPayload, validateDevice, windowLength,
} from "./planning";

const washer = {
  device_id: "dev_wm_01",
  is_ev: false,
  max_power_kw: null,
  programs: [{ program_id: "cotton_60", program_name: "Bawełna 60°C", duration_min: 120 }],
};
const ev = { device_id: "dev_ev_01", is_ev: true, max_power_kw: 3.7, programs: [] };
const windows = (...pairs) => pairs.map(([start, end]) => ({ start, end }));

describe("planning", () => {
  it("przedział przez północ trwa do rana, 00:00–00:00 to cała doba", () => {
    expect(windowLength({ start: "18:00", end: "07:00" })).toBe(13 * 60);
    expect(crossesMidnight({ start: "18:00", end: "07:00" })).toBe(true);
    expect(windowLength({ start: "17:00", end: "00:00" })).toBe(7 * 60);
    expect(crossesMidnight({ start: "17:00", end: "00:00" })).toBe(false);
    expect(windowLength({ start: "00:00", end: "00:00" })).toBe(24 * 60);
  });

  it("blokuje przedziały krótsze niż program, a kilka przedziałów wystarcza, gdy jeden się mieści", () => {
    const base = { enabled: true, program_id: "cotton_60" };

    expect(validateDevice(washer, { ...base, windows: windows(["08:00", "09:00"], ["12:00", "13:30"]) }, 0.9).windows)
      .toBe("Najdłuższy przedział (1 h 30 min) jest krótszy niż program Bawełna 60°C (2 h).");
    expect(validateDevice(washer, { ...base, windows: windows(["08:00", "13:00"], ["17:00", "00:00"]) }, 0.9)).toEqual({});
  });

  it("wykrywa nachodzące przedziały i brak programu; wyłączone urządzenie nie jest sprawdzane", () => {
    expect(validateDevice(washer, { enabled: true, program_id: "", windows: windows(["08:00", "12:00"], ["11:00", "14:00"]) }, 0.9))
      .toEqual({ windows: "Przedziały godzin nachodzą na siebie." });
    expect(validateDevice(washer, { enabled: true, program_id: "", windows: windows(["08:00", "12:00"]) }, 0.9))
      .toEqual({ program_id: "Wybierz program." });
    expect(validateDevice(washer, { enabled: false, program_id: "", windows: [] }, 0.9)).toEqual({});
  });

  it("energia auta z poziomu baterii uwzględnia straty ładowania", () => {
    const levels = { energy_input: "percent", battery_kwh: 60, current_percent: 40, target_percent: 70 };

    expect(energyNeeded(levels, 0.9)).toBe(20);
    expect(energyNeeded({ ...levels, target_percent: 30 }, 0.9)).toBeNull();
    expect(energyNeeded({ energy_input: "kwh", energy_kwh: "12" }, 0.9)).toBe(12);
  });

  it("energia auta musi zmieścić się w przedziałach przy mocy ładowarki", () => {
    const preference = { enabled: true, energy_input: "kwh", energy_kwh: 10, windows: windows(["22:00", "00:00"]) };

    expect(validateDevice(ev, preference, 0.9).windows).toBe(
      "W przedziałach zmieści się najwyżej 7,40 kWh (3,70 kW × 2 h), a auto potrzebuje 10,00 kWh.",
    );
    expect(validateDevice(ev, { ...preference, windows: windows(["18:00", "07:00"]) }, 0.9)).toEqual({});
  });

  it("pola energii auta mają zakresy jak w backendzie, sprawdzane tylko gdy są widoczne", () => {
    const levels = {
      enabled: true, energy_input: "percent", battery_kwh: 60, current_percent: 40, target_percent: 70,
      windows: windows(["18:00", "07:00"]),
    };

    expect(validateDevice(ev, { ...levels, target_percent: 150 }, 0.9)).toEqual({
      target_percent: "Podaj liczbę całkowitą od 0 do 100.",
    });
    expect(validateDevice(ev, { ...levels, current_percent: "50.5" }, 0.9)).toEqual({
      current_percent: "Podaj liczbę całkowitą od 0 do 100.",
    });
    expect(validateDevice(ev, { ...levels, battery_kwh: 300 }, 0.9)).toEqual({
      battery_kwh: "Podaj wartość większą od 0, najwyżej 200 kWh.",
    });
    expect(validateDevice(ev, { ...levels, energy_input: "kwh", energy_kwh: "0" }, 0.9)).toEqual({
      energy_kwh: "Podaj wartość większą od 0, najwyżej 200 kWh.",
    });
    // Ukryte pole kWh przy poziomie baterii nie blokuje zapisu.
    expect(validateDevice(ev, { ...levels, energy_kwh: 300 }, 0.9)).toEqual({});
  });

  it("wyłączone auto z odwróconymi poziomami baterii nie blokuje zapisu", () => {
    const preference = {
      enabled: false, energy_input: "percent", battery_kwh: 60, current_percent: 80, target_percent: 50, windows: [],
    };

    expect(validateDevice(ev, preference, 0.9)).toEqual({});
    expect(validateDevice(ev, { ...preference, enabled: true, windows: windows(["18:00", "07:00"]) }, 0.9)).toEqual({
      target_percent: "Docelowy poziom baterii musi być wyższy niż obecny.",
    });
  });

  it("zapis pomija błędne wartości w ukrytych polach, a poprawne zostawia", () => {
    const evDevice = (preference) => ({ ...ev, preference });
    const dryer = (preference) => ({ device_id: "dev_td_01", programs: [{ program_id: "dry" }], preference });

    const [hiddenEv, offEv, runsAfter] = toPayload([
      // kWh ukryte przy poziomie baterii
      evDevice({ enabled: true, energy_input: "percent", energy_kwh: 300, battery_kwh: 60, current_percent: 40,
        target_percent: 70, windows: windows(["18:00", "07:00"]) }),
      // karta zwinięta: procenty poza zakresem znikają, poprawna pojemność zostaje
      evDevice({ enabled: false, energy_input: "percent", battery_kwh: "60", current_percent: 150, target_percent: "",
        windows: windows(["18:00", "07:00"]) }),
      // przy „Wykonaj po” przedziały są ukryte: pusta godzina nie trafia do zapisu
      dryer({ enabled: true, program_id: "dry", after_device_id: "dev_wm_01", finish_by: "22:00",
        windows: windows(["08:00", ""], ["12:00", "14:00"]) }),
    ]).devices;

    expect(hiddenEv).toMatchObject({ energy_kwh: null, battery_kwh: 60, current_percent: 40, target_percent: 70 });
    expect(offEv).toMatchObject({ battery_kwh: 60, current_percent: null, target_percent: null });
    expect(runsAfter.windows).toEqual(windows(["12:00", "14:00"]));
    expect(runsAfter.finish_by).toBe("22:00");
  });

  it("„skończ najpóźniej o” liczymy od startu pierwszego urządzenia w łańcuchu", () => {
    const device = (id, after, deviceWindows) => ({
      device_id: id, device_name: id, preference: { after_device_id: after, windows: deviceWindows },
    });
    const washerFirst = device("pralka", null, windows(["20:00", "23:00"]));
    const dryerAfter = device("suszarka", "pralka", windows(["07:00", "22:00"]));
    const dishwasherAfter = device("zmywarka", "suszarka", windows(["19:00", "07:00"]));
    const devices = [washerFirst, dryerAfter, dishwasherAfter];

    expect(chainRoot(devices, dishwasherAfter).device_id).toBe("pralka");
    expect(chainRoot(devices, dryerAfter).device_id).toBe("pralka");
    expect(earliestStart(windows(["22:00", "02:00"], ["18:00", "20:00"]))).toBe("18:00");
    expect(earliestStart(windows(["", "10:00"]))).toBeNull();
  });

  it("nowy przedział zaczyna się po ostatnim i trwa 2 h", () => {
    expect(nextWindow([])).toEqual({ start: "08:00", end: "10:00" });
    expect(nextWindow(windows(["07:00", "22:00"]))).toEqual({ start: "22:00", end: "00:00" });
    expect(nextWindow(windows(["18:00", "07:00"]))).toEqual({ start: "07:00", end: "09:00" });
  });

  it("przypisuje błędy 422 z backendu do urządzeń", () => {
    const error = { response: { data: { detail: [
      { loc: ["body", "devices", 1, "windows"], msg: "Za krótko.", type: "value_error" },
    ] } } };

    expect(errorsFromResponse(error, [washer, ev])).toEqual({ dev_ev_01: { windows: "Za krótko." } });
    expect(errorsFromResponse({ response: { data: { detail: "Błąd" } } }, [washer])).toBeNull();
  });

  it("„Wykonaj po” nie pozwala na pętlę i wymaga, żeby poprzednik pracował jutro", () => {
    const device = (id, after = null, enabled = true, programs = [{ program_id: "p" }]) => ({
      device_id: id, device_name: id, programs, preference: { enabled, after_device_id: after },
    });
    const devices = [device("a"), device("b", "a"), device("c", "b"), device("ev", null, true, [])];

    expect(afterOptions(devices, devices[0]).map((item) => item.device_id)).toEqual([]);  // b i c czekają na a
    expect(afterOptions(devices, devices[2]).map((item) => item.device_id)).toEqual(["a", "b"]);
    expect(afterOptions(devices, devices[3])).toEqual([]);
    expect(orderError(devices, devices[1])).toBeNull();
    expect(orderError([device("a", null, false), devices[1]], devices[1])).toBe("a nie pracuje jutro. Zaznacz je albo usuń „Wykonaj po”.");
  });

  it("urządzenie „Wykonaj po” nie potrzebuje przedziałów, ale godzina końca musi być co kwadrans", () => {
    const dryer = { programs: [{ program_id: "dry", program_name: "Suszenie", duration_min: 90 }], is_ev: false };
    const preference = { enabled: true, program_id: "dry", windows: [], after_device_id: "wm" };

    expect(validateDevice(dryer, preference, 0.9)).toEqual({});
    expect(validateDevice(dryer, { ...preference, finish_by: "22:10" }, 0.9)).toEqual({
      finish_by: "Godziny ustaw co kwadrans, np. 08:00 albo 17:45.",
    });
    expect(validateDevice(dryer, { ...preference, after_device_id: null }, 0.9)).toEqual({
      windows: "Dodaj co najmniej jeden przedział godzin.",
    });
  });

  it("bojler wymaga pojemności zbiornika 30–500 l i godzin co kwadrans bez powtórzeń", () => {
    const heater = { kind: "water_heater", programs: [] };
    const preference = { enabled: true, ready_times: ["06:00", "18:00"], tank_liters: 120 };

    expect(validateDevice(heater, preference, 0.9)).toEqual({});
    expect(validateDevice(heater, { ...preference, tank_liters: "20" }, 0.9)).toEqual({
      tank_liters: "Podaj pojemność zbiornika od 30 do 500 l.",
    });
    expect(validateDevice(heater, { ...preference, ready_times: ["06:00", "06:00"] }, 0.9)).toEqual({
      ready_times: "Godziny się powtarzają.",
    });
  });

  it("poziom baterii auta to najwyżej 100%", () => {
    const ev = { is_ev: true, programs: [], max_power_kw: 3.7 };
    const preference = {
      enabled: true, energy_input: "percent", battery_kwh: 50, current_percent: 20, target_percent: 803,
      windows: [{ start: "17:00", end: "03:00" }],
    };

    expect(validateDevice(ev, preference, 0.9)).toMatchObject({ target_percent: "Podaj liczbę całkowitą od 0 do 100." });
    expect(energyNeeded(preference, 0.9)).toBeNull();
    expect(validateDevice(ev, { ...preference, current_percent: 120, target_percent: 80 }, 0.9))
      .toMatchObject({ current_percent: "Podaj liczbę całkowitą od 0 do 100." });
  });

  it("„Dodaj godzinę” bojlera bierze środek najdłuższej przerwy i nie powtarza godzin", () => {
    expect(nextReadyTime([])).toBe("06:00");
    expect(nextReadyTime(["06:00"])).toBe("18:00");
    expect(nextReadyTime(["06:00", "18:00"])).toBe("12:00");
    expect(nextReadyTime(["06:00", "18:00", "12:00"])).toBe("00:00");

    // Wcześniej: dwa kliknięcia na domyślnych godzinach dawały 00:00 dwa razy.
    let times = ["06:00", "18:00"];
    for (let click = 0; click < 2; click += 1) times = [...times, nextReadyTime(times)];
    expect(new Set(times).size).toBe(times.length);

    // Puste albo niepełne pole jest pomijane, zamiast dawać „NaN:NaN”.
    expect(nextReadyTime(["06:00", ""])).toBe("18:00");
    expect(nextReadyTime([""])).toBe("06:00");
    // Środek przerwy zaokrąglony do kwadransa: 07:00–08:15 → 07:30.
    expect(nextReadyTime(["07:00", "08:15", "18:00"])).toMatch(/^([01]\d|2[0-3]):(00|15|30|45)$/);
  });
});
