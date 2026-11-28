import { useState } from "react";
import apiClient, { isAuthenticated, saveAuthResponse } from "../api/client";
import { GoogleLogin } from "@react-oauth/google";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { FiCalendar, FiCheck, FiCircle, FiPieChart, FiTrendingDown } from "react-icons/fi";
import PrivacyPolicyAcceptance from "../components/PrivacyPolicyAcceptance";
import { PRIVACY_POLICY_PATH, fetchPrivacyPolicy, isPolicyRequiredError } from "../api/privacyPolicy";

// Co daje aplikacja: trzy krótkie korzyści na ekranie logowania (widoczne od szerokiego ekranu).
const BENEFITS = [
  { Icon: FiPieChart, title: "Porównaj taryfy na swoich danych", text: "Zobacz, ile zapłaciłbyś w każdej taryfie operatora, także z fotowoltaiką." },
  { Icon: FiTrendingDown, title: "Sprawdź, kiedy prąd jest najtańszy", text: "Ceny dynamiczne na dziś i jutro, godzina po godzinie." },
  { Icon: FiCalendar, title: "Zaplanuj pracę urządzeń na jutro", text: "Pranie, zmywanie i ładowanie auta w najtańszych godzinach." },
];
import logo from "../assets/logo/logo.svg";
import logoDark from "../assets/logo/logo-dark.svg";
import { buttonClass } from "../components/uiStyles";

const GOOGLE_LOGIN_ENABLED = Boolean(import.meta.env.VITE_GOOGLE_CLIENT_ID);
const SESSION_EXPIRED_MESSAGE = "Sesja wygasła, zaloguj się ponownie.";
const ACCOUNT_DELETED_MESSAGE = "Konto i wszystkie dane zostały usunięte.";
const POLICY_NOT_ACCEPTED_MESSAGE = "Bez akceptacji polityki prywatności nie można założyć konta.";
const INVALID_EMAIL_MESSAGE = "Podaj poprawny adres e-mail, np. jan.kowalski@example.com.";
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
// Te same zasady co na serwerze (AuthService.validate_password).
const PASSWORD_RULES = [
  { label: "co najmniej 8 znaków", test: (value) => value.length >= 8 },
  { label: "wielka litera", test: (value) => /\p{Lu}/u.test(value) },
  { label: "mała litera", test: (value) => /\p{Ll}/u.test(value) },
  { label: "cyfra", test: (value) => /\p{N}/u.test(value) },
  { label: "znak specjalny, np. ! ? # -", test: (value) => /[^\p{L}\p{N}]/u.test(value) },
];

// Błąd z serwera jednym zdaniem, bez technicznych dopisków (np. angielskiego komunikatu walidacji maila).
function errorMessage(detail) {
  if (!Array.isArray(detail)) return detail;
  const first = detail[0] ?? {};
  if ((first.loc ?? []).includes("email")) return INVALID_EMAIL_MESSAGE;
  return String(first.msg ?? "").replace("Value error, ", "");
}

function initialMessage(state) {
  if (state?.accountDeleted) return ACCOUNT_DELETED_MESSAGE;
  return state?.sessionExpired ? SESSION_EXPIRED_MESSAGE : "";
}

function getRedirectPath(from) {
  if (!from?.pathname || from.pathname === "/") {
    return "/dashboard";
  }
  return `${from.pathname}${from.search || ""}${from.hash || ""}`;
}

function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const location = useLocation();
  const [message, setMessage] = useState(initialMessage(location.state));
  const [isRegister, setIsRegister] = useState(false);
  const [policyAccepted, setPolicyAccepted] = useState(false);
  // Token Google nowego konta, które czeka na akceptację polityki (backend: 403 privacy_policy_required).
  const [pendingGoogleToken, setPendingGoogleToken] = useState(null);
  useDocumentTitle(isRegister ? "Rejestracja" : "Logowanie");
  const navigate = useNavigate();
  const redirectTo = getRedirectPath(location.state?.from);

  const loginWithGoogle = async (token, acceptedPolicyVersion) => {
    try {
      const response = await apiClient.post("/auth/google", {
        google_code: token,
        ...(acceptedPolicyVersion ? { accepted_policy_version: acceptedPolicyVersion } : {}),
      });

      saveAuthResponse(response.data, null);
      navigate(redirectTo, { replace: true });
    } catch (error) {
      if (!acceptedPolicyVersion && isPolicyRequiredError(error)) {
        setPendingGoogleToken(token);
        return;
      }
      setPendingGoogleToken(null);
      if (error.response && error.response.data.detail) {
        setMessage(`Błąd autoryzacji Google: ${error.response.data.detail}`);
      } else {
        setMessage("Błąd połączenia z serwerem podczas logowania Google.");
      }
    }
  };

  const handleGoogleSuccess = (credentialResponse) => {
    setMessage("");
    return loginWithGoogle(credentialResponse.credential);
  };

  const handleGoogleError = () => {
    setMessage("Błąd wygenerowania okna logowania Google.");
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setMessage("");

    if (!email || !password) {
      setMessage("Wpisz adres e-mail i hasło.");
      return;
    }

    if (!EMAIL_PATTERN.test(email.trim())) {
      setMessage(INVALID_EMAIL_MESSAGE);
      return;
    }

    if (isRegister && !PASSWORD_RULES.every((rule) => rule.test(password))) {
      setMessage("Hasło nie spełnia zasad podanych pod polem hasła.");
      return;
    }

    if (isRegister && !policyAccepted) {
      setMessage("Zaakceptuj politykę prywatności, aby założyć konto.");
      return;
    }

    try {
      if (isRegister) {
        const { version } = await fetchPrivacyPolicy();
        const response = await apiClient.post(
          "/auth/register",
          {
            email: email.trim(),
            password: password,
            accepted_policy_version: version,
          },
        );
        saveAuthResponse(response.data, email);
        navigate(redirectTo, { replace: true });
      } else {
        const response = await apiClient.post("/auth/login", {
          email: email.trim(),
          password: password,
        });

        saveAuthResponse(response.data, email);
        navigate(redirectTo, { replace: true });
      }
    } catch (error) {
      if (error.response && error.response.data.detail) {
        setMessage(errorMessage(error.response.data.detail));
      } else {
        setMessage("Błąd połączenia z serwerem.");
      }
    }
  };

  if (isAuthenticated()) {
    return <Navigate to={redirectTo} replace />;
  }

  return (
    <div className="flex min-h-screen w-full bg-white pt-[env(safe-area-inset-top)]">
      <div className="hidden w-1/2 flex-col items-center justify-center bg-slate-900 px-12 lg:flex">
        <img src={logoDark} alt="" className="mb-8 h-32 w-auto" />
        <h1 className="mb-4 text-5xl font-bold tracking-tight text-white text-center">
          Energy Advisor
        </h1>
        <p className="text-lg text-slate-300 text-center">
          Zoptymalizuj koszty prądu w swoim domu
        </p>
        <div className="mt-8 h-1 w-16 rounded bg-emerald-500"></div>
        <ul className="mt-10 max-w-sm space-y-5">
          {BENEFITS.map(({ Icon, title, text }) => (
            <li key={title} className="flex items-start gap-4">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-400">
                <Icon aria-hidden="true" className="text-xl" />
              </span>
              <span>
                <span className="block font-semibold text-white">{title}</span>
                <span className="block text-sm text-slate-400">{text}</span>
              </span>
            </li>
          ))}
        </ul>
      </div>

      <div className="flex w-full flex-col items-center justify-center px-4 sm:px-8 lg:w-1/2">
        <div className="w-full max-w-md space-y-8">
          <div className="text-center sm:text-left">
            {/* Logo widoczne tylko na mobile dla spójności */}
            <h1 className="lg:hidden mb-8 flex items-center justify-center gap-3 text-3xl font-bold tracking-tight text-slate-900 sm:justify-start">
              <img src={logo} alt="" className="h-10 w-auto" />
              <span>
                Energy<span className="text-emerald-500">Advisor</span>
              </span>
            </h1>
            <h2 className="text-2xl sm:text-3xl font-bold text-gray-900">
              {isRegister ? "Rejestracja" : "Logowanie"}
            </h2>
            <p className="mt-2 text-sm sm:text-base text-gray-600">
              {isRegister
                ? "Utwórz nowe konto użytkownika"
                : "Wprowadź dane dostępowe"}
            </p>
          </div>

          {/* noValidate: format maila sprawdzamy sami, żeby każdy błąd był w tym samym polu pod formularzem. */}
          <form onSubmit={handleSubmit} noValidate className="mt-8 space-y-6">
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  Email
                </label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="imienazwisko@student.pwr.edu.pl"
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 focus:border-emerald-500 focus:outline-none focus:ring-emerald-500 sm:text-sm"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  Hasło
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  aria-describedby={isRegister ? "password-rules" : undefined}
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 focus:border-emerald-500 focus:outline-none focus:ring-emerald-500 sm:text-sm"
                />
                {isRegister && (
                  <ul id="password-rules" aria-label="Zasady hasła" className="mt-2 grid grid-cols-1 gap-1 text-xs sm:grid-cols-2">
                    {PASSWORD_RULES.map((rule) => {
                      const met = rule.test(password);
                      return (
                        <li key={rule.label} className={`flex items-center gap-1.5 ${met ? "text-emerald-700" : "text-gray-500"}`}>
                          {met ? <FiCheck aria-hidden="true" /> : <FiCircle aria-hidden="true" className="text-[0.6rem]" />}
                          <span>{rule.label}</span>
                          <span className="sr-only">{met ? "(spełnione)" : "(niespełnione)"}</span>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            </div>

            {isRegister && (
              <div className="space-y-2">
                <label className="flex items-start gap-2 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    checked={policyAccepted}
                    onChange={(e) => setPolicyAccepted(e.target.checked)}
                    className="mt-0.5 h-4 w-4 rounded border-gray-300 text-emerald-600 focus:ring-emerald-500"
                  />
                  <span>
                    Zapoznałem/am się z{" "}
                    <Link
                      to={PRIVACY_POLICY_PATH}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-medium text-emerald-600 hover:text-emerald-500"
                    >
                      Polityką prywatności
                    </Link>{" "}
                    i ją akceptuję.
                  </span>
                </label>
              </div>
            )}

            <button
              type="submit"
              className={`${buttonClass("primary", "lg")} w-full shadow-sm`}
            >
              {isRegister ? "Zarejestruj się" : "Zaloguj się"}
            </button>
          </form>

          {message && (
            <div
              role={message === SESSION_EXPIRED_MESSAGE || message === ACCOUNT_DELETED_MESSAGE ? "status" : "alert"}
              className={`mt-4 text-center text-sm font-medium p-3 rounded ${
                message === ACCOUNT_DELETED_MESSAGE
                  ? "text-emerald-700 bg-emerald-50"
                  : message === SESSION_EXPIRED_MESSAGE
                    ? "text-amber-700 bg-amber-50"
                    : "text-red-600 bg-red-50"
              }`}
            >
              {message}
            </div>
          )}

          {GOOGLE_LOGIN_ENABLED && (
            <div className="mt-6">
              <div className="relative">
                <div className="absolute inset-0 flex items-center">
                  <div className="w-full border-t border-gray-300"></div>
                </div>
                <div className="relative flex justify-center text-sm">
                  <span className="bg-white px-2 text-gray-500">
                    lub {isRegister ? "zarejestruj" : "zaloguj"} przez
                  </span>
                </div>
              </div>

              <div className="mt-6 flex justify-center">
                <GoogleLogin
                  onSuccess={handleGoogleSuccess}
                  onError={handleGoogleError}
                  useOneTap
                />
              </div>
            </div>
          )}

          <div className="mt-6 text-center">
            <button
              type="button"
              onClick={() => {
                setIsRegister(!isRegister);
                setPolicyAccepted(false);
                setMessage("");
              }}
              className="text-sm font-medium text-emerald-600 hover:text-emerald-500"
            >
              {isRegister
                ? "Masz już konto? Zaloguj się"
                : "Nie masz konta? Zarejestruj się"}
            </button>
          </div>

          <p className="text-center text-xs text-gray-500">
            <Link to={PRIVACY_POLICY_PATH} className="hover:text-gray-700 hover:underline">
              Polityka prywatności
            </Link>
          </p>
        </div>
      </div>

      {pendingGoogleToken && (
        <PrivacyPolicyAcceptance
          title="Zakładanie konta przez Google"
          intro="To pierwsze logowanie tym kontem Google. Przed założeniem konta zapoznaj się z polityką prywatności."
          acceptLabel="Akceptuję i zakładam konto"
          onAccept={(version) => loginWithGoogle(pendingGoogleToken, version)}
          cancelLabel="Anuluj"
          onCancel={() => {
            setPendingGoogleToken(null);
            setMessage(POLICY_NOT_ACCEPTED_MESSAGE);
          }}
        />
      )}
    </div>
  );
}

export default Login;