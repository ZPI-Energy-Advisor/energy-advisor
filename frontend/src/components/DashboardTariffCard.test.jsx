import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DashboardTariffCard from "./DashboardTariffCard";

let comparisonState;
vi.mock("../hooks/useEnergyFiles", () => ({
  useEnergyFiles: () => ({ viewSource: { fileId: "f1", range: null }, cacheScope: "s", comparisonCache: null }),
}));
vi.mock("../hooks/useTariffComparison", () => ({ useTariffComparison: () => comparisonState }));

const ENTRIES = [
  { key: "G13", label: "G13", name: null, payable_gross: 500 },
  { key: "G12w", label: "G12w", name: "Taryfa weekendowa", payable_gross: 470 },
];
const comparison = (recommendation, fromProfile = true) => ({
  from_profile: fromProfile, tariffs: ENTRIES, recommendation,
});
const PROFILE = { tariff_type: "G13", exists: true };
const CURRENT = { label: "G13", operator: "TAURON" };

const renderCard = () =>
  render(
    <MemoryRouter>
      <DashboardTariffCard enabled profileTariff={PROFILE} currentTariff={CURRENT} loadError={null} />
    </MemoryRouter>,
  );

describe("DashboardTariffCard", () => {
  beforeEach(() => {
    comparisonState = { comparison: null, isLoading: false };
  });

  it("pokazuje, ile można zaoszczędzić i na jakiej taryfie, z linkiem do analizy", () => {
    comparisonState.comparison = comparison({
      tariff: "G12w", is_current: false, saving: 30, saving_percent: 6,
    });
    renderCard();

    expect(screen.getByText("Możesz zaoszczędzić")).toBeTruthy();
    expect(screen.getByText(/30,00 zł/)).toBeTruthy();
    expect(screen.getByText("G12w · Taryfa weekendowa")).toBeTruthy();
    // Bez szacunku miesięcznego: każdy miesiąc jest inny, liczy się kwota z wybranego okresu.
    expect(screen.queryByText(/miesięcznie/)).toBeNull();
    expect(screen.getByRole("link", { name: /Zobacz analizę taryf/ }).getAttribute("href")).toBe("/tariffs");
  });

  it("gdy obecna taryfa jest najkorzystniejsza, potwierdza to", () => {
    comparisonState.comparison = comparison({ tariff: "G13", is_current: true, saving: 0 });
    renderCard();

    expect(screen.getByText("Taryfa G13 · TAURON")).toBeTruthy();
    expect(screen.getByText(/Najkorzystniejsza z taryf operatora/)).toBeTruthy();
  });

  it("bez profilu zostaje dotychczasowa karta z prośbą o profil", () => {
    comparisonState.comparison = comparison({ tariff: "G12w", is_current: false, saving: null }, false);
    renderCard();

    expect(screen.getByText("Aktualna taryfa")).toBeTruthy();
    expect(screen.queryByText("Możesz zaoszczędzić")).toBeNull();
  });

  it("podczas liczenia porównania pokazuje zarys karty", () => {
    comparisonState = { comparison: null, isLoading: true };
    renderCard();

    expect(screen.getByRole("status").textContent).toMatch(/Liczymy porównanie taryf/);
  });
});
