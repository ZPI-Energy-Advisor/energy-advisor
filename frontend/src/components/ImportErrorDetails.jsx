import { useState } from "react";
import { formatCount } from "../utils/energyFiles";

const VISIBLE_ERRORS = 10;
const ERRORS = ["błąd", "błędy", "błędów"];

// Urządzenie po nazwie, a ID z pliku w nawiasie, żeby dało się je znaleźć w pliku.
const errorLabel = (item) => (item.device_name ? `${item.device_name} (${item.location})` : item.location);

// Błąd importu z backendu: zwykły tekst albo lista błędów pliku urządzeń ({ message, errors, errors_count }).
function ImportErrorDetails({ error }) {
  const [showAll, setShowAll] = useState(false);

  if (!error) return null;
  if (typeof error === "string") return error;

  const errors = error.errors ?? [];
  const visible = showAll ? errors : errors.slice(0, VISIBLE_ERRORS);
  const notSent = (error.errors_count ?? errors.length) - errors.length;

  return (
    <div className="text-left">
      <p>{error.message}</p>
      <ul className="mt-2 space-y-1 list-disc pl-5 font-normal">
        {visible.map((item, index) => (
          <li key={`${item.location}-${index}`}>
            {item.location && <span className="font-medium">{errorLabel(item)}:</span>} {item.message}
          </li>
        ))}
      </ul>
      {visible.length < errors.length && (
        <button type="button" onClick={() => setShowAll(true)} className="mt-2 underline hover:no-underline">
          Pokaż wszystkie ({errors.length})
        </button>
      )}
      {notSent > 0 && (visible.length === errors.length) && (
        <p className="mt-2 font-normal">
          …i {formatCount(notSent, ERRORS)} więcej. Popraw powyższe i wgraj plik ponownie, żeby zobaczyć resztę.
        </p>
      )}
    </div>
  );
}

export default ImportErrorDetails;
