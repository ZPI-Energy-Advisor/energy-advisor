import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import Login from "./Login";
import apiClient from "../api/client";
import { fakeJwt, loginAs } from "../test/auth";

vi.mock("@react-oauth/google", () => ({ GoogleLogin: () => null }));

function PageProbe() {
  const { pathname, search } = useLocation();
  return <p>strona: {pathname + search}</p>;
}

const renderLogin = (state) =>
  render(
    <MemoryRouter initialEntries={[{ pathname: "/", state }]}>
      <Routes>
        <Route path="/" element={<Login />} />
        <Route path="*" element={<PageProbe />} />
      </Routes>
    </MemoryRouter>,
  );

const submitLoginForm = () => {
  fireEvent.change(screen.getByPlaceholderText("imienazwisko@student.pwr.edu.pl"), {
    target: { value: "jan@example.com" },
  });
  fireEvent.change(screen.getByPlaceholderText("••••••••"), {
    target: { value: "Haslo123!" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Zaloguj się" }));
};

const mockSuccessfulLogin = () =>
  vi.spyOn(apiClient, "post").mockResolvedValue({
    data: {
      access_token: fakeJwt({ sub: "user-1", type: "access" }),
      refresh_token: fakeJwt({ sub: "user-1", type: "refresh" }),
    },
  });

describe("Login", () => {
  it("pokazuje komunikat po wygaśnięciu sesji", () => {
    renderLogin({ sessionExpired: true });

    expect(screen.getByText("Sesja wygasła, zaloguj się ponownie.")).toBeTruthy();
  });

  it("bez wygaśnięcia sesji nie pokazuje komunikatu", () => {
    renderLogin();

    expect(screen.queryByText("Sesja wygasła, zaloguj się ponownie.")).toBeNull();
  });

  it("po zalogowaniu wraca na ścieżkę z state.from", async () => {
    mockSuccessfulLogin();
    renderLogin({ from: { pathname: "/prices", search: "?zakres=dzien" } });

    submitLoginForm();

    await waitFor(() => expect(screen.getByText("strona: /prices?zakres=dzien")).toBeTruthy());
  });

  it("po zalogowaniu bez state.from przechodzi na Dashboard", async () => {
    mockSuccessfulLogin();
    renderLogin();

    submitLoginForm();

    await waitFor(() => expect(screen.getByText("strona: /dashboard")).toBeTruthy());
  });

  it("zalogowanego użytkownika na „/” przenosi na Dashboard", () => {
    loginAs();

    renderLogin();

    expect(screen.getByText("strona: /dashboard")).toBeTruthy();
  });
});
