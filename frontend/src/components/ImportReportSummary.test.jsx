import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ImportReportSummary from "./ImportReportSummary";

const baseReport = {
  detected_format: "tauron_v2",
  format_label: "Tauron eLicznik (Data i godzina; Wartosc[kWh/kvar]; Rodzaj energii)",
  rows_total: 2976,
  rows_imported: 2976,
  rows_ignored: 0,
  resolution_minutes: 15,
  skipped_rows: { count: 0, examples: [] },
};

describe("ImportReportSummary", () => {
  it("pokazuje rozpoznany format i liczbę zaimportowanych wierszy", () => {
    render(<ImportReportSummary report={baseReport} />);

    expect(screen.getByText(baseReport.format_label)).toBeTruthy();
    expect(screen.getByText(/2976 wierszy z 2976 · odczyty co 15\smin/)).toBeTruthy();
    expect(screen.getByText(/Wszystkie wiersze z poborem energii zostały zaimportowane/)).toBeTruthy();
  });

  it("wypisuje odrzucone wiersze z numerami i informuje o pozostałych", () => {
    const report = {
      ...baseReport,
      rows_total: 15,
      rows_imported: 1,
      rows_ignored: 2,
      resolution_minutes: 60,
      skipped_rows: {
        count: 12,
        examples: [
          { row: 3, reason: "nieprawidłowa wartość zużycia: „abc”" },
          { row: 4, reason: "nieprawidłowa data: „jutro”" },
        ],
      },
    };

    render(<ImportReportSummary report={report} />);

    expect(screen.getByText("Odrzucono 12 błędnych wierszy")).toBeTruthy();
    expect(screen.getByText("Wiersz 3:")).toBeTruthy();
    expect(screen.getByText(/nieprawidłowa data: „jutro”/)).toBeTruthy();
    expect(screen.getByText("…i 10 wierszy więcej.")).toBeTruthy();
    expect(screen.getByText(/2 wiersze z energią oddaną do sieci/)).toBeTruthy();
    expect(screen.getByText(/1 wiersz z 15 · odczyty godzinowe/)).toBeTruthy();
  });

  it("dla pliku urządzeń opisuje akcje zamiast wierszy", () => {
    const report = {
      detected_format: "devices",
      format_label: "Plik urządzeń smart home (JSON)",
      unit: "action",
      rows_total: 62,
      rows_imported: 60,
      rows_ignored: 0,
      resolution_minutes: 15,
      skipped_rows: {
        count: 3,
        examples: [
          { row: 16, action_id: "act_0016", reason: "suma profilu różni się od energy_kwh" },
          { row: 40, reason: "nieznane urządzenie" },
        ],
      },
    };

    render(<ImportReportSummary report={report} />);

    expect(screen.getByText("60 akcji z 62")).toBeTruthy();
    expect(screen.getByText("Odrzucono 3 błędne akcje")).toBeTruthy();
    expect(screen.getByText("Akcja 16 (act_0016):")).toBeTruthy();
    expect(screen.getByText("Akcja 40:")).toBeTruthy();
    expect(screen.getByText("…i 1 akcja więcej.")).toBeTruthy();
  });

  it("dla pliku urządzeń pokazuje urządzenia, kategorie, pobór i produkcję PV", () => {
    const report = {
      detected_format: "devices",
      format_label: "Plik urządzeń smart home (JSON)",
      unit: "action",
      rows_total: 62,
      rows_imported: 62,
      rows_ignored: 0,
      resolution_minutes: 15,
      skipped_rows: { count: 0, examples: [] },
      devices: {
        devices_count: 24,
        actions_count: 62,
        categories: ["AGD", "OZE"],
        consumption_kwh: 52.49,
        pv_production_kwh: 14.6,
      },
    };

    render(<ImportReportSummary report={report} />);

    expect(screen.getByText("24 urządzenia · AGD, OZE")).toBeTruthy();
    expect(screen.getByText("pobór 52,49 kWh · produkcja PV 14,6 kWh")).toBeTruthy();
  });

  it("nic nie renderuje bez raportu", () => {
    const { container } = render(<ImportReportSummary report={null} />);

    expect(container.innerHTML).toBe("");
  });
});
