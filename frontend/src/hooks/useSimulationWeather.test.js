import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import { useSimulationWeather } from "./useSimulationWeather";

const interval = (start, cloud, temperature, ghi = 100) => ({
  start, source: "archive", temperature_c: temperature, cloud_cover_pct: cloud, ghi_w_m2: ghi, tilted_w_m2: [],
});

const DAY = {
  location_approximate: true,
  intervals: [interval("2026-10-12T22:00:00Z", 90, 4.2, 0), interval("2026-10-12T22:15:00Z", 10, 3.9, 0)],
};

describe("useSimulationWeather", () => {
  afterEach(() => vi.restoreAllMocks());

  it("pobiera pogodę doby symulacji w strefie domu i zwraca kwadrans zegara", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: DAY });
    const { result, rerender } = renderHook(({ time }) => useSimulationWeather(time), {
      initialProps: { time: "2026-10-12T22:20:00Z" },
    });

    await waitFor(() => expect(result.current?.cloud_cover_pct).toBe(10));
    expect(get).toHaveBeenCalledWith("/weather/forecast", { params: { date: "2026-10-13" } });
    expect(result.current.approximate).toBe(true);

    rerender({ time: "2026-10-12T22:05:00Z" });
    expect(result.current.cloud_cover_pct).toBe(90);
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("bez pogody nic nie pokazuje", async () => {
    const get = vi.spyOn(apiClient, "get").mockRejectedValue(new Error("503"));
    const { result } = renderHook(() => useSimulationWeather("2026-10-12T22:20:00Z"));

    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(result.current).toBeNull();
  });
});
