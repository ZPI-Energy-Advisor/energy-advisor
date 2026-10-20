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

  it("nic nie renderuje bez raportu", () => {
    const { container } = render(<ImportReportSummary report={null} />);

    expect(container.innerHTML).toBe("");
  });
});
