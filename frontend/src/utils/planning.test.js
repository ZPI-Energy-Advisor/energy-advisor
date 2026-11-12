import { describe, expect, it } from "vitest";
import {
  afterOptions, crossesMidnight, energyNeeded, errorsFromResponse, nextWindow, orderError, validateDevice, windowLength,
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
      "W przedziałach zmieści się najwyżej 7,4 kWh (3,7 kW × 2 h), a auto potrzebuje 10,0 kWh.",
    );
    expect(validateDevice(ev, { ...preference, windows: windows(["18:00", "07:00"]) }, 0.9)).toEqual({});
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
});
