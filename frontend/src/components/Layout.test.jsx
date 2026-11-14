import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import Layout from "./Layout";
import { CurrentUserContext } from "../context/currentUserContext";

const user = { me: null };

vi.mock("../context/CurrentUserProvider", () => ({
  CurrentUserProvider: ({ children }) => (
    <CurrentUserContext.Provider value={{ me: user.me }}>{children}</CurrentUserContext.Provider>
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
});
