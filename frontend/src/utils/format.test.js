import { describe, expect, it } from "vitest";
import { formatAxis, formatNumber } from "./format";

describe("format", () => {
  it("kwoty i kWh z przecinkiem i dwoma miejscami", () => {
    expect(formatNumber(186.53)).toBe("186,53");
    expect(formatNumber(279.4)).toBe("279,40");
    expect(formatNumber(null)).toBe("—");
  });

  it("podziałka osi bez zbędnych zer", () => {
    expect(formatAxis(1.65)).toBe("1,65");
    expect(formatAxis(2.2)).toBe("2,2");
    expect(formatAxis(0)).toBe("0");
  });
});
