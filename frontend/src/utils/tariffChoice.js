// Optymalizacja historyczna: wybór taryfy na ekranie i wyjaśnienie wyniku taryfy G11.
const FLAT_GROUP = "G11";

/** Czy sprzedawca dopuszcza umowę z ceną dynamiczną przy tej grupie (z /tariffs/options). */
export const dynamicAllowed = (options, group) => Boolean(options?.dynamic_offer?.distribution_groups?.includes(group));

/** Taryfa z profilu jako wybór na ekranie; null, gdy profil nie ma grupy. */
export const profileChoice = (profile) => {
  const tariff = profile?.consumption_and_tariff;
  return tariff?.tariff_type ? { group: tariff.tariff_type, dynamic: Boolean(tariff.dynamic_price) } : null;
};

export const sameChoice = (first, second) =>
  Boolean(first && second) && first.group === second.group && first.dynamic === second.dynamic;

export const choiceLabel = (choice) => (choice.dynamic ? `${choice.group} z ceną dynamiczną` : choice.group);

/**
 * Wyjaśnienie wyniku w G11 bez ceny dynamicznej: prąd kosztuje tyle samo o każdej porze, więc przesuwanie
 * nic nie daje. Z fotowoltaiką zysk jest tylko z przeniesienia urządzeń na godziny produkcji. Null dla innych taryf.
 */
export const flatTariffNote = (schedule) => {
  if (schedule?.tariff_group !== FLAT_GROUP || schedule.tariff_dynamic) return null;
  if (schedule.prosumer) {
    return (
      "W taryfie G11 prąd z sieci kosztuje tyle samo o każdej porze. Oszczędność pochodzi tylko z przeniesienia " +
      "urządzeń na godziny, w których panele produkują prąd. Więcej da taryfa z ceną dynamiczną, " +
      "w której prąd jest tańszy w nocy i w środku dnia."
    );
  }
  return (
    "W taryfie G11 prąd kosztuje tyle samo o każdej porze, więc przesuwanie urządzeń nic nie daje i oszczędność " +
    "wynosi 0 zł. Zysk da taryfa z ceną dynamiczną, w której prąd jest tańszy w nocy i w środku dnia."
  );
};
