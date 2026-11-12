import { describe, expect, it } from "vitest";
import {
  deviceStateLabel,
  durationLabel,
  formatKw,
  formatPln,
  formatSimDate,
  formatSimTime,
  groupDevicesByCategory,
  isControllable,
  simDay,
  speedOptions,
} from "./home";

const device = (fields) => ({ device_name: "X", state: "off", power_kw: 0, programs: [], ...fields });

describe("home utils", () => {
  it("grupuje urządzenia po kategorii w stałej kolejności, a nieznane na końcu", () => {
    const groups = groupDevicesByCategory([
      device({ device_name: "Lampa", device_category: "Oświetlenie" }),
      device({ device_name: "Zmywarka", device_category: "AGD" }),
      device({ device_name: "Pralka", device_category: "AGD" }),
      device({ device_name: "Spoza rejestru", device_category: null }),
      device({ device_name: "PV", device_category: "OZE" }),
    ]);

    expect(groups.map((group) => group.category)).toEqual(["OZE", "AGD", "Oświetlenie", "Pozostałe"]);
    expect(groups[1].devices.map((item) => item.device_name)).toEqual(["Pralka", "Zmywarka"]);
  });

  it("opisuje stan urządzenia, w tym produkcję PV i program", () => {
    expect(deviceStateLabel(device({ state: "running", power_kw: -2.5 }))).toBe("Produkuje");
    expect(deviceStateLabel(device({ state: "running", power_kw: 1.8, program_id: "eco" }))).toBe("Program w toku");
    expect(deviceStateLabel(device({ state: "running", power_kw: 0.06 }))).toBe("Pracuje");
    expect(deviceStateLabel(device({ state: "unreachable", power_kw: null }))).toBe("Brak połączenia");
  });

  it("nie pozwala sterować urządzeniem bez połączenia albo po awarii", () => {
    expect(isControllable(device({ state: "idle" }))).toBe(true);
    expect(isControllable(device({ state: "unreachable" }))).toBe(false);
    expect(isControllable(device({ state: "error" }))).toBe(false);
  });

  it("pokazuje czas symulacji w strefie domu niezależnie od strefy przeglądarki", () => {
    const utcMidnight = "2026-10-24T22:00:00Z"; // północ 25.10 w Warszawie (jeszcze czas letni)

    expect(formatSimTime(utcMidnight)).toBe("00:00");
    expect(simDay(utcMidnight)).toBe("2026-10-25");
    expect(formatSimDate(utcMidnight)).toContain("25 października 2026");
  });

  it("formatuje liczby po polsku i bez minus zera", () => {
    expect(formatKw(1.8)).toBe("1,80 kW");
    expect(formatKw(-0)).toBe("0,00 kW");
    expect(formatKw(null)).toBe("—");
    expect(formatPln(3.7215)).toBe("3,72 zł");
  });

  it("dodaje do listy tempo ustawione poza ekranem", () => {
    expect(speedOptions(288).map((option) => option.value)).toEqual([60, 288, 1440]);
    expect(speedOptions(100).map((option) => option.value)).toEqual([60, 100, 288, 1440]);
  });

  it("opisuje czas trwania programu", () => {
    expect(durationLabel(45)).toBe("45 min");
    expect(durationLabel(120)).toBe("2 h");
    expect(durationLabel(150)).toBe("2 h 30 min");
  });
});
