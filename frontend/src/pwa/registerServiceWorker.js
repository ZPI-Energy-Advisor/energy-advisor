import { registerSW } from "virtual:pwa-register";

// Zdarzenie dla paska „Jest nowa wersja”: komponent AppStatusBanner nie importuje modułu pluginu PWA,
// więc działa też w testach (vitest), gdzie service workera nie ma.
export const UPDATE_READY_EVENT = "pwa:update-ready";

export function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  const updateServiceWorker = registerSW({
    onNeedRefresh() {
      window.dispatchEvent(new CustomEvent(UPDATE_READY_EVENT, { detail: { update: () => updateServiceWorker(true) } }));
    },
  });
}
