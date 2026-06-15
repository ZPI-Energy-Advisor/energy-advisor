import React, { useState, useCallback } from 'react';
import { useDropzone } from 'react-dropzone';

function ImportPage() {
  const [file, setFile] = useState(null);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState(null); 

  const onDrop = useCallback(acceptedFiles => {
    if (acceptedFiles.length > 0) {
      setFile(acceptedFiles[0]);
      setError(null); 
      
      setProgress(30);
      setTimeout(() => setProgress(70), 300);
      setTimeout(() => setProgress(100), 600);
    }
  }, []);

  const onDropRejected = useCallback(() => {
    setError("Nieprawidłowy format pliku. Proszę wgrać plik z rozszerzeniem .csv lub .xlsx.");
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    onDropRejected, 
    accept: {
      'text/csv': ['.csv'],
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx']
    },
    maxFiles: 1
  });

  const handleRemoveFile = () => {
    setFile(null);
    setProgress(0);
    setError(null);
  };

  return (
    <div className="max-w-4xl mx-auto">
      <h2 className="text-xl font-bold text-gray-900 border-b border-gray-200 pb-4 mb-8">
        Prześlij plik CSV
      </h2>

      {!file ? (
        <div className="space-y-4">
          <div 
            {...getRootProps()} 
            className={`border-2 border-dashed rounded-lg p-16 text-center cursor-pointer transition-colors ${
              isDragActive ? 'border-emerald-500 bg-emerald-50' : 'border-gray-300 bg-gray-50 hover:bg-gray-100'
            }`}
          >
            <input {...getInputProps()} />
            <h3 className="text-xl font-bold text-gray-900 mb-2">
              {isDragActive ? "Upuść plik tutaj..." : "Przeciągnij i upuść plik tutaj"}
            </h3>
            <p className="text-sm text-gray-500 mb-6">Format: CSV, XLSX</p>
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
          <div className="flex justify-between items-start mb-4">
            <div>
              <p className="font-medium text-gray-900">{file.name}</p>
              <p className="text-sm text-gray-500">
                Rozmiar: {(file.size / 1024 / 1024).toFixed(2)} MB
              </p>
            </div>
            <button 
              onClick={handleRemoveFile}
              className="text-gray-400 hover:text-red-500 transition-colors p-2 -mr-2"
              title="Usuń i wybierz inny plik"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <div className="flex justify-between text-sm mb-2">
            <span className="text-gray-500">Przesłano...</span>
            <span className="text-emerald-600 font-medium">{progress}%</span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-2">
            <div 
              className="bg-emerald-500 h-2 rounded-full transition-all duration-300" 
              style={{ width: `${progress}%` }}
            ></div>
          </div>
        </div>
      )}

      <div className="mt-8 bg-white border border-gray-200 p-6 rounded-lg shadow-sm">
        <h3 className="font-bold text-gray-900 mb-4">Instrukcja</h3>
        <ol className="list-decimal list-inside text-gray-600 space-y-2 text-sm">
          <li>Zaloguj się do portalu operatora (np. Tauron eLicznik).</li>
          <li>Eksportuj dane godzinowe do pliku CSV.</li>
          <li>Wgraj plik powyżej, aby rozpocząć kalkulacje.</li>
        </ol>
      </div>
    </div>
  );
}

export default ImportPage;