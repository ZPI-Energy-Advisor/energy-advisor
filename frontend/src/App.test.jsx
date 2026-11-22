import { render, screen } from "@testing-library/react";
import { MemoryRouter, Outlet, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AppRoutes } from "./App";
import { loginAs } from "./test/auth";

vi.mock("./components/Layout", () => ({ default: () => <Outlet /> }));
vi.mock("./pages/TariffsPage", () => ({
  default: function TariffsPage() {
    return <p>Analiza taryf pod {useLocation().pathname}</p>;
  },
}));

describe("AppRoutes", () => {
  it.each(["/tariffs", "/results", "/calculations"])("%s prowadzi do Analizy taryf", (path) => {
    loginAs();
    render(
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>,
    );

    expect(screen.getByText("Analiza taryf pod /tariffs")).toBeTruthy();
  });
});
