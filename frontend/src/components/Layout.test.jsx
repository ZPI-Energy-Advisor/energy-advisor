import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import Layout from "./Layout";
import { CurrentUserContext } from "../context/currentUserContext";
import apiClient from "../api/client";

const user = { me: null, refresh: vi.fn() };

vi.mock("../context/CurrentUserProvider", () => ({
  CurrentUserProvider: ({ children }) => (
    <CurrentUserContext.Provider value={{ me: user.me, refresh: user.refresh }}>{children}</CurrentUserContext.Provider>
  ),
}));
vi.mock("../context/EnergyFileProvider", () => ({ EnergyFileProvider: ({ children }) => children }));

const renderLayout = (me) => {
  user.me = me;
  render(
    <MemoryRouter>
      <Layout />
    </MemoryRouter>,
  );
};

describe("Layout", () => {
  it("pokazuje „Mój dom” właścicielowi domu", () => {
    renderLayout({ home_owner: true });

    expect(screen.getByRole("link", { name: "Mój dom" }).getAttribute("href")).toBe("/home");
  });

  it.each([[{ home_owner: false }], [null]])("ukrywa „Mój dom” przed innymi kontami (%o)", (me) => {
    renderLayout(me);

    expect(screen.getByRole("link", { name: "Dashboard" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Mój dom" })).toBeNull();
    // Plan na jutro jest dla każdego: dotyczy urządzeń z plików, nie domu Smart Home.
    expect(screen.getByRole("link", { name: "Plan na jutro" }).getAttribute("href")).toBe("/plan");
  });

  it("ma jeden ekran taryf", () => {
    renderLayout(null);

    expect(screen.getByRole("link", { name: "Analiza taryf" }).getAttribute("href")).toBe("/tariffs");
    expect(screen.queryByRole("link", { name: "Wyniki kalkulacji" })).toBeNull();
  });
});

const POLICY = { version: "2026-11-23", content: "# Polityka prywatności\n\nNowa treść polityki." };
const meWithPolicy = (needsAcceptance) => ({
  home_owner: false,
  privacy_policy: {
    current_version: "2026-11-23",
    accepted_version: needsAcceptance ? null : "2026-11-23",
    accepted_at: null,
    needs_acceptance: needsAcceptance,
  },
});

const renderWithPage = (me) => {
  user.me = me;
  user.refresh = vi.fn();
  render(
    <MemoryRouter initialEntries={["/dashboard"]}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/dashboard" element={<p>treść dashboardu</p>} />
        </Route>
        <Route path="/" element={<p>ekran logowania</p>} />
      </Routes>
    </MemoryRouter>,
  );
};

const gate = () => screen.queryByRole("dialog", { name: "Zmiana polityki prywatności" });

describe("Layout: akceptacja polityki prywatności", () => {
  it("ma link do polityki prywatności w menu", () => {
    renderLayout(null);

    const link = screen.getByRole("link", { name: "Polityka prywatności" });
    expect(link.getAttribute("href")).toBe("/privacy");
    expect(link.getAttribute("target")).toBe("_blank");
  });

  it("konto z akceptacją aktualnej wersji widzi stronę bez okna", () => {
    renderWithPage(meWithPolicy(false));

    expect(screen.getByText("treść dashboardu")).toBeTruthy();
    expect(gate()).toBeNull();
  });

  it("bez akceptacji aktualnej wersji zasłania stronę oknem polityki", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: POLICY });

    renderWithPage(meWithPolicy(true));

    expect(gate()).toBeTruthy();
    expect(screen.queryByText("treść dashboardu")).toBeNull();
    expect(await screen.findByText("Nowa treść polityki.")).toBeTruthy();
  });

  it("akceptacja zapisuje wersję i odświeża dane konta", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: POLICY });
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: {} });
    renderWithPage(meWithPolicy(true));
    await screen.findByText("Nowa treść polityki.");

    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Akceptuję" }));

    await waitFor(() => expect(user.refresh).toHaveBeenCalled());
    expect(post).toHaveBeenCalledWith("/users/me/privacy-consent", { version: "2026-11-23" });
  });

  it("zamiast akceptacji można się wylogować", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: POLICY });
    renderWithPage(meWithPolicy(true));
    await screen.findByText("Nowa treść polityki.");

    const logoutButtons = screen.getAllByRole("button", { name: "Wyloguj się" });
    fireEvent.click(logoutButtons[logoutButtons.length - 1]);

    expect(await screen.findByText("ekran logowania")).toBeTruthy();
  });
});
