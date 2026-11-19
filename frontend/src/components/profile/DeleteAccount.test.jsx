import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import apiClient from "../../api/client";
import DeleteAccount from "./DeleteAccount";

function LoginStub() {
  const location = useLocation();
  return <p>Logowanie{location.state?.accountDeleted ? ": konto usunięte" : ""}</p>;
}

const renderSection = () =>
  render(
    <MemoryRouter initialEntries={["/profile"]}>
      <Routes>
        <Route path="/profile" element={<DeleteAccount email="Jan@Example.com" />} />
        <Route path="/" element={<LoginStub />} />
      </Routes>
    </MemoryRouter>,
  );

const typeEmail = (value) => fireEvent.change(screen.getByLabelText(/żeby potwierdzić/), { target: { value } });

describe("DeleteAccount", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("przycisk działa dopiero po wpisaniu e-maila konta (bez względu na wielkość liter)", () => {
    renderSection();
    const button = screen.getByRole("button", { name: "Usuń konto" });

    expect(button.disabled).toBe(true);
    typeEmail("jan@example");
    expect(button.disabled).toBe(true);
    typeEmail(" jan@example.com ");
    expect(button.disabled).toBe(false);
  });

  it("usuwa konto, czyści sesję i wraca do logowania", async () => {
    localStorage.setItem("access_token", "a");
    localStorage.setItem("refresh_token", "r");
    const remove = vi.spyOn(apiClient, "delete").mockResolvedValue({ status: 204 });
    renderSection();

    typeEmail("jan@example.com");
    fireEvent.click(screen.getByRole("button", { name: "Usuń konto" }));

    expect(await screen.findByText("Logowanie: konto usunięte")).toBeTruthy();
    expect(remove).toHaveBeenCalledWith("/users/me", { data: { confirm_email: "jan@example.com" } });
    expect(localStorage.getItem("access_token")).toBeNull();
    expect(localStorage.getItem("refresh_token")).toBeNull();
  });

  it("gdy backend odmówi, zostaje na profilu z komunikatem", async () => {
    localStorage.setItem("access_token", "a");
    vi.spyOn(apiClient, "delete").mockRejectedValue({
      response: { data: { detail: "Nie udało się odłączyć domu Smart Home, więc konto nie zostało usunięte." } },
    });
    renderSection();

    typeEmail("jan@example.com");
    fireEvent.click(screen.getByRole("button", { name: "Usuń konto" }));

    expect((await screen.findByRole("alert")).textContent).toContain("konto nie zostało usunięte");
    await waitFor(() => expect(screen.getByRole("button", { name: "Usuń konto" }).disabled).toBe(false));
    expect(localStorage.getItem("access_token")).toBe("a");
  });
});
