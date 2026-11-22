import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import apiClient from "../api/client";
import { usePlanRun } from "./usePlanRun";

describe("usePlanRun", () => {
  afterEach(() => vi.restoreAllMocks());

  it("spóźniona odpowiedź GET nie nadpisuje przebiegu podmienionego po poleceniu", async () => {
    let answer;
    vi.spyOn(apiClient, "get").mockImplementation(() => new Promise((resolve) => { answer = resolve; }));
    const { result } = renderHook(() => usePlanRun("2026-10-19T12:00:00+02:00", "sim-1"));

    act(() => result.current.replace({ id: "run-1", status: "ended" }));
    await act(async () => answer({ data: { id: "run-1", status: "running" } }));

    expect(result.current.run.status).toBe("ended");
  });

  it("odświeżenie po poleceniu znowu bierze przebieg z backendu", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValue({ data: { id: "run-2", status: "running" } });
    const { result } = renderHook(() => usePlanRun("2026-10-19T12:00:00+02:00", "sim-1"));

    act(() => result.current.replace(null));
    act(() => result.current.refresh());

    await waitFor(() => expect(result.current.run?.id).toBe("run-2"));
  });
});
