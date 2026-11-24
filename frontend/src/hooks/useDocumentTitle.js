import { useEffect } from "react";

export const APP_NAME = "Energy Advisor";

// Tytuł karty przeglądarki: nazwa ekranu i aplikacji, żeby kilka otwartych kart dało się odróżnić.
export function useDocumentTitle(title) {
  useEffect(() => {
    document.title = title ? `${title} · ${APP_NAME}` : APP_NAME;
  }, [title]);
}
