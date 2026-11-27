const QUARTER_MS = 15 * 60 * 1000;

export const quarterAt = (quarters, iso) => {
  if (!quarters?.length || !iso) return null;
  const moment = new Date(iso).getTime();
  return quarters.find((quarter) => {
    const start = new Date(quarter.start).getTime();
    return start <= moment && moment < start + QUARTER_MS;
  }) ?? null;
};

export const cloudLabel = (cloud) => {
  if (cloud == null) return null;
  if (cloud < 25) return "bezchmurnie";
  if (cloud < 70) return "częściowe zachmurzenie";
  return "pochmurno";
};

export const weatherKind = (quarter) => {
  if (!quarter || quarter.cloud_cover_pct == null) return null;
  if (quarter.cloud_cover_pct >= 70) return "cloud";
  if (quarter.ghi_w_m2 === 0) return "night";
  return quarter.cloud_cover_pct < 25 ? "sun" : "partly";
};

export const hourlyWeather = (quarters, day) => {
  const hours = new Map();
  for (const quarter of quarters ?? []) {
    if (quarter.start.slice(0, 10) !== day) continue;
    const hour = Number(quarter.start.slice(11, 13));
    if (!hours.has(hour)) hours.set(hour, { hour, clouds: [], temperatures: [] });
    const entry = hours.get(hour);
    if (quarter.cloud_cover_pct != null) entry.clouds.push(quarter.cloud_cover_pct);
    if (quarter.temperature_c != null) entry.temperatures.push(quarter.temperature_c);
  }
  const mean = (values) => (values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null);
  return [...hours.values()]
    .sort((first, second) => first.hour - second.hour)
    .map(({ hour, clouds, temperatures }) => ({ hour, cloud: mean(clouds), temperature: mean(temperatures) }));
};
