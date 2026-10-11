import { Link } from "react-router-dom";
import { useEnergyFiles } from "../hooks/useEnergyFiles";
import { FILES_TABLE_ANCHOR } from "../utils/energyFiles";

function NoFileData({ emptyTitle, emptyDescription }) {
  const { files, filesError, isLoadingFiles, reload } = useEnergyFiles();

  let title = emptyTitle;
  let description = emptyDescription;
  let action = (
    <Link
      to="/upload"
      className="inline-block bg-emerald-600 text-white font-medium px-6 py-3 rounded hover:bg-emerald-700 transition-colors w-full sm:w-auto"
    >
      Przejdź do Importu Danych
    </Link>
  );

  if (filesError && files.length === 0) {
    title = "Nie udało się pobrać plików";
    description = filesError;
    action = (
      <button
        type="button"
        onClick={reload}
        disabled={isLoadingFiles}
        className="inline-block bg-emerald-600 text-white font-medium px-6 py-3 rounded hover:bg-emerald-700 transition-colors w-full sm:w-auto disabled:opacity-60 disabled:cursor-wait"
      >
        {isLoadingFiles ? "Ładowanie..." : "Spróbuj ponownie"}
      </button>
    );
  } else if (files.length > 0) {
    const hasCompletedFile = files.some((file) => file.status === "completed");
    title = "Brak danych do wyświetlenia";
    description = hasCompletedFile
      ? "Wybierz plik w tabeli „Twoje pliki” na stronie importu, aby zobaczyć jego dane."
      : "Żaden z wgranych plików nie został poprawnie przetworzony. Wgraj nowy plik CSV.";
    if (hasCompletedFile) {
      action = (
        <Link
          to={`/upload#${FILES_TABLE_ANCHOR}`}
          className="inline-block bg-emerald-600 text-white font-medium px-6 py-3 rounded hover:bg-emerald-700 transition-colors w-full sm:w-auto"
        >
          Wybierz plik
        </Link>
      );
    }
  }

  return (
    <div className="bg-white p-8 md:p-10 rounded-lg shadow-sm border border-emerald-100 text-center">
      <h3 className="text-xl font-bold text-gray-800 mb-2">{title}</h3>
      <p className="text-gray-500 mb-6 text-sm md:text-base">{description}</p>
      {action}
    </div>
  );
}

export default NoFileData;
