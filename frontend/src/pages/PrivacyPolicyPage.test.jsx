import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import { AppRoutes } from "../App";

vi.mock("@react-oauth/google", () => ({ GoogleLogin: () => null }));

const POLICY = {
  version: "2026-11-23",
  content: "# Polityka prywatności\n\n## Administrator\n\nNapisz na **energy-advisor@gmail.com**.\n\n- dostęp\n- usunięcie",
};

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={["/privacy"]}>
      <Routes>
        <Route path="*" element={<AppRoutes />} />
      </Routes>
    </MemoryRouter>,
  );

describe("PrivacyPolicyPage", () => {
  it("jest dostępna bez logowania i pokazuje treść z backendu z datą wersji", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: POLICY });

    renderPage();

    expect(await screen.findByRole("heading", { name: "Polityka prywatności" })).toBeTruthy();
    expect(get).toHaveBeenCalledWith("/legal/privacy-policy");
    expect(screen.getByRole("heading", { name: "Administrator" })).toBeTruthy();
    expect(screen.getByText("energy-advisor@gmail.com").tagName).toBe("STRONG");
    expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual(["dostęp", "usunięcie"]);
    expect(screen.getByText("Wersja z dnia 23.11.2026")).toBeTruthy();
  });

  it("treść nie jest wstawiana jako HTML", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({
      data: { version: "2026-11-23", content: "<img src=x onerror=alert(1)>" },
    });

    renderPage();

    expect(await screen.findByText("<img src=x onerror=alert(1)>")).toBeTruthy();
    expect(document.querySelector("img")).toBeNull();
  });

  it("pokazuje błąd, gdy nie udało się pobrać polityki", async () => {
    vi.spyOn(apiClient, "get").mockRejectedValue(new Error("brak sieci"));

    renderPage();

    expect((await screen.findByRole("alert")).textContent).toBe("Nie udało się pobrać polityki prywatności.");
  });
});
