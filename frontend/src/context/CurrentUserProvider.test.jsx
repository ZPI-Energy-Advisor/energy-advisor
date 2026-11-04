import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import { CurrentUserProvider } from "./CurrentUserProvider";
import { useCurrentUser } from "../hooks/useCurrentUser";

const G12 = { id: 2, code: "G12", type: "strefowa", profile_tariff_type: "G12" };

const meWith = (currentTariff, profile) => ({
  email: "jan@example.com",
  provider: "local",
  current_tariff: currentTariff,
  profile,
});

function Probe() {
  const { currentTariff, profileTariff, isReady, refresh } = useCurrentUser();
  if (!isReady) return <p>ładowanie</p>;
  return (
    <>
      <p>aktualna: {currentTariff?.code ?? "brak"}</p>
      <p>profil: {profileTariff?.exists ? profileTariff.tariff_type : "brak"}</p>
      <button onClick={refresh}>odśwież</button>
    </>
  );
}

const renderProvider = () =>
  render(
    <CurrentUserProvider>
      <Probe />
    </CurrentUserProvider>,
  );

describe("CurrentUserProvider", () => {
  it("pobiera taryfę z profilu przez /users/me", async () => {
    const get = vi
      .spyOn(apiClient, "get")
      .mockResolvedValue({ data: meWith(G12, { exists: true, tariff_type: "G12" }) });

    renderProvider();

    expect(await screen.findByText("aktualna: G12")).toBeTruthy();
    expect(screen.getByText("profil: G12")).toBeTruthy();
    expect(get).toHaveBeenCalledWith("/users/me");
  });

  it("bez profilu nie ma aktualnej taryfy", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({
      data: meWith(null, { exists: false, tariff_type: null }),
    });

    renderProvider();

    expect(await screen.findByText("aktualna: brak")).toBeTruthy();
    expect(screen.getByText("profil: brak")).toBeTruthy();
  });

  it("refresh pobiera taryfę zapisaną właśnie w profilu", async () => {
    const get = vi
      .spyOn(apiClient, "get")
      .mockResolvedValueOnce({ data: meWith(null, { exists: false, tariff_type: null }) })
      .mockResolvedValueOnce({ data: meWith(G12, { exists: true, tariff_type: "G12" }) });
    renderProvider();
    await screen.findByText("aktualna: brak");

    await act(async () => screen.getByRole("button", { name: "odśwież" }).click());

    expect(screen.getByText("aktualna: G12")).toBeTruthy();
    expect(get).toHaveBeenCalledTimes(2);
  });
});
