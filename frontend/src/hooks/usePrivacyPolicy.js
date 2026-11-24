import { useEffect, useState } from "react";
import { fetchPrivacyPolicy } from "../api/privacyPolicy";

// Wersja polityki to data publikacji RRRR-MM-DD; na ekranie DD.MM.RRRR.
export const formatPolicyVersion = (version) => {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(version ?? "");
  return match ? `${match[3]}.${match[2]}.${match[1]}` : version;
};

export function usePrivacyPolicy() {
  const [state, setState] = useState({ policy: null, error: null });

  useEffect(() => {
    let cancelled = false;
    fetchPrivacyPolicy()
      .then((policy) => {
        if (!cancelled) setState({ policy, error: null });
      })
      .catch(() => {
        if (!cancelled) setState({ policy: null, error: "Nie udało się pobrać polityki prywatności." });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
