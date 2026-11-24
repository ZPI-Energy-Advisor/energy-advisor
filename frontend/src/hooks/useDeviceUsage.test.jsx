import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import { EnergyFileContext } from "../context/energyFileContext";
import { createResponseCache } from "../utils/responseCache";
import { useDeviceUsage } from "./useDeviceUsage";

vi.mock("../api/client", () => ({ default: { get: vi.fn() } }));

const request = (level) => ({ sourceId: "all-devices", params: { level } });

const renderUsage = (cache, initial) => {
  const wrapper = ({ children }) => (
    <EnergyFileContext.Provider value={{ deviceUsageCache: cache, cacheScope: "u1|1|0" }}>{children}</EnergyFileContext.Provider>
  );
  return renderHook(({ value }) => useDeviceUsage(value), { wrapper, initialProps: { value: initial } });
};

describe("useDeviceUsage", () => {
  beforeEach(() => apiClient.get.mockReset());

  it("powrót do wcześniejszego widoku bierze odpowiedź z pamięci, bez zapytania", async () => {
    apiClient.get.mockImplementation((url, config = {}) => Promise.resolve({ data: { level: config.params?.level } }));
    const cache = createResponseCache(10);
    const { result, rerender } = renderUsage(cache, request("category"));
    await waitFor(() => expect(result.current.data).toEqual({ level: "category" }));

    rerender({ value: request("type") });
    await waitFor(() => expect(result.current.data).toEqual({ level: "type" }));
    rerender({ value: request("category") });

    expect(result.current.data).toEqual({ level: "category" });
    expect(result.current.isLoading).toBe(false);
    expect(apiClient.get).toHaveBeenCalledTimes(2);
  });

  it("spóźniona odpowiedź na wcześniejszy widok nie podmienia nowszego", async () => {
    let releaseFirst;
    apiClient.get
      .mockImplementationOnce(() => new Promise((resolve) => (releaseFirst = () => resolve({ data: { level: "category" } }))))
      .mockImplementationOnce(() => Promise.resolve({ data: { level: "type" } }));
    const { result, rerender } = renderUsage(createResponseCache(10), request("category"));

    rerender({ value: request("type") });
    await waitFor(() => expect(result.current.data).toEqual({ level: "type" }));
    await act(async () => releaseFirst());

    expect(result.current.data).toEqual({ level: "type" });
  });
});
