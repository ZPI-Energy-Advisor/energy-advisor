import { useState } from "react";
import { FiTrash2 } from "react-icons/fi";
import { useNavigate } from "react-router-dom";
import apiClient, { clearAuth } from "../../api/client";
import { getApiErrorMessage } from "../../utils/energyFiles";

const sameEmail = (typed, email) => typed.trim().toLowerCase() === (email ?? "").trim().toLowerCase();

// Usunięcie konta ze wszystkimi danymi (ZP-53): potwierdzenie wpisaniem e-maila konta, potem wylogowanie.
function DeleteAccount({ email }) {
  const [typed, setTyped] = useState("");
  const [isDeleting, setIsDeleting] = useState(false);
  const [error, setError] = useState(null);
  const navigate = useNavigate();
  const confirmed = Boolean(email) && sameEmail(typed, email);

  const remove = async () => {
    setIsDeleting(true);
    setError(null);
    try {
      await apiClient.delete("/users/me", { data: { confirm_email: typed } });
      clearAuth();
      navigate("/", { replace: true, state: { accountDeleted: true } });
    } catch (err) {
      setError(getApiErrorMessage(err, "Nie udało się usunąć konta."));
      setIsDeleting(false);
    }
  };

  return (
    <section className="mt-10 rounded-lg border border-red-200 p-4 sm:p-5" aria-label="Usuń konto">
      <h3 className="font-semibold text-red-700">Usuń konto</h3>
      <p className="mt-1 text-sm text-gray-700">
        Usuniemy konto i wszystkie dane: profil, wgrane pliki, urządzenia, plany i wyniki symulacji. Tego nie da się
        cofnąć.
      </p>
      <label className="mt-3 block text-sm text-gray-700" htmlFor="delete-account-email">
        Wpisz <span className="font-semibold">{email}</span>, żeby potwierdzić
      </label>
      <div className="mt-1 flex flex-col gap-2 sm:flex-row">
        <input
          id="delete-account-email"
          type="email"
          autoComplete="off"
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm sm:max-w-xs"
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
        />
        <button
          type="button"
          className="inline-flex items-center justify-center gap-1.5 rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50"
          disabled={!confirmed || isDeleting}
          onClick={remove}
        >
          <FiTrash2 aria-hidden="true" /> {isDeleting ? "Usuwanie..." : "Usuń konto"}
        </button>
      </div>
      {error && (
        <p className="mt-2 text-sm text-red-600" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

export default DeleteAccount;
