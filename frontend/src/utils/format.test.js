import { describe, expect, it } from "vitest";
import {
  formatAxis,
  formatDate,
  formatDateTime,
  formatDayMonth,
  formatDayWords,
  formatDegrees,
  formatKw,
  formatKwh,
  formatNumber,
  formatPercent,
  formatPln,
  formatPrice,
  formatRate,
  formatTime,
  formatWeekdayDay,
  formatWeekdayDayYear,
} from "./format";

// Intl w pl-PL rozdziela tysiące spacją niełamliwą (U+00A0); w asercjach zamieniamy ją na zwykłą spację.
const plain = (text) => text.replace(/[\u00a0\u202f]/g, " ");

describe("format: liczby", () => {
  it("dwa miejsca, przecinek i bez „-0”", () => {
    expect(formatNumber(186.53)).toBe("186,53");
    expect(formatNumber(279.4)).toBe("279,40");
    expect(formatNumber(-0.001)).toBe("0,00");
    expect(formatNumber(null)).toBe("—");
  });

  it("podziałka osi bez zbędnych zer", () => {
    expect(formatAxis(1.65)).toBe("1,65");
    expect(formatAxis(2.2)).toBe("2,2");
    expect(formatAxis(0)).toBe("0");
  });

  it("kwota: 1 234,56 zł", () => {
    expect(plain(formatPln(1234.561))).toBe("1 234,56 zł");
    expect(formatPln(null)).toBe("—");
  });

  it("cena kWh z dwoma miejscami, składnik ceny z trzema", () => {
    expect(formatPrice(0.4031)).toBe("0,40 zł/kWh");
    expect(formatRate(0.0892)).toBe("0,089 zł");
  });

  it("energia i moc z dwoma miejscami", () => {
    expect(plain(formatKwh(1234.5))).toBe("1 234,50 kWh");
    expect(formatKw(2.5)).toBe("2,50 kW");
    expect(formatKwh(undefined)).toBe("—");
  });

  it("procent z udziału, najwyżej jedno miejsce", () => {
    expect(formatPercent(0.123)).toBe("12,3%");
    expect(formatPercent(0.04)).toBe("4%");
    expect(formatPercent(null)).toBe("—");
  });

  it("temperatura zaokrąglona albo z jednym miejscem", () => {
    expect(formatDegrees(20.6)).toBe("21°C");
    expect(formatDegrees(-0.2)).toBe("0°C");
    expect(formatDegrees(20.64, 1)).toBe("20,6°C");
  });
});

describe("format: daty", () => {
  it("doba RRRR-MM-DD liczbami i słowami", () => {
    expect(formatDate("2026-11-27")).toBe("27.11.2026");
    expect(formatDayMonth("2026-11-27")).toBe("27.11");
    expect(formatDayWords("2026-11-27")).toBe("27 listopada");
    expect(formatWeekdayDay("2026-11-27")).toBe("piątek, 27 listopada");
    expect(formatWeekdayDayYear("2026-11-27")).toBe("piątek, 27 listopada 2026");
  });

  it("moment w czasie polskim, także zapisany w UTC bez strefy", () => {
    expect(formatTime("2026-11-27T13:30:00Z")).toBe("14:30");
    expect(formatTime("2026-07-01T10:00:00+02:00")).toBe("10:00");
    expect(formatDateTime("2026-11-27T13:30:00")).toBe("27.11.2026, 14:30");
    expect(formatDateTime(null)).toBe("—");
  });
});
