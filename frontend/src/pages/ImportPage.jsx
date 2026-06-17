import React, { useState, useCallback } from "react";
import { useDropzone } from "react-dropzone";
import { useNavigate } from "react-router-dom";
import axios from "axios";

function ImportPage() {
  const [file, setFile] = useState(null);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState(null);
  const [isUploading, setIsUploading] = useState(false);
  const [successMsg, setSuccessMsg] = useState(null);

  const navigate = useNavigate();

  const onDrop = useCallback((acceptedFiles) => {
    if (acceptedFiles.length > 0) {
      setFile(acceptedFiles[0]);
      setError(null);
      setSuccessMsg(null);
      setProgress(0);
    }
  }, []);

  const onDropRejected = useCallback(() => {
    setError(
      "Nieprawidłowy format pliku. Proszę wgrać plik z rozszerzeniem .csv.",
    );
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    onDropRejected,
    accept: {
      "text/csv": [".csv"],
    },
    maxFiles: 1,
  });

  const handleRemoveFile = () => {
    setFile(null);
    setProgress(0);
    setError(null);
    setSuccessMsg(null);
  };

  const handleUpload = async () => {
    if (!file) return;

    setIsUploading(true);
    setError(null);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await axios.post(
        "http://localhost:8000/upload",
        formData,
        {
          headers: {
            "Content-Type": "multipart/form-data",
          },
          onUploadProgress: (progressEvent) => {
            const percentCompleted = Math.round(
              (progressEvent.loaded * 100) / progressEvent.total,
            );
            setProgress(percentCompleted);
          },
        },
      );

      localStorage.setItem("last_simulation_id", response.data.simulation_id);

      setSuccessMsg(
        response.data.message || "Plik został pomyślnie przetworzony!",
      );
      setIsUploading(false);
    } catch (err) {
      setIsUploading(false);
      setProgress(0);

      if (err.response && err.response.data && err.response.data.detail) {
        setError(err.response.data.detail);
      } else {
        setError("Wystąpił błąd podczas łączenia z serwerem.");
      }
    }
  };

  return (
    <div className="max-w-4xl mx-auto">
      <h2 className="text-xl font-bold text-gray-900 border-b border-gray-200 pb-4 mb-8">
        Prześlij plik CSV
      </h2>

      {successMsg ? (
        <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-10 text-center shadow-sm">
          <div className="w-16 h-16 bg-emerald-100 rounded-full flex items-center justify-center mx-auto mb-4 text-emerald-600">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-8 w-8"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M5 13l4 4L19 7"
              />
            </svg>
          </div>
          <h3 className="text-2xl font-bold text-emerald-800 mb-2">Sukces!</h3>
          <p className="text-emerald-600 mb-6">{successMsg}</p>
          <button
            onClick={() => navigate("/dashboard")}
            className="bg-emerald-600 text-white px-8 py-3 rounded font-medium hover:bg-emerald-700 transition-colors"
          >
            Zobacz wyniki na Dashboardzie
          </button>
        </div>
      ) : (
        <>
          {!file ? (
            <div className="space-y-4">
              <div
                {...getRootProps()}
                className={`border-2 border-dashed rounded-lg p-16 text-center cursor-pointer transition-colors ${
                  isDragActive
                    ? "border-emerald-500 bg-emerald-50"
                    : "border-gray-300 bg-gray-50 hover:bg-gray-100"
                }`}
              >
                <input {...getInputProps()} />
                <h3 className="text-xl font-bold text-gray-900 mb-2">
                  {isDragActive
                    ? "Upuść plik tutaj..."
                    : "Przeciągnij i upuść plik tutaj"}
                </h3>
                <p className="text-sm text-gray-500 mb-6">Format: CSV</p>
                <button
                  type="button"
                  className="bg-emerald-600 text-white px-6 py-2 rounded font-medium hover:bg-emerald-700 transition-colors"
                >
                  Wybierz plik
                </button>
              </div>

              {error && (
                <div className="p-4 bg-red-50 text-red-600 rounded-lg border border-red-200 text-center font-medium">
                  {error}
                </div>
              )}
            </div>
          ) : (
            <div className="p-6 bg-white border border-gray-200 rounded-lg shadow-sm">
              <div className="flex justify-between items-start mb-6">
                <div>
                  <p className="font-medium text-gray-900">{file.name}</p>
                  <p className="text-sm text-gray-500">
                    Rozmiar: {(file.size / 1024 / 1024).toFixed(2)} MB
                  </p>
                </div>
                {!isUploading && (
                  <button
                    onClick={handleRemoveFile}
                    className="text-gray-400 hover:text-red-500 transition-colors p-2 -mr-2"
                    title="Usuń i wybierz inny plik"
                  >
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      className="h-6 w-6"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M6 18L18 6M6 6l12 12"
                      />
                    </svg>
                  </button>
                )}
              </div>

              {isUploading && (
                <div className="mb-6">
                  <div className="flex justify-between text-sm mb-2">
                    <span className="text-gray-500">
                      Przetwarzanie danych...
                    </span>
                    <span className="text-emerald-600 font-medium">
                      {progress}%
                    </span>
                  </div>
                  <div className="w-full bg-gray-200 rounded-full h-2">
                    <div
                      className="bg-emerald-500 h-2 rounded-full transition-all duration-300"
                      style={{ width: `${progress}%` }}
                    ></div>
                  </div>
                </div>
              )}

              {error && (
                <div className="mb-6 p-4 bg-red-50 text-red-600 rounded border border-red-200 text-sm font-medium">
                  {error}
                </div>
              )}

              <div className="flex justify-end border-t border-gray-100 pt-4 mt-2">
                <button
                  onClick={handleUpload}
                  disabled={isUploading}
                  className={`px-6 py-2 rounded font-medium text-white transition-colors flex items-center ${
                    isUploading
                      ? "bg-gray-400 cursor-not-allowed"
                      : "bg-emerald-600 hover:bg-emerald-700"
                  }`}
                >
                  {isUploading ? (
                    <>
                      <svg
                        className="animate-spin -ml-1 mr-3 h-5 w-5 text-white"
                        xmlns="http://www.w3.org/2000/svg"
                        fill="none"
                        viewBox="0 0 24 24"
                      >
                        <circle
                          className="opacity-25"
                          cx="12"
                          cy="12"
                          r="10"
                          stroke="currentColor"
                          strokeWidth="4"
                        ></circle>
                        <path
                          className="opacity-75"
                          fill="currentColor"
                          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                        ></path>
                      </svg>
                      Wysyłanie...
                    </>
                  ) : (
                    "Wyślij na serwer"
                  )}
                </button>
              </div>
            </div>
          )}

          <div className="mt-8 bg-white border border-gray-200 p-6 rounded-lg shadow-sm">
            <h3 className="font-bold text-gray-900 mb-4">Instrukcja</h3>
            <ol className="list-decimal list-inside text-gray-600 space-y-2 text-sm">
              <li>Zaloguj się do portalu operatora (np. Tauron eLicznik).</li>
              <li>Eksportuj dane godzinowe do pliku CSV.</li>
              <li>Wgraj plik powyżej, aby rozpocząć symulację.</li>
            </ol>
          </div>
        </>
      )}
    </div>
  );
}

export default ImportPage;
