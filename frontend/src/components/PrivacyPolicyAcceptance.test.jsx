import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import PrivacyPolicyAcceptance from "./PrivacyPolicyAcceptance";

const POLICY = { version: "2026-11-23", content: "# Polityka prywatności\n\nTreść polityki." };

const renderAcceptance = ({ onAccept = vi.fn(), onCancel = vi.fn() } = {}) => {
  render(
    <PrivacyPolicyAcceptance
      title="Zmiana polityki prywatności"
      intro="Zaakceptuj nową wersję."
      acceptLabel="Akceptuję"
      onAccept={onAccept}
      cancelLabel="Wyloguj się"
      onCancel={onCancel}
    />,
  );
  return { onAccept, onCancel };
};

const acceptButton = () => screen.getByRole("button", { name: "Akceptuję" });

describe("PrivacyPolicyAcceptance", () => {
  it("pokazuje treść polityki i nie pozwala zaakceptować bez zaznaczenia", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: POLICY });

    renderAcceptance();

    expect(await screen.findByText("Treść polityki.")).toBeTruthy();
    expect(screen.getByRole("dialog", { name: "Zmiana polityki prywatności" })).toBeTruthy();
    expect(screen.getByRole("checkbox").closest("label").textContent).toContain("wersja z dnia 23.11.2026");
    expect(acceptButton().disabled).toBe(true);
  });

  it("po zaznaczeniu przekazuje wersję, którą pokazało", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: POLICY });
    const { onAccept } = renderAcceptance({ onAccept: vi.fn().mockResolvedValue() });
    await screen.findByText("Treść polityki.");

    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(acceptButton());

    await waitFor(() => expect(onAccept).toHaveBeenCalledWith("2026-11-23"));
  });

  it("gdy zapis się nie uda, pokazuje błąd i pozwala spróbować ponownie", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: POLICY });
    renderAcceptance({ onAccept: vi.fn().mockRejectedValue(new Error("500")) });
    await screen.findByText("Treść polityki.");

    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(acceptButton());

    expect((await screen.findByRole("alert")).textContent).toBe(
      "Nie udało się zapisać akceptacji. Spróbuj ponownie.",
    );
    expect(acceptButton().disabled).toBe(false);
  });

  it("nie zamyka się klawiszem Esc, tylko przyciskiem rezygnacji", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: POLICY });
    const { onCancel } = renderAcceptance();
    await screen.findByText("Treść polityki.");

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onCancel).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Zamknij" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Wyloguj się" }));
    expect(onCancel).toHaveBeenCalled();
  });

  it("bez polityki nie da się zaakceptować", async () => {
    vi.spyOn(apiClient, "get").mockRejectedValue(new Error("brak sieci"));

    renderAcceptance();

    expect((await screen.findByRole("alert")).textContent).toBe("Nie udało się pobrać polityki prywatności.");
    expect(screen.getByRole("checkbox").disabled).toBe(true);
    expect(acceptButton().disabled).toBe(true);
  });
});
