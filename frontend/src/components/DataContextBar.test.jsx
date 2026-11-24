import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DataContextBar from "./DataContextBar";

let context;
vi.mock("../hooks/useEnergyFiles", () => ({ useEnergyFiles: () => context }));

const FILE = {
  id: "f1",
  file_name: "licznik_2026.csv",
  source_type: "meter",
  status: "completed",
  data_start: "2026-01-01",
  data_end: "2026-03-31",
  days_count: 90,
};
const OTHER = { ...FILE, id: "f2", file_name: "drugi.csv" };
const FAILED = { ...FILE, id: "f3", file_name: "zepsuty.csv", status: "failed" };
const ALL = { ...FILE, id: "all", file_name: "Wszystkie pliki licznika", files_count: 2 };

beforeEach(() => {
  context = {
    selectedFile: FILE,
    selectedFileId: FILE.id,
    dateRange: { from: "2026-01-01", to: "2026-03-31" },
    results: { statistics: { resolution_minutes: 15 } },
    files: [FILE, OTHER, FAILED],
    total: 3,
    aggregate: ALL,
    devicesAggregate: null,
    isLoadingData: false,
    dataError: null,
    rangeError: null,
    clearDataError: vi.fn(),
    clearRangeError: vi.fn(),
    selectFile: vi.fn(),
    applyDateRange: vi.fn(),
  };
});

const renderBar = (props) =>
  render(
    <MemoryRouter>
      <DataContextBar title="Mój profil zużycia" {...props} />
    </MemoryRouter>,
  );

describe("DataContextBar", () => {
  it("w jednej linii pokazuje plik i okres, a kontrolki dopiero po kliknięciu", () => {
    renderBar();

    expect(screen.getByRole("heading", { name: "Mój profil zużycia" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Dane z: licznik_2026\.csv/ })).toBeTruthy();
    const range = screen.getByRole("button", { name: /Okres: 01\.01\.2026 – 31\.03\.2026, 90 dni, cały okres/ });
    expect(range.textContent).toMatch(/· 90 dni/);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByLabelText("Data od")).toBeNull();
  });

  it("wybiera inny plik z panelu bez przechodzenia do importu i pomija pliki z błędem", () => {
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: /Dane z:/ }));

    const panel = screen.getByRole("dialog", { name: "Wybór danych" });
    expect(within(panel).queryByText("zepsuty.csv")).toBeNull();
    expect(within(panel).getByText("Wszystkie pliki licznika")).toBeTruthy();
    fireEvent.click(within(panel).getByText("drugi.csv"));

    expect(context.selectFile).toHaveBeenCalledWith("f2");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("szybki wybór okresu stosuje zakres od razu i zamyka panel", () => {
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: /Okres:/ }));

    const panel = screen.getByRole("dialog", { name: "Wybór okresu" });
    fireEvent.change(within(panel).getByLabelText("Miesiąc"), { target: { value: "1" } });

    expect(context.applyDateRange).toHaveBeenCalledWith(expect.objectContaining({ from: "2026-02-01", to: "2026-02-28" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("Esc zamyka panel i wraca fokusem na przycisk", () => {
    renderBar();
    const trigger = screen.getByRole("button", { name: /Okres:/ });
    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");

    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("kliknięcie poza paskiem zamyka panel", () => {
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: /Dane z:/ }));

    fireEvent.mouseDown(document.body);

    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("błędy pliku i zakresu są widoczne pod paskiem, bez otwierania paneli", () => {
    context.dataError = "Nie udało się pobrać danych.";
    context.rangeError = "Zły zakres.";
    renderBar();

    expect(screen.getByText(/Nie udało się pobrać danych\. Wyświetlane są nadal dane poprzednio wybranego pliku/)).toBeTruthy();
    expect(screen.getByText(/Zły zakres\. Wyświetlane są nadal dane poprzedniego zakresu/)).toBeTruthy();
  });

  it("bez wybranego pliku zostaje sam tytuł", () => {
    context.selectedFile = null;
    renderBar();

    expect(screen.getByRole("heading", { name: "Mój profil zużycia" })).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("bez danych w pliku nie pokazuje wyboru okresu", () => {
    renderBar({ showRange: false });

    expect(screen.getByRole("button", { name: /Dane z:/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Okres:/ })).toBeNull();
  });
});
