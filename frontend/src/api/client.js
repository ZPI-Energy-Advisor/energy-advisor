import axios from "axios";

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1",
});

const decodeTokenPayload = (token) => {
  try {
    const payload = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const paddedPayload = payload.padEnd(payload.length + ((4 - (payload.length % 4)) % 4), "=");
    return JSON.parse(atob(paddedPayload));
  } catch {
    return null;
  }
};

export const saveAuthResponse = (authResponse, email) => {
  const { access_token: accessToken, refresh_token: refreshToken } = authResponse;
  const payload = decodeTokenPayload(accessToken);

  localStorage.setItem("access_token", accessToken);
  localStorage.setItem("refresh_token", refreshToken);
  localStorage.setItem(
    "user",
    JSON.stringify({ id: payload?.sub, email: email || payload?.email }),
  );
};

export const SESSION_EXPIRED_EVENT = "auth:session-expired";

export const clearAuth = () => {
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
  localStorage.removeItem("user");
};

export const isAuthenticated = () => {
  try {
    const user = JSON.parse(localStorage.getItem("user"));
    return Boolean(user?.id && localStorage.getItem("access_token"));
  } catch {
    return false;
  }
};

// Backend rotuje refresh token, więc równoległe 401 muszą czekać na jeden wspólny refresh.
let refreshPromise = null;

const refreshTokens = (refreshToken) => {
  if (!refreshPromise) {
    refreshPromise = axios
      .post(`${apiClient.defaults.baseURL}/auth/refresh`, {
        refresh_token: refreshToken,
      })
      .then((response) => {
        localStorage.setItem("access_token", response.data.access_token);
        localStorage.setItem("refresh_token", response.data.refresh_token);
        return response.data.access_token;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
};

apiClient.interceptors.request.use((config) => {
  const accessToken = localStorage.getItem("access_token");
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    const refreshToken = localStorage.getItem("refresh_token");

    if (
      error.response?.status !== 401 ||
      originalRequest?._retry ||
      !refreshToken ||
      originalRequest?.url?.endsWith("/auth/refresh")
    ) {
      return Promise.reject(error);
    }

    originalRequest._retry = true;

    try {
      const accessToken = await refreshTokens(refreshToken);
      originalRequest.headers.Authorization = `Bearer ${accessToken}`;
      return apiClient(originalRequest);
    } catch (refreshError) {
      // Bez odpowiedzi serwera (np. brak sieci) sesja może być nadal ważna.
      if (refreshError.response) {
        clearAuth();
        window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
      }
      return Promise.reject(refreshError);
    }
  },
);

export default apiClient;
