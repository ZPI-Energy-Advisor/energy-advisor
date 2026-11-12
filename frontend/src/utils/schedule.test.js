import { describe, expect, it } from "vitest";
import {
  dayPrices,
  actionSummary,
  afterRanges,
  conflictText,
  dayRows,
  daySegment,
  formatMoment,
  formatPln,
  isConflict,
  listDays,
  minutesOf,
  missingPricesNote,
  visibleDays,
} from "./schedule";

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

  it("ładowanie EV z przerwami rysuje każdy okres ładowania osobno", () => {
    const ev = action({
      device_id: "dev_ev",
      device_name: "Ładowarka EV",
      start: "2026-10-20T01:00:00+02:00",
      end: "2026-10-20T03:15:00+02:00",
      charging: [
        { start: "2026-10-20T01:00:00+02:00", end: "2026-10-20T02:00:00+02:00" },
        { start: "2026-10-20T03:00:00+02:00", end: "2026-10-20T03:15:00+02:00" },
      ],
    });

    const [row] = dayRows([ev], "2026-10-20");

    expect(row.after).toHaveLength(2);
    expect(row.after[1].left).toBeCloseTo((180 / 1440) * 100);
  });

  it("opis akcji pokazuje godziny przed i po, a dla EV każdy okres ładowania", () => {
    const ev = action({
      device_name: "Ładowarka EV",
      original_start: "2026-04-04T08:00:00+02:00",
      original_end: "2026-04-04T11:45:00+02:00",
      start: "2026-04-04T08:00:00+02:00",
      end: "2026-04-04T15:00:00+02:00",
      cost_before: 14.05,
      cost_after: 10.79,
      charging: [
        { start: "2026-04-04T08:00:00+02:00", end: "2026-04-04T09:45:00+02:00" },
        { start: "2026-04-04T13:00:00+02:00", end: "2026-04-04T15:00:00+02:00" },
      ],
    });

    expect(actionSummary(ev)).toMatch(/^Ładowarka EV: 08:00–11:45 → 08:00–09:45, 13:00–15:00, 14,05\sz/);
  });

  it("godziny po optymalizacji: zwykła akcja jako zakres, EV z przerwami jako lista okresów", () => {
    expect(afterRanges(action({ start: "2026-10-19T13:00:00+02:00", end: "2026-10-19T15:00:00+02:00" }))).toBe("13:00–15:00");
    expect(afterRanges(action({
      charging: [
        { start: "2026-10-19T13:00:00+02:00", end: "2026-10-19T14:00:00+02:00" },
        { start: "2026-10-19T15:00:00+02:00", end: "2026-10-19T16:00:00+02:00" },
      ],
    }))).toBe("13:00–14:00, 15:00–16:00");
  });

  it("okres ładowania po północy dostaje swoją datę", () => {
    const ev = action({
      charging: [
        { start: "2026-10-19T22:00:00+02:00", end: "2026-10-19T23:00:00+02:00" },
        { start: "2026-10-20T02:00:00+02:00", end: "2026-10-20T03:00:00+02:00" },
        { start: "2026-10-20T04:00:00+02:00", end: "2026-10-20T05:00:00+02:00" },
      ],
    });

    expect(afterRanges(ev)).toBe("22:00–23:00, 20.10 02:00–03:00, 04:00–05:00");
    expect(afterRanges(ev, { withDay: true })).toBe("19.10 22:00–23:00, 20.10 02:00–03:00, 04:00–05:00");
  });

  it("data z godziną", () => {
    expect(formatMoment("2026-10-20T01:00:00+02:00")).toBe("20.10 01:00");
  });

  it("konflikt limitu przyłącza podaje moc umowną z profilu", () => {
    expect(conflictText(action({ reason: "grid_limit" }), 12.5)).toBe("przekroczony limit przyłącza (12,5 kW, moc umowna z profilu)");
    expect(conflictText(action({ reason: "outside_window" }), 12.5)).toBe("poza dozwolonym oknem godzin");
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

  it("brak cen nie jest konfliktem akcji", () => {
    expect(isConflict(action({ status: "conflict", reason: "missing_prices" }))).toBe(false);
    expect(isConflict(action({ status: "conflict", reason: "outside_window" }))).toBe(true);
    expect(isConflict(action({ status: "moved" }))).toBe(false);
  });

  it("opisuje brak cen jednym zdaniem z listą dni", () => {
    expect(missingPricesNote(0, [])).toBeNull();
    expect(missingPricesNote(3, ["2026-10-19", "2026-10-20"])).toMatch(/^Brak cen dynamicznych dla 3 akcji \(19\.10, 20\.10\)\./);
  });
});
