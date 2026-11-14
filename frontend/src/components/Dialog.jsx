import { useEffect, useRef } from "react";
import { FiX } from "react-icons/fi";

// Okienko na wierzchu strony: zamyka się przyciskiem, klawiszem Esc albo kliknięciem w tło.
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

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
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
        className="w-full max-w-3xl max-h-[90vh] overflow-y-auto rounded-lg bg-white shadow-xl focus:outline-none"
      >
        <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3 md:px-5">
          <h3 className="font-bold text-gray-900">{title}</h3>
          <button type="button" className="p-1.5 text-gray-500 hover:text-gray-900" aria-label="Zamknij" onClick={onClose}>
            <FiX aria-hidden="true" />
          </button>
        </div>
        <div className="p-4 md:p-5">{children}</div>
      </div>
    </div>
  );
}

export default Dialog;
