import { Link } from "react-router-dom";
import { useCurrentUser } from "../hooks/useCurrentUser";

const NOTICE = "mb-6 rounded-lg border px-4 py-3 text-sm";
const INFO = `${NOTICE} border-blue-200 bg-blue-50 text-blue-800`;
const ERROR = `${NOTICE} border-red-200 bg-red-50 text-red-800`;
const LINK = "font-semibold underline";

// Baner o taryfie z profilu. Błąd pobrania /users/me nie może wyglądać jak brak profilu,
// bo użytkownik z profilem dostałby wtedy prośbę o jego uzupełnienie.
// `pricingNote` to uwaga backendu o taryfie kosztów, np. gdy operator nie ma stawek taryfy z profilu w okresie pliku.
function ProfileTariffNotice({ missingProfile, pricingNote = null }) {
  const { profileTariff, isReady, loadError, refresh } = useCurrentUser();

  if (!isReady) return null;
  if (loadError) {
    return (
      <div className={ERROR} role="alert">
        {loadError}{" "}
        <button type="button" onClick={refresh} className={LINK}>
          Spróbuj ponownie
        </button>
      </div>
    );
  }
  const note = pricingNote ? <div className={INFO}>{pricingNote}</div> : null;
  if (!profileTariff?.exists) {
    return (
      <>
        <div className={INFO}>
          <Link to="/profile" className={LINK}>
            Uzupełnij profil
          </Link>
          {missingProfile}
        </div>
        {note}
      </>
    );
  }
  if (profileTariff.needs_update) {
    return (
      <>
        <div className={INFO}>
          Zmienił się format profilu i część danych trzeba podać ponownie.{" "}
          <Link to="/profile" className={LINK}>
            Uzupełnij profil
          </Link>
        </div>
        {note}
      </>
    );
  }
  return note;
}

export default ProfileTariffNotice;
