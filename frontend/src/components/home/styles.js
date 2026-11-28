// Ekran „Mój dom” korzysta ze wspólnych przycisków i kart aplikacji (components/ui.jsx).
export { CARD, PRIMARY_BUTTON, SECONDARY_BUTTON } from "../uiStyles";

// Plakietka planu (ZP-114): obrys zamiast wypełnienia, żeby nie mylić jej ze stanem urządzenia.
export const PLAN_BADGE = {
  active: "border-emerald-300 text-emerald-800",
  ready: "border-sky-300 text-sky-800",
  error: "border-red-300 text-red-700",
  neutral: "border-gray-300 text-gray-600",
};

export const STATE_BADGE = {
  active: "bg-emerald-100 text-emerald-800",
  ready: "bg-sky-100 text-sky-800",
  error: "bg-red-100 text-red-700",
  neutral: "bg-gray-100 text-gray-600",
};
