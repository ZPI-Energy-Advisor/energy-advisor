import { useContext } from "react";
import { CurrentUserContext } from "../context/currentUserContext";

export function useCurrentUser() {
  const context = useContext(CurrentUserContext);
  if (!context) {
    throw new Error("useCurrentUser musi być użyty wewnątrz CurrentUserProvider");
  }
  return context;
}
