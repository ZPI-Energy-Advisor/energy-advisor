import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import ProtectedRoute from "./ProtectedRoute";
import { loginAs } from "../test/auth";

function LoginProbe() {
  const location = useLocation();
  return <p>logowanie, from: {location.state?.from?.pathname ?? "brak"}</p>;
}

const renderAt = (path) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/" element={<LoginProbe />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/prices" element={<p>ceny</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );

describe("ProtectedRoute", () => {
  it("niezalogowanego przekierowuje na logowanie i zapamiętuje ścieżkę", () => {
    renderAt("/prices");

    expect(screen.getByText("logowanie, from: /prices")).toBeTruthy();
  });

  it("zalogowanemu pokazuje chronioną stronę", () => {
    loginAs();

    renderAt("/prices");

    expect(screen.getByText("ceny")).toBeTruthy();
  });
});
