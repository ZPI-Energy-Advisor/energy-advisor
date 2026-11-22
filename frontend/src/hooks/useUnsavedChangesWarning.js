import { useEffect } from "react";

export const UNSAVED_CHANGES_MESSAGE = "Masz niezapisane zmiany w profilu. Wyjść bez zapisywania?";

function leavesPage(event) {
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
    return false;
  }
  const target = event.target instanceof Element ? event.target.closest("a[href], [data-leaves-page]") : null;
  if (!target) return false;
  if (target.tagName !== "A") return true;
  if (target.target === "_blank" || target.hasAttribute("download")) return false;
  const url = new URL(target.href, window.location.href);
  return url.origin === window.location.origin && url.pathname !== window.location.pathname;
}

export function useUnsavedChangesWarning(dirty, message = UNSAVED_CHANGES_MESSAGE) {
  useEffect(() => {
    if (!dirty) return undefined;
    const onBeforeUnload = (event) => {
      event.preventDefault();
      event.returnValue = "";
    };
    const onClick = (event) => {
      if (leavesPage(event) && !window.confirm(message)) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    document.addEventListener("click", onClick, true);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      document.removeEventListener("click", onClick, true);
    };
  }, [dirty, message]);
}
