import { describe, expect, it } from "vitest";
import { dayPrices, dayRows, daySegment, formatPln, listDays, minutesOf, visibleDays } from "./schedule";

const action = (overrides) => ({
  action_id: "act_1",
  device_id: "dev_wm_01",
  device_name: "Pralka",
  original_start: "2026-10-19T18:00:00+02:00",
  original_end: "2026-10-19T20:00:00+02:00",
  start: "2026-10-19T12:00:00+02:00",
  end: "2026-10-19T14:00:00+02:00",
  ...overrides,
});

describe("schedule", () => {
  it("czyta godzinę z czasu lokalnego", () => {
    expect(minutesOf("2026-10-19T17:30:00+02:00")).toBe(17 * 60 + 30);
  });

  it("wymienia dni zakresu włącznie, także przez koniec miesiąca", () => {
    expect(listDays("2026-10-30", "2026-11-01")).toEqual(["2026-10-30", "2026-10-31", "2026-11-01"]);
  });

  it("dokłada dobę, w której kończy się akcja wystająca poza zakres", () => {
    const actions = [action({ start: "2026-10-19T23:45:00+02:00", end: "2026-10-20T02:45:00+02:00" })];

    expect(visibleDays("2026-10-19", "2026-10-19", actions)).toEqual(["2026-10-19", "2026-10-20"]);
  });

  it("nie dokłada doby, gdy akcja kończy się dokładnie o północy", () => {
    const actions = [action({ start: "2026-10-19T22:00:00+02:00", end: "2026-10-20T00:00:00+02:00" })];

    expect(visibleDays("2026-10-19", "2026-10-19", actions)).toEqual(["2026-10-19"]);
  });

  it("liczy pozycję akcji na osi doby", () => {
    expect(daySegment("2026-10-19T12:00:00+02:00", "2026-10-19T18:00:00+02:00", "2026-10-19")).toEqual({
      left: 50,
      width: 25,
    });
  });

  it("dzieli akcję przechodzącą przez północ na dwie doby", () => {
    const start = "2026-10-19T23:00:00+02:00";
    const end = "2026-10-20T02:00:00+02:00";

    expect(daySegment(start, end, "2026-10-19").width).toBeCloseTo((60 / 1440) * 100);
    expect(daySegment(start, end, "2026-10-20")).toEqual({ left: 0, width: (120 / 1440) * 100 });
    expect(daySegment(start, end, "2026-10-21")).toBeNull();
  });

  it("akcja kończąca się o północy nie zajmuje kolejnej doby", () => {
    expect(daySegment("2026-10-19T22:00:00+02:00", "2026-10-20T00:00:00+02:00", "2026-10-20")).toBeNull();
  });

  it("grupuje akcje w wiersze urządzeń", () => {
    const rows = dayRows([action(), action({ action_id: "act_2", device_id: "dev_tv", device_name: "Telewizor" })], "2026-10-19");

    expect(rows.map((row) => row.name)).toEqual(["Pralka", "Telewizor"]);
    expect(rows[0].before).toHaveLength(1);
    expect(rows[0].after).toHaveLength(1);
  });

  it("pokazuje urządzenie, gdy akcja przesunęła się na tę dobę tylko częściowo", () => {
    const rows = dayRows(
      [action({ start: "2026-10-19T23:45:00+02:00", end: "2026-10-20T02:45:00+02:00" })],
      "2026-10-20",
    );

    expect(rows[0].before).toEqual([]);
    expect(rows[0].after).toHaveLength(1);
  });

  it("wybiera ceny doby", () => {
    const prices = [
      { start: "2026-10-19T00:15:00+02:00", price_pln_kwh: 0.5 },
      { start: "2026-10-20T00:00:00+02:00", price_pln_kwh: 0.7 },
    ];

    expect(dayPrices(prices, "2026-10-19")).toEqual([{ minute: 15, price: 0.5 }]);
  });

  it("formatuje kwoty", () => {
    expect(formatPln(1.5)).toMatch(/^1,50\sz/);
    expect(formatPln(null)).toBe("–");
  });
});
