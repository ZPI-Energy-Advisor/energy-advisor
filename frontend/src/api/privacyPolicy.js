import apiClient from "./client";

export const PRIVACY_POLICY_PATH = "/privacy";
export const POLICY_REQUIRED_CODE = "privacy_policy_required";

// Polityka i jej wersja pochodzą z backendu, więc frontend wysyła akceptację dokładnie tej wersji, którą pokazał.
export const fetchPrivacyPolicy = async () => {
  const { data } = await apiClient.get("/legal/privacy-policy");
  return data;
};

export const acceptPrivacyPolicy = async (version) => {
  const { data } = await apiClient.post("/users/me/privacy-consent", { version });
  return data;
};

export const isPolicyRequiredError = (error) => error?.response?.data?.code === POLICY_REQUIRED_CODE;
