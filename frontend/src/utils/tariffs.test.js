import { describe, expect, it } from "vitest";
import { comparisonTariffCode } from "./tariffs";

describe("comparisonTariffCode", () => {
  it("liczy koszty dla taryfy z profilu, a bez niej dla G11", () => {
    expect(comparisonTariffCode({ id: 2, code: "G12", type: "strefowa", profile_tariff_type: "G12" })).toBe("G12");
    expect(comparisonTariffCode(null)).toBe("G11");
  });
});
