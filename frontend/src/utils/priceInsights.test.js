import { describe, expect, it } from "vitest";
import { describeDifference, describeUnavailable, describeWindow, formatWindowHours } from "./priceInsights";

describe("priceInsights", () => {
  it("opisuje różnicę do średniej słowami, bez znaku", () => {
    expect(describeDifference(-35.2)).toBe("35% taniej niż średnio");
    expect(describeDifference(12.6)).toBe("13% drożej niż średnio");
    expect(describeDifference(-0.3)).toBe("tyle samo co średnio");
    expect(describeDifference(null)).toBeNull();
  });

  it("pokazuje ujemną cenę i pomija procent, którego nie da się policzyć", () => {
    const window = { average_price_pln_kwh: -0.05, difference_percent: null };

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
