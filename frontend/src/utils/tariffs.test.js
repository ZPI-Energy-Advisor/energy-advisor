import { describe, expect, it } from "vitest";
import { describeBreakdown, formatPln, tariffEntries } from "./tariffs";

describe("tariffs", () => {
  it("opisuje części ceny w kolejności rachunku", () => {
    const text = describeBreakdown({ energy: 0.5, distribution: 0.3, fees: 0.05, vat: 0.19 }, (value) => value.toFixed(2));

    expect(text).toBe("energia 0.50 · dystrybucja 0.30 · opłaty za kWh 0.05 · VAT 0.19");
    expect(describeBreakdown(null, String)).toBeNull();
  });

  it("formatuje kwoty w złotych", () => {
    expect(formatPln(1234.5)).toMatch(/^1\s?234,50 zł$/);
    expect(formatPln(null)).toBe("—");
  });

  it("zwraca taryfy z kluczem", () => {
    expect(tariffEntries({ tariffs: { G11: { label: "G11" }, "G12-dynamic": { key: "G12-dynamic" } } })).toEqual([
      { key: "G11", label: "G11" },
      { key: "G12-dynamic" },
    ]);
    expect(tariffEntries(null)).toEqual([]);
  });
});
