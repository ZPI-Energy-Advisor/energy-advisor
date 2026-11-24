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

    expect(screen.getByRole("status").textContent).toBe("Sesja wygasła, zaloguj się ponownie.");
  });

  it("po usunięciu konta mówi, że dane zostały usunięte", () => {
    renderLogin({ accountDeleted: true });

    expect(screen.getByRole("status").textContent).toBe("Konto i wszystkie dane zostały usunięte.");
  });

  it("błąd logowania pokazuje jako alert, nie jako informację", () => {
    renderLogin();

    fireEvent.click(screen.getByRole("button", { name: "Zaloguj się" }));

    expect(screen.getByRole("alert").textContent).toBe("Wypełnij wszystkie pola!");
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

  describe("rejestracja", () => {
    const openRegistration = () => {
      fireEvent.click(screen.getByRole("button", { name: "Nie masz konta? Zarejestruj się" }));
      fireEvent.change(screen.getByPlaceholderText("imienazwisko@student.pwr.edu.pl"), {
        target: { value: "nowy@example.com" },
      });
      fireEvent.change(screen.getByPlaceholderText("••••••••"), { target: { value: "Haslo123!" } });
    };
    const submit = () => fireEvent.click(screen.getByRole("button", { name: "Zarejestruj się" }));
    const policyCheckbox = () => screen.getByRole("checkbox", { name: /Polityką prywatności/ });

    it("pokazuje zgodę z linkiem do polityki i informację o usuwaniu nieaktywnych kont", () => {
      renderLogin();
      openRegistration();

      expect(policyCheckbox().checked).toBe(false);
      const link = screen.getByRole("link", { name: "Polityką prywatności" });
      expect(link.getAttribute("href")).toBe("/privacy");
      expect(link.getAttribute("target")).toBe("_blank");
      expect(screen.getByText(/przez 12 miesięcy, usuwamy razem ze wszystkimi danymi/)).toBeTruthy();
    });

    it("bez akceptacji polityki nie wysyła formularza", () => {
      const post = vi.spyOn(apiClient, "post");
      renderLogin();
      openRegistration();

      submit();

      expect(screen.getByRole("alert").textContent).toBe("Zaakceptuj politykę prywatności, aby założyć konto.");
      expect(post).not.toHaveBeenCalled();
    });

    it("wysyła wersję polityki pobraną z backendu", async () => {
      vi.spyOn(apiClient, "get").mockResolvedValue({ data: { version: "2026-11-23", content: "" } });
      const post = mockSuccessfulLogin();
      renderLogin();
      openRegistration();

      fireEvent.click(policyCheckbox());
      submit();

      await waitFor(() => expect(screen.getByText("strona: /dashboard")).toBeTruthy());
      expect(post).toHaveBeenCalledWith("/auth/register", {
        email: "nowy@example.com",
        password: "Haslo123!",
        accepted_policy_version: "2026-11-23",
      });
    });

    it("po przełączeniu na logowanie i z powrotem zgoda jest odznaczona", () => {
      renderLogin();
      openRegistration();
      fireEvent.click(policyCheckbox());

      fireEvent.click(screen.getByRole("button", { name: "Masz już konto? Zaloguj się" }));
      fireEvent.click(screen.getByRole("button", { name: "Nie masz konta? Zarejestruj się" }));

      expect(policyCheckbox().checked).toBe(false);
    });
  });

  it("ma link do polityki prywatności także przy logowaniu", () => {
    renderLogin();

    expect(screen.getByRole("link", { name: "Polityka prywatności" }).getAttribute("href")).toBe("/privacy");
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("zalogowanego użytkownika na „/” przenosi na Dashboard", () => {
    loginAs();

    renderLogin();

    expect(screen.getByText("strona: /dashboard")).toBeTruthy();
  });
});
