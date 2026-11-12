import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import { PAUSED_POLL_MS, RUNNING_POLL_MS, useHomeState } from "./useHomeState";

const state = (running) => ({ hub_available: true, clock: { sim_time: "2026-10-19T12:00:00+02:00", running, speed: 288 } });

const setHidden = (hidden) => {
  Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
  document.dispatchEvent(new Event("visibilitychange"));
};

// Przepuszcza odpowiedź zamockowanego API i zaplanowanie kolejnego odświeżenia.
const flush = () => act(() => vi.advanceTimersByTimeAsync(0));

describe("useHomeState", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    setHidden(false);
  });

  it("odświeża co 2 s przy działającym zegarze i rzadziej przy pauzie", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: state(true) });
    renderHook(() => useHomeState());
    await flush();
    expect(get).toHaveBeenCalledTimes(1);

    await act(() => vi.advanceTimersByTimeAsync(RUNNING_POLL_MS));
    expect(get).toHaveBeenCalledTimes(2);

    get.mockResolvedValue({ data: state(false) });
    await act(() => vi.advanceTimersByTimeAsync(RUNNING_POLL_MS));
    expect(get).toHaveBeenCalledTimes(3);
    await act(() => vi.advanceTimersByTimeAsync(PAUSED_POLL_MS - 1));
    expect(get).toHaveBeenCalledTimes(3);
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(get).toHaveBeenCalledTimes(4);
  });

  it("nie wysyła kolejnego żądania, zanim poprzednie się nie skończy", async () => {
    let resolve;
    const get = vi.spyOn(apiClient, "get").mockImplementation(() => new Promise((done) => { resolve = done; }));
    renderHook(() => useHomeState());

    await act(() => vi.advanceTimersByTimeAsync(RUNNING_POLL_MS * 5));
    expect(get).toHaveBeenCalledTimes(1);

    resolve({ data: state(true) });
    await flush();
    await act(() => vi.advanceTimersByTimeAsync(RUNNING_POLL_MS));
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("wstrzymuje odpytywanie w ukrytej karcie i odświeża po powrocie", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: state(true) });
    renderHook(() => useHomeState());
    await flush();

    setHidden(true);
    await act(() => vi.advanceTimersByTimeAsync(RUNNING_POLL_MS * 10));
    expect(get).toHaveBeenCalledTimes(1);

    await act(async () => setHidden(false));
    await flush();
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("zachowuje ostatni stan, gdy odświeżenie się nie uda", async () => {
    vi.spyOn(apiClient, "get")
      .mockResolvedValueOnce({ data: state(true) })
      .mockRejectedValueOnce({ response: { data: { detail: "Hub niedostępny" } } });
    const { result } = renderHook(() => useHomeState());
    await flush();

    await act(() => vi.advanceTimersByTimeAsync(RUNNING_POLL_MS));

    expect(result.current.state.clock.running).toBe(true);
    expect(result.current.error).toBe("Hub niedostępny");
  });

  it("refresh pobiera stan od razu", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: state(false) });
    const { result } = renderHook(() => useHomeState());
    await flush();

    await act(async () => result.current.refresh());
    await flush();

    expect(get).toHaveBeenCalledTimes(2);
  });
});
