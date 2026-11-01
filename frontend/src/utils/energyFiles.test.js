import { describe, expect, it } from "vitest";
import {
  ALL_DEVICE_FILES_ID,
  ALL_FILES_ID,
  aggregateIdForSourceType,
  formatDataResolution,
  formatRecordsCount,
  isAggregateSource,
} from "./energyFiles";

describe("źródła danych plików", () => {
  it("rozpoznaje oba źródła zbiorcze", () => {
    expect(isAggregateSource(ALL_FILES_ID)).toBe(true);
    expect(isAggregateSource(ALL_DEVICE_FILES_ID)).toBe(true);
    expect(isAggregateSource("3f2c1b7e-0000-4000-8000-000000000000")).toBe(false);
  });

  it("dobiera źródło zbiorcze do typu pliku", () => {
    expect(aggregateIdForSourceType("devices")).toBe(ALL_DEVICE_FILES_ID);
    expect(aggregateIdForSourceType("meter")).toBe(ALL_FILES_ID);
    expect(aggregateIdForSourceType(undefined)).toBe(ALL_FILES_ID);
  });

  it("liczy akcje w pliku urządzeń i rekordy w pliku licznika", () => {
    expect(formatRecordsCount(62, "devices")).toBe("62 akcje");
    expect(formatRecordsCount(1, "devices")).toBe("1 akcja");
    expect(formatRecordsCount(25, "devices")).toBe("25 akcji");
    expect(formatRecordsCount(744, "meter")).toBe("744 rekordy");
    expect(formatRecordsCount(2976, "meter")).toBe("2976 rekordów");
  });

  it("dla pliku urządzeń nie pokazuje rozdzielczości odczytów", () => {
    expect(formatDataResolution({ resolution_minutes: 15, data_source: "devices" })).toBe("akcje urządzeń");
    expect(formatDataResolution({ resolution_minutes: 15, data_source: "meter" })).toMatch(/^odczyty co 15\smin$/);
    expect(formatDataResolution({ resolution_minutes: 60 })).toBe("odczyty godzinowe");
  });
});
