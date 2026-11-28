import { Link } from "react-router-dom";
import PrivacyPolicyContent from "../components/PrivacyPolicyContent";
import { formatPolicyVersion, usePrivacyPolicy } from "../hooks/usePrivacyPolicy";
import { alertClass } from "../components/uiStyles";

// Publiczna strona polityki prywatności (bez logowania), otwierana z ekranu logowania i z menu aplikacji.
function PrivacyPolicyPage() {
  const { policy, error } = usePrivacyPolicy();

  return (
    <div className="min-h-screen bg-gray-50 px-4 py-10 pt-[calc(2.5rem+env(safe-area-inset-top))]">
      <div className="mx-auto max-w-3xl rounded-lg bg-white p-6 shadow-sm md:p-10">
        <Link to="/" className="text-sm font-medium text-emerald-600 hover:text-emerald-500">
          ← Energy Advisor
        </Link>
        <div className="mt-6">
          {error && (
            <p role="alert" className={alertClass("error")}>
              {error}
            </p>
          )}
          {!policy && !error && <p className="text-sm text-gray-500">Wczytywanie…</p>}
          {policy && (
            <>
              <PrivacyPolicyContent markdown={policy.content} />
              <p className="mt-8 border-t border-gray-100 pt-4 text-xs text-gray-500">
                Wersja z dnia {formatPolicyVersion(policy.version)}
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default PrivacyPolicyPage;
