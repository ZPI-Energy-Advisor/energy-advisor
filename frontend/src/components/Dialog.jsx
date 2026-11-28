import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { FiX } from "react-icons/fi";

// Okienko na wierzchu strony: zamyka się przyciskiem, klawiszem Esc albo kliknięciem w tło. Renderowane wprost
// w <body> (portal), żeby odstępy kontenera strony (np. space-y-4) nie przesuwały przyciemnionego tła.
function Dialog({ title, onClose, children }) {
  const panelRef = useRef(null);

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    panelRef.current?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-stretch justify-center bg-black/40 sm:items-center sm:p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        // Na telefonie okno na cały ekran (z marginesem na wycięcie ekranu), od `sm` okienko z marginesami.
        className="w-full max-w-3xl overflow-y-auto bg-white pt-[env(safe-area-inset-top)] shadow-xl focus:outline-none sm:max-h-[90vh] sm:rounded-lg sm:pt-0"
      >
        <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3 md:px-5">
          <h3 className="font-bold text-gray-900">{title}</h3>
          <button type="button" className="-m-1 p-2.5 text-gray-500 hover:text-gray-900" aria-label="Zamknij" onClick={onClose}>
            <FiX aria-hidden="true" />
          </button>
        </div>
        <div className="p-4 md:p-5">{children}</div>
      </div>
    </div>,
    document.body,
  );
}

export default Dialog;
