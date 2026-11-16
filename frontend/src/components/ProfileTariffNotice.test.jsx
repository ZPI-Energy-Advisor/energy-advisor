import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import ProfileTariffNotice from "./ProfileTariffNotice";
import { CurrentUserContext } from "../context/currentUserContext";

const G12 = { code: "G12", label: "G12", operator: "TAURON", dynamic: false };

const renderNotice = (user, pricingNote = null) =>
  render(
    <MemoryRouter>
      <CurrentUserContext.Provider value={{ isReady: true, loadError: null, refresh: vi.fn(), ...user }}>
        <ProfileTariffNotice missingProfile=" - brak profilu." pricingNote={pricingNote} />
      </CurrentUserContext.Provider>
    </MemoryRouter>,
  );

describe("ProfileTariffNotice", () => {
  it("przy błędzie pobrania konta pokazuje błąd zamiast prośby o profil", () => {
    renderNotice({ currentTariff: null, profileTariff: null, loadError: "Błąd serwera." });

    expect(screen.getByRole("alert").textContent).toContain("Błąd serwera.");
    expect(screen.getByRole("button", { name: "Spróbuj ponownie" })).toBeTruthy();
    expect(screen.queryByText("Uzupełnij profil")).toBeNull();
  });

  it("bez profilu prosi o jego uzupełnienie", () => {
    renderNotice({ currentTariff: null, profileTariff: { exists: false, needs_update: false, tariff_type: null } });

    expect(screen.getByRole("link", { name: "Uzupełnij profil" })).toBeTruthy();
    expect(screen.getByText(/brak profilu/)).toBeTruthy();
  });

  it("bez profilu pokazuje też uwagę o przyciętym okresie kosztów", () => {
    renderNotice(
      { currentTariff: null, profileTariff: { exists: false, needs_update: false, tariff_type: null } },
      "Dni przed 24.08.2024 nie liczymy.",
    );

    expect(screen.getByRole("link", { name: "Uzupełnij profil" })).toBeTruthy();
    expect(screen.getByText("Dni przed 24.08.2024 nie liczymy.")).toBeTruthy();
  });

  it("profil w starym formacie wymaga ponownego uzupełnienia", () => {
    renderNotice({ currentTariff: G12, profileTariff: { exists: true, needs_update: true, tariff_type: "G12" } });

    expect(screen.getByText(/Zmienił się format profilu/)).toBeTruthy();
  });

  it("pokazuje uwagę o taryfie kosztów, gdy operator nie ma stawek taryfy z profilu", () => {
    renderNotice(
      { currentTariff: null, profileTariff: { exists: true, needs_update: false, tariff_type: "G13" } },
      "Operator PGE nie ma w cenniku stawek taryfy G13 dla tego okresu, więc koszty liczymy dla taryfy G11.",
    );

    expect(screen.getByText(/koszty liczymy dla taryfy G11/)).toBeTruthy();
  });

  it("nic nie pokazuje, gdy taryfa z profilu ma ceny", () => {
    const { container } = renderNotice({
      currentTariff: G12,
      profileTariff: { exists: true, needs_update: false, tariff_type: "G12" },
    });

    expect(container.textContent).toBe("");
  });
});
