import { describe, expect, it } from "vitest";
import sample from "../../public/samples/devices-example.json";
import {
  FALLBACK_ROOM,
  HOUSE_ROOMS,
  deviceAppearance,
  evSession,
  gridFlow,
  isPlanControlled,
  isRoomLit,
  layoutRoom,
  placeDevicesInRooms,
} from "./houseView";

// Urządzenia z przykładowego pliku w kształcie stanu domu (GET /home/state).
const sampleDevices = sample.devices.map((device) => ({
  device_id: device.device_id,
  device_name: device.device_name,
  device_type: device.device_type,
  device_category: device.device_category,
  room: device.room ?? null,
  flexibility_mode: device.flexibility.mode,
  programs: device.programs ?? [],
  state: "off",
  power_kw: 0,
  energy_today_kwh: 0,
}));

const device = (overrides = {}) => ({
  device_id: "dev_1",
  device_name: "Urządzenie",
  device_type: "other",
  device_category: "AGD",
  room: "kitchen",
  state: "off",
  power_kw: 0,
  ...overrides,
});

describe("placeDevicesInRooms", () => {
  it("rozmieszcza 24 urządzenia z pliku przykładowego w ich pomieszczeniach", () => {
    const rooms = placeDevicesInRooms(sampleDevices);

    const placed = [...rooms.values()].flat();
    expect(placed).toHaveLength(24);
    for (const item of sampleDevices) {
      expect(rooms.get(item.room).map((d) => d.device_id)).toContain(item.device_id);
    }
    expect(rooms.get("kitchen")).toHaveLength(8);
    expect(rooms.get("roof").map((d) => d.device_id)).toEqual(["dev_pv_01"]);
    expect(rooms.get("garage").map((d) => d.device_id)).toEqual(["dev_ev_01"]);
  });

  it("urządzenie bez pomieszczenia albo z pomieszczeniem spoza słownika trafia do „Inne”", () => {
    const rooms = placeDevicesInRooms([
      device({ device_id: "a", room: null }),
      device({ device_id: "b", room: undefined }),
      device({ device_id: "c", room: "attic" }),
    ]);

    expect(FALLBACK_ROOM).toBe("other");
    expect(rooms.get("other").map((d) => d.device_id)).toEqual(["a", "b", "c"]);
  });

  it("w pomieszczeniu sortuje po nazwie, a puste pomieszczenia mają pustą listę", () => {
    const rooms = placeDevicesInRooms([
      device({ device_id: "z", device_name: "Zmywarka" }),
      device({ device_id: "c", device_name: "Czajnik" }),
    ]);

    expect(rooms.get("kitchen").map((d) => d.device_name)).toEqual(["Czajnik", "Zmywarka"]);
    expect(rooms.get("office")).toEqual([]);
  });
});

describe("layoutRoom", () => {
  const inside = (room, cell) =>
    cell.x >= room.x && cell.y >= room.y && cell.x + cell.w <= room.x + room.w && cell.y + cell.h <= room.y + room.h;

  it("mieści urządzenia z pliku przykładowego w granicach pomieszczeń", () => {
    const rooms = placeDevicesInRooms(sampleDevices);
    for (const room of HOUSE_ROOMS) {
      const cells = layoutRoom(room, rooms.get(room.id).length);
      expect(cells).toHaveLength(rooms.get(room.id).length);
      for (const cell of cells) expect(inside(room, cell)).toBe(true);
    }
  });

  it("przy wielu urządzeniach zmniejsza komórki, żeby się zmieściły", () => {
    const technical = HOUSE_ROOMS.find((room) => room.id === "technical");
    const cells = layoutRoom(technical, 6);

    expect(cells[0].w).toBeLessThan(48);
    for (const cell of cells) expect(inside(technical, cell)).toBe(true);
  });

  it("bez urządzeń nie zwraca komórek", () => {
    expect(layoutRoom(HOUSE_ROOMS[0], 0)).toEqual([]);
  });
});

describe("deviceAppearance", () => {
  it("wyłączone jest szare, bez animacji", () => {
    expect(deviceAppearance(device({ state: "off" }))).toMatchObject({
      tone: "off",
      glyph: "off",
      label: "Wyłączone",
      fill: "#f1f5f9",
      animated: false,
    });
  });

  it("gotowe ma biały środek i obrys w kolorze kategorii", () => {
    expect(deviceAppearance(device({ state: "idle", device_category: "AGD" }))).toMatchObject({
      tone: "ready",
      glyph: "ready",
      label: "Gotowe",
      fill: "#ffffff",
      stroke: "#3b82f6",
    });
  });

  it("pracujące jest w kolorze kategorii i animowane", () => {
    expect(deviceAppearance(device({ state: "running", device_category: "Ogrzewanie", power_kw: 3 }))).toMatchObject({
      tone: "active",
      glyph: "running",
      label: "Pracuje",
      fill: "#f97316",
      animated: true,
    });
  });

  it("awaria i brak połączenia są czerwone, z różnym znakiem i tekstem", () => {
    const error = deviceAppearance(device({ state: "error" }));
    const unreachable = deviceAppearance(device({ state: "unreachable" }));

    expect(error).toMatchObject({ tone: "error", glyph: "error", label: "Awaria", stroke: "#ef4444" });
    expect(unreachable).toMatchObject({ tone: "error", glyph: "unreachable", label: "Brak połączenia", stroke: "#ef4444" });
  });

  it("nieznana kategoria dostaje szary kolor, a przebieg planu podpis „Według planu”", () => {
    const appearance = deviceAppearance(
      device({ state: "running", device_category: null, power_kw: 2, run: { ref: null, ends_at: "2026-10-19T19:00:00+02:00" } }),
    );

    expect(appearance.fill).toBe("#64748b");
    expect(appearance.label).toBe("Według planu");
  });
});

describe("isPlanControlled", () => {
  it("rozróżnia przebieg z planu od przebiegu z historii i braku przebiegu", () => {
    expect(isPlanControlled(device({ run: { ref: null } }))).toBe(true);
    expect(isPlanControlled(device({ run: { ref: "act_1" } }))).toBe(false);
    expect(isPlanControlled(device())).toBe(false);
  });
});

describe("isRoomLit", () => {
  it("rozjaśnia pomieszczenie tylko przy włączonym oświetleniu", () => {
    const light = device({ device_type: "light" });

    expect(isRoomLit([light, device({ state: "running" })])).toBe(false);
    expect(isRoomLit([{ ...light, state: "running" }])).toBe(true);
  });
});

describe("gridFlow", () => {
  it("dodatni bilans to pobór z sieci, ujemny to oddawanie", () => {
    expect(gridFlow({ net_kw: 1.5 })).toEqual({ direction: "import", kw: 1.5, label: "Pobór z sieci" });
    expect(gridFlow({ net_kw: -1.2 })).toEqual({ direction: "export", kw: 1.2, label: "Oddawanie do sieci" });
  });

  it("bilans bliski zera nie ma kierunku, a brak mocy nie ma licznika", () => {
    expect(gridFlow({ net_kw: 0.004 })).toEqual({ direction: "none", kw: 0, label: "Bilans zerowy" });
    expect(gridFlow(null)).toBeNull();
    expect(gridFlow({ net_kw: null })).toBeNull();
  });
});

describe("evSession", () => {
  const charger = (overrides) => device({ device_type: "ev_charger", state: "running", ...overrides });
  const run = { ref: null, started_at: "2026-10-19T18:00:00+02:00", ends_at: "2026-10-19T22:00:00+02:00" };

  it("liczy postęp sesji według zegara symulacji", () => {
    expect(evSession(charger({ run }), "2026-10-19T19:00:00+02:00")).toEqual({ fraction: 0.25, endsAt: run.ends_at });
    expect(evSession(charger({ run }), "2026-10-19T23:00:00+02:00").fraction).toBe(1);
  });

  it("ładowanie włączone ręcznie nie ma procentu, a wyłączona ładowarka nie ma sesji", () => {
    expect(evSession(charger({ run: null }), "2026-10-19T19:00:00+02:00")).toEqual({ fraction: null, endsAt: null });
    expect(evSession(charger({ state: "off", run }), "2026-10-19T19:00:00+02:00")).toBeNull();
    expect(evSession(device({ state: "running", run }), "2026-10-19T19:00:00+02:00")).toBeNull();
  });
});
