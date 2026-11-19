import { describe, expect, it } from "vitest";
import { describeUnavailable, describeWindow, formatWindowHours } from "./priceInsights";

describe("priceInsights", () => {
  it("pokazuje samą średnią cenę okna, także ujemną", () => {
    const window = { average_price_pln_kwh: -0.05, difference_percent: -120.0 };

    expect(describeWindow(window)).toBe("średnio -0,05 zł/kWh");
  });

  it("bierze godziny wprost z czasu polskiego, także w dobie zmiany czasu", () => {
    const window = { start: "2026-10-25T01:00:00+02:00", end: "2026-10-25T02:00:00+01:00" };

    expect(formatWindowHours(window)).toBe("01:00–02:00");
  });

  it("bez spodziewanej godziny nie zmyśla jej", () => {
    expect(describeUnavailable({ expected_publication_at: null })).toBe("Nie mamy jeszcze cen na jutro.");
  });
});
