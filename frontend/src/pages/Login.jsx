import React, { useState } from "react";
import axios from "axios";
import { GoogleLogin } from "@react-oauth/google";

function Login() {
  // Stany dla pól formularza
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");

  // Stan przełączający między Logowaniem (false) a Rejestracją (true)
  const [isRegister, setIsRegister] = useState(false);

  // --- LOGIKA GOOGLE SSO ---
  const handleGoogleSuccess = async (credentialResponse) => {
    try {
      const token = credentialResponse.credential;

      // Wysyłamy token z frontu do backendu FastAPI
      const response = await axios.post("http://localhost:8000/auth/google", {
        id_token: token,
      });

      setMessage(`Sukces Google! Zalogowano jako: ${response.data.user.email}`);
      // W przyszłości połączysz to z nawigacją do wewnątrz Energy Advisor (np. navigate('/dashboard'))
    } catch (error) {
      if (error.response && error.response.data.detail) {
        setMessage(`Błąd autoryzacji Google: ${error.response.data.detail}`);
      } else {
        setMessage("Błąd połączenia z serwerem podczas logowania Google.");
      }
    }
  };

  const handleGoogleError = () => {
    setMessage("Błąd wygenerowania okna logowania Google.");
  };

  // --- LOGIKA FORMULARZA LOKALNEGO ---
  const handleSubmit = async (e) => {
    e.preventDefault();
    setMessage("");

    if (!email || !password) {
      setMessage("Wypełnij wszystkie pola!");
      return;
    }

    try {
      if (isRegister) {
        const response = await axios.post(
          "http://localhost:8000/auth/register",
          {
            email: email,
            password: password,
          },
        );
        setMessage(`Sukces! Zarejestrowano konto: ${response.data.user.email}`);
        setIsRegister(false);
      } else {
        setMessage(
          "Logowanie e-mail/hasło będzie zaprogramowane w kolejnym tasku.",
        );
      }
    } catch (error) {
      if (error.response && error.response.data.detail) {
        setMessage(`Błąd: ${error.response.data.detail}`);
      } else {
        setMessage("Błąd połączenia z serwerem.");
      }
    }
  };

  return (
    <div className="flex min-h-screen w-full bg-white">
      {/* LEWA KOLUMNA */}
      <div className="hidden w-1/2 flex-col items-center justify-center bg-slate-900 px-12 lg:flex">
        <h1 className="mb-4 text-5xl font-bold tracking-tight text-white">
          Energy Advisor
        </h1>
        <p className="text-lg text-slate-300">
          Zoptymalizuj koszty prądu w swoim domu
        </p>
        <div className="mt-8 h-1 w-16 rounded bg-emerald-500"></div>
      </div>

      {/* PRAWA KOLUMNA */}
      <div className="flex w-full flex-col items-center justify-center px-8 lg:w-1/2">
        <div className="w-full max-w-md space-y-8">
          <div>
            <h2 className="text-3xl font-bold text-gray-900">
              {isRegister ? "Rejestracja" : "Logowanie"}
            </h2>
            <p className="mt-2 text-gray-600">
              {isRegister
                ? "Utwórz nowe konto użytkownika"
                : "Wprowadź dane dostępowe"}
            </p>
          </div>

          {/* Formularz lokalny */}
          <form onSubmit={handleSubmit} className="mt-8 space-y-6">
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
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 focus:border-emerald-500 focus:outline-none focus:ring-emerald-500 sm:text-sm"
                />
              </div>
            </div>

            <button
              type="submit"
              className="flex w-full justify-center rounded-md border border-transparent bg-emerald-600 py-2 px-4 text-sm font-medium text-white shadow-sm hover:bg-emerald-700 focus:outline-none focus:ring-2 focus:ring-emerald-500"
            >
              {isRegister ? "Zarejestruj się" : "Zaloguj się"}
            </button>
          </form>

          {/* Wiadomości zwrotne z systemu */}
          {message && (
            <div className="mt-4 text-center text-sm font-medium text-emerald-600 bg-emerald-50 p-2 rounded">
              {message}
            </div>
          )}

          {/* SEKCJA GOOGLE SSO */}
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

          {/* Przełącznik widoków */}
          <div className="mt-6 text-center">
            <button
              type="button"
              onClick={() => {
                setIsRegister(!isRegister);
                setMessage("");
              }}
              className="text-sm font-medium text-emerald-600 hover:text-emerald-500"
            >
              {isRegister
                ? "Masz już konto? Zaloguj się"
                : "Nie masz konta? Zarejestruj się"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default Login;
