import { useEffect, useState } from "react";
import apiClient from "../api/client";

const emptyProfile = {
  type_of_property: "apartment",
  heating_area_m2: "",
  place_latitude: "",
  place_longitude: "",
  number_of_residents: "",
  current_tariff_id: "",
};

const propertyTypes = [
  ["apartment", "Mieszkanie"],
  ["single_family_house", "Dom jednorodzinny"],
  ["terrace_house", "Dom szeregowy"],
  ["recreational_cottage", "Domek letniskowy"],
  ["other", "Inny"],
];

function ProfilePage() {
  const [profile, setProfile] = useState(emptyProfile);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);

  useEffect(() => {
    const loadProfile = async () => {
      try {
        const response = await apiClient.get("/upload/profile");
        setProfile({
          ...emptyProfile,
          ...Object.fromEntries(
            Object.entries(response.data).map(([key, value]) => [
              key,
              value ?? "",
            ]),
          ),
        });
      } catch (err) {
        if (err.response?.status !== 404) {
          setError(
            err.response?.data?.detail ||
              "Nie udało się pobrać danych profilu.",
          );
        }
      } finally {
        setIsLoading(false);
      }
    };

    loadProfile();
  }, []);

  const handleChange = (event) => {
    const { name, value } = event.target;
    setProfile((currentProfile) => ({ ...currentProfile, [name]: value }));
    setError(null);
    setSuccessMessage(null);
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setIsSaving(true);
    setError(null);
    setSuccessMessage(null);

    const profileData = {
      type_of_property: profile.type_of_property,
      heating_area_m2: Number(profile.heating_area_m2),
      number_of_residents: Number(profile.number_of_residents),
      place_latitude:
        profile.place_latitude === "" ? null : Number(profile.place_latitude),
      place_longitude:
        profile.place_longitude === "" ? null : Number(profile.place_longitude),
      current_tariff_id:
        profile.current_tariff_id === ""
          ? null
          : Number(profile.current_tariff_id),
    };

    try {
      const response = await apiClient.post("/upload/profile", profileData);
      setProfile((currentProfile) => ({ ...currentProfile, ...response.data }));
      setSuccessMessage("Profil został zapisany.");
    } catch (err) {
      setError(
        err.response?.data?.detail || "Nie udało się zapisać profilu.",
      );
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoading) {
    return <div className="max-w-4xl mx-auto text-gray-500">Ładowanie profilu...</div>;
  }

  return (
    <div className="max-w-4xl mx-auto pb-12">
      <h2 className="text-xl font-bold text-gray-900 border-b border-gray-200 pb-4 mb-6 md:mb-8">
        Profil
      </h2>

      <form
        onSubmit={handleSubmit}
        className="bg-white border border-gray-200 rounded-lg shadow-sm p-6 md:p-8"
      >
        <p className="text-gray-600 mb-6">
          Uzupełnij dane nieruchomości, aby spersonalizować analizy zużycia.
        </p>

        {error && (
          <div className="mb-6 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            {error}
          </div>
        )}
        {successMessage && (
          <div className="mb-6 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-700">
            {successMessage}
          </div>
        )}

        <div className="grid gap-5 md:grid-cols-2">
          <label className="text-sm font-medium text-gray-700">
            Typ nieruchomości
            <select
              name="type_of_property"
              value={profile.type_of_property}
              onChange={handleChange}
              required
              className="mt-2 w-full rounded-md border border-gray-300 bg-white px-3 py-2.5 font-normal text-gray-900 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            >
              {propertyTypes.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>

          <label className="text-sm font-medium text-gray-700">
            Powierzchnia ogrzewana (m²)
            <input
              type="number"
              name="heating_area_m2"
              min="0.01"
              step="0.01"
              value={profile.heating_area_m2}
              onChange={handleChange}
              required
              className="mt-2 w-full rounded-md border border-gray-300 px-3 py-2.5 font-normal text-gray-900 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </label>

          <label className="text-sm font-medium text-gray-700">
            Liczba mieszkańców
            <input
              type="number"
              name="number_of_residents"
              min="1"
              step="1"
              value={profile.number_of_residents}
              onChange={handleChange}
              required
              className="mt-2 w-full rounded-md border border-gray-300 px-3 py-2.5 font-normal text-gray-900 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </label>

          <label className="text-sm font-medium text-gray-700">
            ID aktualnej taryfy
            <input
              type="number"
              name="current_tariff_id"
              min="1"
              step="1"
              value={profile.current_tariff_id}
              onChange={handleChange}
              className="mt-2 w-full rounded-md border border-gray-300 px-3 py-2.5 font-normal text-gray-900 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </label>

          <label className="text-sm font-medium text-gray-700">
            Szerokość geograficzna
            <input
              type="number"
              name="place_latitude"
              min="-90"
              max="90"
              step="any"
              value={profile.place_latitude}
              onChange={handleChange}
              className="mt-2 w-full rounded-md border border-gray-300 px-3 py-2.5 font-normal text-gray-900 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </label>

          <label className="text-sm font-medium text-gray-700">
            Długość geograficzna
            <input
              type="number"
              name="place_longitude"
              min="-180"
              max="180"
              step="any"
              value={profile.place_longitude}
              onChange={handleChange}
              className="mt-2 w-full rounded-md border border-gray-300 px-3 py-2.5 font-normal text-gray-900 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </label>
        </div>

        <div className="mt-8 flex justify-end">
          <button
            type="submit"
            disabled={isSaving}
            className="rounded-md bg-emerald-500 px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-emerald-600 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isSaving ? "Zapisywanie..." : "Zapisz profil"}
          </button>
        </div>
      </form>
    </div>
  );
}

export default ProfilePage;
