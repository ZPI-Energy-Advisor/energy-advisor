import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

const menu = () => screen.getByRole("navigation", { name: "Menu główne" });
const menuLinks = () => within(menu()).getAllByRole("link").map((link) => link.textContent);

describe("Layout: menu", () => {
  it("prowadzi w kolejności pracy: dane, analiza, dom", () => {
    renderLayout({ home_owner: true, profile: { has_pv: true } });

    expect(within(menu()).getAllByRole("list").map((list) => list.getAttribute("aria-labelledby"))).toEqual([
      "nav-Dane",
      "nav-Analiza",
      "nav-Dom",
    ]);
    expect(menuLinks()).toEqual([
      "Profil",
      "Import danych",
      "Pulpit",
      "Taryfy",
      "Ceny dynamiczne",
      "Fotowoltaika",
      "Optymalizacja",
      "Mój dom",
      "Plan na jutro",
    ]);
    expect(screen.getByRole("list", { name: "Analiza" })).toBeTruthy();
  });

  it("właściciel domu widzi Mój dom i Plan na jutro", () => {
    renderLayout({ home_owner: true });

    expect(screen.getByRole("link", { name: "Mój dom" }).getAttribute("href")).toBe("/home");
    expect(screen.getByRole("link", { name: "Plan na jutro" }).getAttribute("href")).toBe("/plan");
  });

  it.each([[{ home_owner: false }], [null]])("inne konta nie widzą „Mój dom”, ale mają Plan na jutro (%o)", (me) => {
    renderLayout(me);

    expect(screen.getByRole("link", { name: "Pulpit" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Mój dom" })).toBeNull();
    // Plan na jutro jest dla każdego: dotyczy urządzeń z plików, nie domu Smart Home.
    expect(screen.getByRole("link", { name: "Plan na jutro" }).getAttribute("href")).toBe("/plan");
    expect(screen.getByRole("list", { name: "Dom" })).toBeTruthy();
  });

  it.each([
    [{ profile: { has_pv: true } }, true],
    [{ profile: { has_pv: false } }, false],
    [null, false],
  ])("Fotowoltaika tylko z PV w profilu (%o)", (me, visible) => {
    renderLayout(me);

    expect(Boolean(screen.queryByRole("link", { name: "Fotowoltaika" }))).toBe(visible);
  });

  it("ma jeden ekran taryf", () => {
    renderLayout(null);

    expect(screen.getByRole("link", { name: "Taryfy" }).getAttribute("href")).toBe("/tariffs");
    expect(screen.queryByRole("link", { name: "Wyniki kalkulacji" })).toBeNull();
  });

  it("tytuł karty to nazwa ekranu, także gdy pozycja nie jest w menu", () => {
    user.me = null;
    render(
      <MemoryRouter initialEntries={["/schedule"]}>
        <Layout />
      </MemoryRouter>,
    );
    expect(document.title).toBe("Optymalizacja · Energy Advisor");
  });

  it("na telefonie menu otwiera się przyciskiem i zamyka po wyborze pozycji albo Escape", () => {
    renderLayout(null);
    const toggle = screen.getByRole("button", { name: "Otwórz menu" });

    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(document.getElementById("app-menu").className).not.toContain("-translate-x-full");

    fireEvent.click(screen.getByRole("link", { name: "Taryfy" }));
    expect(screen.getByRole("button", { name: "Otwórz menu" }).getAttribute("aria-expanded")).toBe("false");
    expect(document.getElementById("app-menu").className).toContain("-translate-x-full");

    fireEvent.click(screen.getByRole("button", { name: "Otwórz menu" }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.getByRole("button", { name: "Otwórz menu" }).getAttribute("aria-expanded")).toBe("false");
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
