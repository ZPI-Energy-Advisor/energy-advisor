import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import { fakeJwt } from "../test/auth";

// Login sprawdza VITE_GOOGLE_CLIENT_ID przy imporcie modułu, więc zmienna musi być ustawiona przed importem.
vi.hoisted(() => {
  vi.stubEnv("VITE_GOOGLE_CLIENT_ID", "test-client-id");
});

vi.mock("@react-oauth/google", () => ({
  GoogleLogin: ({ onSuccess }) => (
    <button type="button" onClick={() => onSuccess({ credential: "google-credential" })}>
      Google
    </button>
  ),
}));

const { default: Login } = await import("./Login");

const POLICY = { version: "2026-11-23", content: "# Polityka prywatności\n\nTreść polityki." };
const TOKENS = {
  access_token: fakeJwt({ sub: "user-1", type: "access" }),
  refresh_token: fakeJwt({ sub: "user-1", type: "refresh" }),
};
const policyRequired = () =>
  Object.assign(new Error("403"), {
    response: { status: 403, data: { code: "privacy_policy_required", detail: "Zaakceptuj politykę." } },
  });

function PageProbe() {
  return <p>strona: {useLocation().pathname}</p>;
}

const renderLogin = () =>
  render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<Login />} />
        <Route path="*" element={<PageProbe />} />
      </Routes>
    </MemoryRouter>,
  );

const dialog = () => screen.queryByRole("dialog", { name: "Zakładanie konta przez Google" });

describe("Login przez Google", () => {
  it("istniejące konto loguje bez pytania o politykę", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: TOKENS });
    renderLogin();

    fireEvent.click(screen.getByRole("button", { name: "Google" }));

    await waitFor(() => expect(screen.getByText("strona: /dashboard")).toBeTruthy());
    expect(post).toHaveBeenCalledWith("/auth/google", { google_code: "google-credential" });
    expect(dialog()).toBeNull();
  });

  it("przy pierwszym logowaniu pokazuje politykę i po akceptacji ponawia logowanie z wersją", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: POLICY });
    const post = vi
      .spyOn(apiClient, "post")
      .mockRejectedValueOnce(policyRequired())
      .mockResolvedValueOnce({ data: TOKENS });
    renderLogin();

    fireEvent.click(screen.getByRole("button", { name: "Google" }));
    expect(await screen.findByText("Treść polityki.")).toBeTruthy();
    expect(dialog()).toBeTruthy();

    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Akceptuję i zakładam konto" }));

    await waitFor(() => expect(screen.getByText("strona: /dashboard")).toBeTruthy());
    expect(post).toHaveBeenLastCalledWith("/auth/google", {
      google_code: "google-credential",
      accepted_policy_version: "2026-11-23",
    });
  });

  it("rezygnacja zamyka okno i mówi, że konto nie powstało", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: POLICY });
    const post = vi.spyOn(apiClient, "post").mockRejectedValueOnce(policyRequired());
    renderLogin();

    fireEvent.click(screen.getByRole("button", { name: "Google" }));
    await screen.findByText("Treść polityki.");
    fireEvent.click(screen.getByRole("button", { name: "Anuluj" }));

    expect(dialog()).toBeNull();
    expect(screen.getByRole("alert").textContent).toBe("Bez akceptacji polityki prywatności nie można założyć konta.");
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("inny błąd Google pokazuje komunikat bez okna polityki", async () => {
    vi.spyOn(apiClient, "post").mockRejectedValue(
      Object.assign(new Error("401"), { response: { status: 401, data: { detail: "Nieprawidłowy token" } } }),
    );
    renderLogin();

    fireEvent.click(screen.getByRole("button", { name: "Google" }));

    expect((await screen.findByRole("alert")).textContent).toBe("Błąd autoryzacji Google: Nieprawidłowy token");
    expect(dialog()).toBeNull();
  });
});
