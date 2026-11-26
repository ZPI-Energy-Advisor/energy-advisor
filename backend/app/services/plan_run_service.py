"""Wykonanie zatwierdzonego planu dnia w symulacji Smart Home (ZP-113).

Uruchomienie zaczyna w hubie dobę planu od północy i wysyła jednym żądaniem całą dobę:

- pozycje planu: program pralki czy zmywarki jako `start_program`, a auto, bojler i pompa ciepła jako
  `run_profile` z profilem z planu (zera w przerwach ładowania), każda ze startem z planu w `start_at`;
- urządzenia, które pracują same (bez nocy po dobie planu): produkcja PV, od której zależy, czy plan się
  opłaca (pralka w południe z paneli), oraz pompa ciepła i bojler odznaczone w planie, bo plan zakłada, że
  pracują same na termostacie i liczy na nie miejsce w limicie przyłącza. Bierzemy je z planu (`background`,
  ZP-120): PV z prognozy pogody, pompa dopasowana do temperatury, a bojler i to, czego nie dało się policzyć
  z pogody, z dnia referencyjnego. Plan sprzed ZP-120 nie ma `background`: wtedy wszystko z dnia referencyjnego.

Urządzenia stałe (światło, TV, czajnik…) startują wyłączone i włącza je użytkownik z ekranu „Mój dom”:
widać wtedy, jak plan i ręczne włączenia razem obciążają przyłącze.

Zegar rusza ze `stop_at` na koniec przebiegu, więc hub sam staje. Koniec przebiegu to północ po dobie planu
albo, gdy pozycja planu pracuje dłużej (np. auto ładuje się w nocy), koniec ostatniej pozycji, najpóźniej
06:00 jak zakres planu: po północy bez pracy z planu nie ma czego symulować. Hub jest jedynym
źródłem czasu i stanu, więc status przebiegu sprawdzamy przy odczycie: hub z innym `simulation_id` zaczął
nową symulację (`superseded`), a zegar na końcu planu kończy przebieg (`completed`).

Rachunek przed i po (ZP-114, `plan_run_report`): przy starcie zapisujemy ceny kwadransów planu i koszt każdej
akcji bez planu, bo ponowne ułożenie planu nadpisuje jego wiersz. Raport zapisujemy przy zamknięciu przebiegu
i jeszcze przez `REPORT_SETTLE` przeliczamy go przy odczycie: hub dosyła zdarzenia z kolejki z opóźnieniem.
"""

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status

from app.clients.hub_client import HubClient, HubError
from app.models.DayPlan import DayPlan
from app.models.PlanRun import PlanRun
from app.models.User import User
from app.parsers.devices import LOCAL_TIMEZONE
from app.repositories.day_plan_repository import DayPlanRepository
from app.repositories.home_event_repository import HomeEventRepository
from app.repositories.home_repository import HomeRepository
from app.repositories.plan_run_repository import PlanRunRepository
from app.schemas.day_plan import PlanItemOut
from app.schemas.plan_run import (
    PlanRunActionOut,
    PlanRunCostOut,
    PlanRunDeviceOut,
    PlanRunErrorOut,
    PlanRunHistoryDeviceOut,
    PlanRunOut,
    PlanRunPriceOut,
    PlanRunReplay,
    PlanRunSummaryOut,
    PlanRunWaterHeaterOut,
)
from app.schemas.smart_home import CommandType, HubClock, HubCommand, HubCommandResult, HubCommandStatus
from app.services.home_control_service import (
    INVALID_RESPONSE_MESSAGE,
    day_midnight,
    hub_http_error,
    require_hub,
    send_batch,
    update_hub_clock,
)
from app.services.day_background import HISTORY, PV_TYPE, THERMOSTAT_TYPES, BackgroundDevice, DayBackground, history_runs
from app.services.home_replay import ReplayRun, replay_commands, replay_summary
from app.services.home_state_service import DayEnergy, day_energy
from app.services.plan_run_report import RunEnergy, cost_report, profile_cost
from app.services.pv_balance import HouseBalance


logger = logging.getLogger(__name__)

PLAN_NOT_FOUND_MESSAGE = "Nie ma takiego planu."
RUN_NOT_FOUND_MESSAGE = "Nie ma takiego przebiegu planu."
PLAN_NOT_APPROVED_MESSAGE = "Zatwierdź plan, zanim uruchomisz go w symulacji."
PLAN_OUTDATED_MESSAGE = (
    "Ten plan ułożono, zanim można było go uruchomić w symulacji. Ułóż go ponownie i zatwierdź."
)
PLAN_FAILED_MESSAGE = "Doba planu została ustawiona, ale hub nie przyjął planu. Uruchom plan ponownie."
MAX_REPORTED_ERRORS = 50
# Tyle po zamknięciu przebiegu raport jeszcze się przelicza: hub wysyła zdarzenia partiami z kolejki i ponawia je,
# gdy backend nie odpowiada, więc ostatnie kwadranse mogą dojść po końcu planu.
REPORT_SETTLE = timedelta(minutes=5)
HISTORY_LIMIT = 30


def _kwh(value: float) -> float:
    return round(value, 3) + 0.0  # + 0.0 zamienia -0.0 na 0.0


class PlanRunService:
    def __init__(
        self,
        home_repository: HomeRepository,
        plan_repository: DayPlanRepository,
        run_repository: PlanRunRepository,
        event_repository: HomeEventRepository,
        hub_client: HubClient | None,
    ):
        self.home_repository = home_repository
        self.plan_repository = plan_repository
        self.run_repository = run_repository
        self.event_repository = event_repository
        self.hub_client = hub_client

    # --- uruchomienie ---

    def start(self, owner: User, plan_id: UUID) -> PlanRunOut:
        """Uruchamia plan od północy jego doby. Ponowne uruchomienie zaczyna dobę od nowa.

        Kolejność z kontraktu huba: pauza (czasu nie da się zmienić przy chodzącym zegarze), nowa doba
        z `restart` (pusta kolejka komend), jedna partia komend, start zegara. Przebieg zapisujemy dopiero
        po starcie zegara: gdy coś po drodze zawiedzie, w bazie nie zostaje przebieg, który nie ruszył,
        a ponowienie znów resetuje dobę, więc nic nie wykona się dwa razy.
        """
        hub_client = require_hub(self.hub_client, self.home_repository, owner)
        plan = self.plan_repository.get(owner.id, plan_id)
        if plan is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=PLAN_NOT_FOUND_MESSAGE)
        if plan.status != DayPlan.APPROVED:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=PLAN_NOT_APPROVED_MESSAGE)
        items = [PlanItemOut.model_validate(item) for item in plan.result["items"]]
        planned = self._plan_commands(items)
        tariff = {
            "max_grid_kw": plan.result.get("max_grid_kw"),
            "prices": plan.result["prices"],
            # Od tej chwili ceny nocy po dniu planu są przybliżone (te same godziny dnia planu), gdy nie było cen.
            "approximate_from": plan.result.get("approximate_from"),
            # Rachunek domu z PV z planu (ZP-121): reszta domu, prognoza PV i wartość oddania. Raport liczy koszt
            # urządzeń tym samym rachunkiem; None w planach bez PV.
            "balance": plan.result.get("balance"),
            # Temperatura wody według planu do wskaźnika na ekranie „Mój dom” (ZP-110). Migawka, bo ponowne
            # ułożenie planu nadpisuje jego wiersz.
            "water_heaters": [
                {
                    "device_id": heater["device_id"],
                    "device_name": heater["device_name"],
                    "temperatures": [
                        {"start": entry["start"], "temp_c": entry["after"]} for entry in heater["temperatures"]
                    ],
                }
                for heater in plan.result.get("water_heaters", [])
            ],
        }
        prices = _prices(tariff)
        horizon_start = datetime.fromisoformat(plan.result["horizon_start"])
        horizon_end = self._run_end(plan, [item for item, _ in planned])
        background = self._background(owner, plan, {item.device_id for item in items})
        runs = background.runs

        # Blokada wiersza domu: dwa równoczesne „Uruchom” (albo uruchomienie i wysyłka rejestru) nie przeplatają
        # zmian w hubie. Trzymamy ją do zapisu przebiegu.
        self.home_repository.lock()
        paused = update_hub_clock(hub_client, running=False)
        clock = update_hub_clock(hub_client, sim_time=day_midnight(plan.plan_date), restart=True)
        if not clock.simulation_id:
            # Bez simulation_id nie odróżnimy zdarzeń tego przebiegu od innych (hub sprzed ZP-95).
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=INVALID_RESPONSE_MESSAGE)
        results = send_batch(hub_client, [command for _, command in planned] + replay_commands(runs), PLAN_FAILED_MESSAGE)
        plan_results, replay_results = results[:len(planned)], results[len(planned):]

        now = datetime.now(timezone.utc)
        for previous in self.run_repository.running(owner.id):
            # Zegar sprzed nowej doby: przebieg, który hub już doprowadził do końca planu, jest wykonany.
            if not self._refresh(owner, previous, paused):
                self._close(owner, previous, PlanRun.SUPERSEDED, now)
        replayed = self._history_energy(runs, replay_results, background.devices)
        run = self.run_repository.add(PlanRun(
            user_id=owner.id,
            day_plan_id=plan.id,
            plan_date=plan.plan_date,
            simulation_id=clock.simulation_id,
            status=PlanRun.RUNNING,
            horizon_start=horizon_start,
            horizon_end=horizon_end,
            # Najnowszy z dni referencyjnych urządzeń (zwykle wszystkie mają ten sam).
            history_day=max(
                (date.fromisoformat(entry["history_day"]) for entry in replayed if entry["history_day"]), default=None,
            ),
            items=[
                self._action(item, result, prices, with_pv=tariff["balance"] is not None).model_dump(mode="json")
                for (item, _), result in zip(planned, plan_results, strict=True)
            ],
            replay=replay_summary(runs, replay_results).model_dump(mode="json"),
            replayed_devices=replayed,
            tariff=tariff,
            started_at=now,
        ))
        # Zegar sam stanie o końcu planu: później nie ma już czego symulować.
        clock = update_hub_clock(hub_client, running=True, stop_at=horizon_end)
        self.run_repository.commit()
        return self._out(owner, run, clock)

    @staticmethod
    def _run_end(plan: DayPlan, items: list[PlanItemOut]) -> datetime:
        """Koniec przebiegu: północ po dobie planu albo koniec ostatniej wysłanej pozycji planu, gdy pracuje
        dłużej, najpóźniej koniec zakresu planu (06:00). Historia (PV, pompa i bojler) kończy się o północy."""
        plan_end = datetime.fromisoformat(plan.result["horizon_end"])
        midnight = day_midnight(plan.plan_date + timedelta(days=1))
        last = max((item.end for item in items), default=midnight)
        return min(plan_end, max(midnight, last))

    @staticmethod
    def _plan_commands(items: list[PlanItemOut]) -> list[tuple[PlanItemOut, HubCommand]]:
        """Pozycje planu jako komendy huba ze startem z planu; pozycje bez energii (np. bojler bez grzania) pomijamy."""
        planned = []
        for item in items:
            if item.profile_kwh is None or (item.kind == "program" and not item.program_id):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=PLAN_OUTDATED_MESSAGE)
            if not any(item.profile_kwh):
                continue
            if item.kind == "program":
                command = HubCommand(
                    device_id=item.device_id, command=CommandType.START_PROGRAM, program_id=item.program_id,
                    start_at=item.start,
                )
            else:
                command = HubCommand(
                    device_id=item.device_id, command=CommandType.RUN_PROFILE, profile_kwh=item.profile_kwh,
                    start_at=item.start,
                )
            planned.append((item, command))
        return planned

    def _background(self, owner: User, plan: DayPlan, planned_devices: set[str]) -> DayBackground:
        """Urządzenia, które pracują same: z migawki planu (ZP-120), a w planie sprzed niej z dnia referencyjnego
        każdego urządzenia (PV oraz pompa ciepła i bojler spoza planu).

        Przebiegi obejmują tylko dobę 00:00–24:00, bez nocy po niej, tak jak plan liczy pompę i bojler, gdy są
        zaznaczone. Noc należy do planu na kolejny dzień, a porównanie z planem (ZP-114) ma po obu stronach ten
        sam zakres.
        """
        if plan.result.get("background") is not None:
            background = DayBackground.from_json(plan.result["background"])
            background.runs = [run for run in background.runs if run.device_id not in planned_devices]
            background.runs.sort(key=lambda run: (run.start, run.device_id))
            return background
        devices = [
            device_id for device_id in self.home_repository.device_ids_of_types(owner.id, (PV_TYPE, *THERMOSTAT_TYPES))
            if device_id not in planned_devices
        ]
        days, by_device = history_runs(self.home_repository, owner.id, plan.plan_date, devices)
        runs = sorted((run for device_runs in by_device.values() for run in device_runs),
                      key=lambda run: (run.start, run.device_id))
        devices_out = [
            BackgroundDevice(device_id, "", HISTORY, day, sum(sum(run.profile_kwh) for run in by_device[device_id]),
                             sum(sum(run.profile_kwh) for run in by_device[device_id]))
            for device_id, day in days.items()
        ]
        return DayBackground(runs=runs, devices=devices_out)

    @staticmethod
    def _history_energy(
        runs: list[ReplayRun], results: list[HubCommandResult], devices: list[BackgroundDevice],
    ) -> list[dict]:
        """Urządzenia, których przebiegi hub przyjął: skąd jest ich doba, dzień referencyjny, energia wysłana
        do huba (`history_kwh`) i energia dnia referencyjnego do raportu."""
        energy: dict[str, float] = defaultdict(float)
        for run, result in zip(runs, results, strict=True):
            if result.status != HubCommandStatus.REJECTED:
                energy[run.device_id] += sum(run.profile_kwh)
        info = {device.device_id: device for device in devices}
        return [
            {
                "device_id": device_id,
                "history_day": info[device_id].history_day.isoformat() if device_id in info and info[device_id].history_day else None,
                "history_kwh": _kwh(kwh),
                "source": info[device_id].source if device_id in info else HISTORY,
                "reference_kwh": _kwh(info[device_id].reference_kwh) if device_id in info else None,
            }
            for device_id, kwh in sorted(energy.items())
        ]

    @staticmethod
    def _action(item: PlanItemOut, result: HubCommandResult, prices: dict[datetime, float],
                with_pv: bool = False) -> PlanRunActionOut:
        """Pozycja planu z wynikiem komendy i kosztami do rachunku: bez planu (od startu bazowego) i według planu.

        Koszty liczymy cenami kwadransów planu z pełną dokładnością (w planie są zaokrąglone do grosza);
        bez ceny któregoś kwadransu zostaje koszt z planu. Plan z PV (ZP-121) ma koszty z rachunku domu
        w godzinach, których nie da się policzyć z samej pozycji, więc bierzemy je z planu.
        """
        original = item.original_profile_kwh or []
        cost_before = None if with_pv else profile_cost(original, item.original_start, prices)
        planned_cost = None if with_pv else profile_cost(item.profile_kwh or [], item.start, prices)
        return PlanRunActionOut(
            action_id=item.action_id,
            device_id=item.device_id,
            device_name=item.device_name,
            kind=item.kind,
            label=item.program_name,
            start=item.start,
            end=item.end,
            energy_kwh=item.energy_kwh,
            status=result.status,
            code=result.code,
            detail=result.detail,
            command_id=result.command_id,
            energy_before_kwh=sum(original),
            cost_before=item.cost_before if cost_before is None else cost_before,
            planned_cost=item.cost_after if planned_cost is None else planned_cost,
        )

    # --- odczyt i zakończenie ---

    def latest(self, owner: User) -> PlanRunOut | None:
        """Ostatni przebieg z raportem; status sprawdzamy w hubie, a bez huba zostaje ostatni znany."""
        run = self.run_repository.latest(owner.id)
        if run is None:
            return None
        return self._read(owner, run)

    def get(self, owner: User, run_id: UUID) -> PlanRunOut:
        run = self.run_repository.get(owner.id, run_id)
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=RUN_NOT_FOUND_MESSAGE)
        return self._read(owner, run)

    def history(self, owner: User) -> list[PlanRunSummaryOut]:
        """Przebiegi od najnowszego z rachunkiem z zapisanego raportu; status ostatni znany, bez pytania huba."""
        summaries = []
        for run in self.run_repository.latest_runs(owner.id, HISTORY_LIMIT):
            report = PlanRunCostOut.model_validate(run.report) if run.report else None
            summaries.append(PlanRunSummaryOut(
                id=run.id,
                plan_date=run.plan_date,
                status=run.status,
                started_at=run.started_at,
                ended_at=run.ended_at,
                complete=report.complete if report else None,
                cost_before=report.cost_before if report else None,
                cost_after=report.cost_after if report else None,
                saving=report.saving if report else None,
                saving_percent=report.saving_percent if report else None,
                deviations=len(report.deviations) if report else None,
            ))
        return summaries

    def _read(self, owner: User, run: PlanRun) -> PlanRunOut:
        """Raport przebiegu; status sprawdzamy w hubie, a bez huba zostaje ostatni znany."""
        clock = self._read_clock()
        self._refresh(owner, run, clock)
        out = self._out(owner, run, clock)
        self.run_repository.commit()  # Zmieniony status albo przeliczony raport.
        return out

    def end(self, owner: User, run_id: UUID) -> PlanRunOut:
        """„Zakończ”: kasuje zaplanowane komendy przebiegu (plan i historię), zatrzymuje zegar i zamyka przebieg.

        To, co urządzenia już wykonują (np. pralka w połowie programu, PV w trakcie produkcji), po ponownym
        Starcie się dokończy; wyłączyć można je ręcznie. Zakończony już przebieg zostaje bez zmian. Gdy hub
        zawiedzie po drodze, przebieg zostaje `running`, a ponowne „Zakończ” robi wszystko jeszcze raz.
        """
        run = self.run_repository.get(owner.id, run_id)
        if run is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=RUN_NOT_FOUND_MESSAGE)
        hub_client = require_hub(self.hub_client, self.home_repository, owner)
        # Jak w `start`: równoległe „Uruchom” czeka, więc zegar odczytany niżej należy do tego przebiegu.
        self.home_repository.lock()
        try:
            clock = hub_client.get_clock()
        except HubError as error:
            raise hub_http_error(error) from error
        self._refresh(owner, run, clock)
        if run.status == PlanRun.RUNNING:
            # Ani zaplanowane komendy, ani zatrzymanie o 06:00 nie mogą przeżyć planu: po Starcie o 02:00
            # ruszyłoby np. ładowanie auta z zakończonego planu, a zegar stanąłby nagle o końcu planu.
            # Najpierw kolejka: gdy hub zawiedzie przy niej, przebieg dalej ma swoje 06:00 i zostaje
            # `running`, więc ponowne „Zakończ” (albo koniec planu) domyka go bez stanu pośredniego.
            try:
                hub_client.cancel_scheduled()
            except HubError as error:
                raise hub_http_error(error) from error
            clock = update_hub_clock(hub_client, running=False, clear_stop_at=True)
            self._close(owner, run, PlanRun.ENDED, datetime.now(timezone.utc), sim_time=clock.sim_time)
        out = self._out(owner, run, clock)
        self.run_repository.commit()
        return out

    def _read_clock(self) -> HubClock | None:
        if self.hub_client is None:
            return None
        try:
            return self.hub_client.get_clock()
        except HubError as error:
            logger.warning("Przebieg planu bez zegara huba: %s", error)
            return None

    def _refresh(self, owner: User, run: PlanRun, clock: HubClock | None) -> bool:
        """Zamyka przebieg, który skończył się w hubie. Zwraca True, gdy zmienił status."""
        if run.status != PlanRun.RUNNING or clock is None:
            return False
        now = datetime.now(timezone.utc)
        if clock.simulation_id != run.simulation_id:
            self._close(owner, run, PlanRun.SUPERSEDED, now)
        elif clock.sim_time >= run.horizon_end:
            self._close(owner, run, PlanRun.COMPLETED, now, sim_time=run.horizon_end)
        else:
            return False
        return True

    def _close(self, owner: User, run: PlanRun, final_status: str, now: datetime, sim_time: datetime | None = None) -> None:
        run.status = final_status
        run.ended_at = now
        # Hub zaczął inną symulację: przebieg skończył się na ostatnim zdarzeniu, jakie z niego mamy.
        run.ended_sim_time = sim_time or self.event_repository.last_sim_time(owner.id, run.simulation_id)
        # Raport od razu: przebiegu zamkniętego przez nowe „Uruchom” nikt może już nie otworzyć, a lista
        # historii pokazuje rachunek z zapisanego raportu.
        if run.tariff is not None and run.ended_sim_time is not None:
            until = min(run.ended_sim_time, run.horizon_end)
            run.report = self._cost(owner, run, until, self._energy(owner, run, until)).model_dump(mode="json")

    @staticmethod
    def _settled(run: PlanRun) -> bool:
        """Raport zamkniętego przebiegu już się nie zmieni: zdarzenia huba zdążyły dojść."""
        return run.ended_at is not None and datetime.now(timezone.utc) - run.ended_at > REPORT_SETTLE

    # --- raport ---

    def _out(self, owner: User, run: PlanRun, clock: HubClock | None) -> PlanRunOut:
        if run.status == PlanRun.RUNNING and clock is not None and clock.simulation_id == run.simulation_id:
            sim_time = clock.sim_time
        else:
            sim_time = run.ended_sim_time or self.event_repository.last_sim_time(owner.id, run.simulation_id)
        actions = [PlanRunActionOut.model_validate(item) for item in run.items]
        by_device: dict[str, list[PlanRunActionOut]] = defaultdict(list)
        for action in actions:
            by_device[action.device_id].append(action)
        history = {entry["device_id"]: entry for entry in run.replayed_devices}
        actual = defaultdict(float)
        cost = None
        if sim_time is not None:
            until = min(sim_time, run.horizon_end)
            energy = self._energy(owner, run, until)
            actual = energy.by_device
            cost = self._report(owner, run, until, energy)
        devices = [
            PlanRunDeviceOut(
                device_id=device_id,
                device_name=device_actions[0].device_name,
                kind=device_actions[0].kind,
                planned_kwh=_kwh(sum(action.energy_kwh for action in device_actions)),
                actual_kwh=_kwh(actual.get(device_id, 0.0)),
                actions=device_actions,
            )
            for device_id, device_actions in by_device.items()
        ]
        names = self.home_repository.device_names(owner.id)
        replayed = [
            PlanRunHistoryDeviceOut(
                device_id=device_id,
                device_name=names.get(device_id, device_id),
                history_day=entry["history_day"],
                history_kwh=entry["history_kwh"],
                source=entry.get("source", HISTORY),
                reference_kwh=entry.get("reference_kwh"),
                actual_kwh=_kwh(actual.get(device_id, 0.0)),
            )
            for device_id, entry in history.items()
        ]
        errors = [
            PlanRunErrorOut(
                device_id=error.device_id,
                device_name=names.get(error.device_id, error.device_id),
                sim_time=error.sim_time.astimezone(LOCAL_TIMEZONE),
                code=error.code,
                message=error.message,
            )
            for error in self.event_repository.device_errors(owner.id, run.simulation_id, MAX_REPORTED_ERRORS)
        ]
        return PlanRunOut(
            id=run.id,
            plan_id=run.day_plan_id,
            plan_date=run.plan_date,
            status=run.status,
            simulation_id=run.simulation_id,
            started_at=run.started_at,
            ended_at=run.ended_at,
            sim_time=sim_time.astimezone(LOCAL_TIMEZONE) if sim_time else None,
            horizon_start=run.horizon_start.astimezone(LOCAL_TIMEZONE),
            horizon_end=run.horizon_end.astimezone(LOCAL_TIMEZONE),
            history_day=run.history_day,
            replay=PlanRunReplay.model_validate(run.replay),
            replayed_devices=replayed,
            planned_kwh=_kwh(sum(device.planned_kwh for device in devices)),
            actual_kwh=_kwh(sum(device.actual_kwh for device in devices)),
            devices=devices,
            errors=errors,
            cost=cost,
            prices=[PlanRunPriceOut.model_validate(entry) for entry in (run.tariff or {}).get("prices", [])],
            prices_approximate_from=(run.tariff or {}).get("approximate_from"),
            water_heaters=[
                PlanRunWaterHeaterOut.model_validate(heater) for heater in (run.tariff or {}).get("water_heaters", [])
            ],
        )

    def _energy(self, owner: User, run: PlanRun, until: datetime) -> DayEnergy:
        """Energia wszystkich urządzeń przebiegu od początku planu do `until`: plan, historia i ręczne włączenia."""
        steps = self.event_repository.energy_steps(owner.id, run.simulation_id, run.horizon_start, until)
        return day_energy(steps, run.horizon_start, until)

    def _report(self, owner: User, run: PlanRun, until: datetime, energy: DayEnergy) -> PlanRunCostOut | None:
        """Rachunek przebiegu: zapisany, gdy już się nie zmieni, a inaczej przeliczony (i zapisany po zamknięciu)."""
        if run.tariff is None:
            return None
        if run.report is not None and self._settled(run):
            return PlanRunCostOut.model_validate(run.report)
        report = self._cost(owner, run, until, energy)
        if run.status != PlanRun.RUNNING:
            run.report = report.model_dump(mode="json")
        return report

    def _cost(self, owner: User, run: PlanRun, until: datetime, energy: DayEnergy) -> PlanRunCostOut:
        actions = [PlanRunActionOut.model_validate(item) for item in run.items]
        pv_devices = set(self.home_repository.device_ids_of_types(owner.id, (PV_TYPE,)))
        prices = _prices(run.tariff)
        balance = run.tariff.get("balance")
        return cost_report(RunEnergy(
            actions=actions,
            prices=prices,
            max_grid_kw=run.tariff.get("max_grid_kw"),
            balance=HouseBalance.from_json(balance, prices) if balance else None,
            energy=energy,
            events=self.event_repository.device_actions(
                owner.id, run.simulation_id, sorted({action.device_id for action in actions}), until,
            ),
            errors=self.event_repository.device_errors(owner.id, run.simulation_id, MAX_REPORTED_ERRORS),
            names=self.home_repository.device_names(owner.id),
            background={entry["device_id"] for entry in run.replayed_devices} | pv_devices,
            pv_devices=pv_devices,
            until=until,
            complete=run.status == PlanRun.COMPLETED,
        ))


def _prices(tariff: dict) -> dict[datetime, float]:
    """Ceny kwadransów z migawki planu po początku kwadransu w UTC (jak kwadranse energii)."""
    return {
        datetime.fromisoformat(entry["start"]).astimezone(timezone.utc): entry["price_pln_kwh"]
        for entry in tariff["prices"]
    }
