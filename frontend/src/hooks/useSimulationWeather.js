import { useEffect, useState } from "react";
import apiClient from "../api/client";
import { simDay } from "../utils/home";
import { quarterAt } from "../utils/weather";

export function useSimulationWeather(simTime) {
  const day = simTime ? simDay(simTime) : null;
  const [loaded, setLoaded] = useState(null);

  useEffect(() => {
    if (!day) return undefined;
    let cancelled = false;
    apiClient
      .get("/weather/forecast", { params: { date: day } })
      .then(({ data }) => {
        if (!cancelled) setLoaded({ day, data });
      })
      .catch(() => {
        if (!cancelled) setLoaded({ day, data: null });
      });
    return () => {
      cancelled = true;
    };
  }, [day]);

  if (!loaded || loaded.day !== day || !loaded.data) return null;
  const quarter = quarterAt(loaded.data.intervals, simTime);
  if (!quarter) return null;
  return { ...quarter, approximate: loaded.data.location_approximate };
}
