import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import ProfileTariffNotice from "./ProfileTariffNotice";
import { CurrentUserContext } from "../context/currentUserContext";

const G12 = { id: 2, code: "G12", type: "strefowa", profile_tariff_type: "G12" };

const renderNotice = (user) =>
  render(
    <MemoryRouter>
      <CurrentUserContext.Provider value={{ isReady: true, loadError: null, refresh: vi.fn(), ...user }}>
        <ProfileTariffNotice missingProfile=" - brak profilu." missingPrices="Brak cen taryfy." />
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

  it("profil w starym formacie wymaga ponownego uzupełnienia", () => {
    renderNotice({ currentTariff: G12, profileTariff: { exists: true, needs_update: true, tariff_type: "G12" } });

    expect(screen.getByText(/Zmienił się format profilu/)).toBeTruthy();
  });

  it("informuje o taryfie z profilu bez cen w bazie", () => {
    renderNotice({ currentTariff: null, profileTariff: { exists: true, needs_update: false, tariff_type: "G13" } });

    expect(screen.getByText("Brak cen taryfy.")).toBeTruthy();
  });

  it("nic nie pokazuje, gdy taryfa z profilu ma ceny", () => {
    const { container } = renderNotice({
      currentTariff: G12,
      profileTariff: { exists: true, needs_update: false, tariff_type: "G12" },
    });

    expect(container.textContent).toBe("");
  });
});
