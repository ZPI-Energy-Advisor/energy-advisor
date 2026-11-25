import { useState } from "react";
import PrivacyPolicyContent from "./PrivacyPolicyContent";
import { formatPolicyVersion, usePrivacyPolicy } from "../hooks/usePrivacyPolicy";

// Okno akceptacji polityki, którego nie da się zamknąć bez decyzji: przy pierwszym logowaniu przez Google
// i po zmianie wersji polityki. `onAccept` dostaje wersję, którą użytkownik widział.
function PrivacyPolicyAcceptance({ title, intro, acceptLabel, onAccept, cancelLabel, onCancel }) {
  const { policy, error: loadError } = usePrivacyPolicy();
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const accept = async () => {
    setBusy(true);
    setError(null);
    try {
      await onAccept(policy.version);
    } catch {
      setError("Nie udało się zapisać akceptacji. Spróbuj ponownie.");
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="flex max-h-[90vh] w-full max-w-3xl flex-col rounded-lg bg-white shadow-xl"
      >
        <div className="border-b border-gray-100 px-5 py-4">
          <h3 className="font-bold text-gray-900">{title}</h3>
          <p className="mt-1 text-sm text-gray-600">{intro}</p>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {loadError && (
            <p role="alert" className="rounded bg-red-50 p-3 text-sm text-red-600">
              {loadError}
            </p>
          )}
          {!policy && !loadError && <p className="text-sm text-gray-500">Wczytywanie…</p>}
          {policy && <PrivacyPolicyContent markdown={policy.content} />}
        </div>

        <div className="space-y-3 border-t border-gray-100 px-5 py-4">
          <label className="flex items-start gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={checked}
              disabled={!policy}
              onChange={(event) => setChecked(event.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-gray-300 text-emerald-600 focus:ring-emerald-500"
            />
            <span>
              Zapoznałem/am się z Polityką prywatności
              {policy ? ` (wersja z dnia ${formatPolicyVersion(policy.version)})` : ""} i ją akceptuję.
            </span>
          </label>
          {error && (
            <p role="alert" className="text-sm text-red-600">
              {error}
            </p>
          )}
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button
              type="button"
              onClick={onCancel}
              disabled={busy}
              className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              {cancelLabel}
            </button>
            <button
              type="button"
              onClick={accept}
              disabled={!policy || !checked || busy}
              className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {acceptLabel}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default PrivacyPolicyAcceptance;
