import axios from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import apiClient, { SESSION_EXPIRED_EVENT, isAuthenticated } from "./client";
import { loginAs } from "../test/auth";

// Zamiast prawdziwego backendu: adapter axiosa odpowiada według handlera ustawionego w teście.
const response = (config, status, data = {}) => {
  const result = { status, statusText: String(status), data, headers: {}, config };
  if (status >= 400) {
    throw new axios.AxiosError(`HTTP ${status}`, "ERR_BAD_RESPONSE", config, null, result);
  }
  return result;
};

const networkError = (config) => {
  throw new axios.AxiosError("Network Error", "ERR_NETWORK", config);
};

let handler;
const requests = [];
const originalAdapters = {
  apiClient: apiClient.defaults.adapter,
  axios: axios.defaults.adapter,
};

beforeEach(() => {
  requests.length = 0;
  const adapter = async (config) => {
    requests.push(config);
    return handler(config);
  };
  apiClient.defaults.adapter = adapter;
  axios.defaults.adapter = adapter;
});

afterEach(() => {
  handler = undefined;
  apiClient.defaults.adapter = originalAdapters.apiClient;
  axios.defaults.adapter = originalAdapters.axios;
});

const isRefresh = (config) => config.url.endsWith("/auth/refresh");
const refreshCount = () => requests.filter(isRefresh).length;

const listenForSessionExpired = () => {
  const listener = vi.fn();
  window.addEventListener(SESSION_EXPIRED_EVENT, listener);
  return listener;
};

describe("apiClient", () => {
  it("dołącza access token do zapytań", async () => {
    loginAs();
    handler = (config) => response(config, 200);

    await apiClient.get("/energy-files");

    expect(requests[0].headers.Authorization).toBe(
      `Bearer ${localStorage.getItem("access_token")}`,
    );
  });

  it("po 401 odświeża tokeny i ponawia zapytanie", async () => {
    loginAs();
    handler = (config) => {
      if (isRefresh(config)) {
        return response(config, 200, { access_token: "nowy-access", refresh_token: "nowy-refresh" });
      }
      return config.headers.Authorization === "Bearer nowy-access"
        ? response(config, 200, { ok: true })
        : response(config, 401);
    };

    const result = await apiClient.get("/energy-files");

    expect(result.data).toEqual({ ok: true });
    expect(localStorage.getItem("access_token")).toBe("nowy-access");
    expect(localStorage.getItem("refresh_token")).toBe("nowy-refresh");
  });

  it("przy kilku równoległych 401 wykonuje tylko jeden refresh", async () => {
    loginAs();
    handler = async (config) => {
      if (isRefresh(config)) {
        await new Promise((resolve) => setTimeout(resolve, 10));
        return response(config, 200, { access_token: "nowy-access", refresh_token: "nowy-refresh" });
      }
      return config.headers.Authorization === "Bearer nowy-access"
        ? response(config, 200)
        : response(config, 401);
    };

    const results = await Promise.all([
      apiClient.get("/a"),
      apiClient.get("/b"),
      apiClient.get("/c"),
    ]);

    expect(results.map((r) => r.status)).toEqual([200, 200, 200]);
    expect(refreshCount()).toBe(1);
  });

  it("gdy serwer odrzuci refresh, czyści sesję i zgłasza jej wygaśnięcie", async () => {
    loginAs();
    const listener = listenForSessionExpired();
    handler = (config) => response(config, 401);

    await expect(apiClient.get("/energy-files")).rejects.toThrow();

    expect(isAuthenticated()).toBe(false);
    expect(localStorage.getItem("refresh_token")).toBeNull();
    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener(SESSION_EXPIRED_EVENT, listener);
  });

  it("przy braku sieci podczas refreshu nie wylogowuje", async () => {
    loginAs();
    const listener = listenForSessionExpired();
    handler = (config) => (isRefresh(config) ? networkError(config) : response(config, 401));

    await expect(apiClient.get("/energy-files")).rejects.toThrow();

    expect(isAuthenticated()).toBe(true);
    expect(listener).not.toHaveBeenCalled();
    window.removeEventListener(SESSION_EXPIRED_EVENT, listener);
  });

  it("nie odświeża tokenu przy błędach innych niż 401", async () => {
    loginAs();
    handler = (config) => response(config, 404);

    await expect(apiClient.get("/simulations/123")).rejects.toThrow();

    expect(refreshCount()).toBe(0);
    expect(isAuthenticated()).toBe(true);
  });
});
