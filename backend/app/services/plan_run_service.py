"""Wykonanie zatwierdzonego planu dnia w symulacji Smart Home (ZP-113).

Uruchomienie zaczyna w hubie dobę planu od północy i wysyła jednym żądaniem całą dobę:

- pozycje planu: program pralki czy zmywarki jako `start_program`, a auto, bojler i pompa ciepła jako
  `run_profile` z profilem z planu (zera w przerwach ładowania), każda ze startem z planu w `start_at`;
- pompa ciepła i bojler odznaczone w planie jako przebiegi z historii: plan zakłada, że pracują same, jak
  zwykle. Bierzemy dobę dnia referencyjnego (dnia planu, gdy ma historię, np. plan demo z przeszłości,
  a inaczej ostatniego dnia przed nim), przeniesioną na te same godziny doby planu, bez nocy po niej.

Urządzeń stałych (światło, lodówka, PV) nie odtwarzamy: symulacja pokazuje plan, a oszczędność planu
i tak ich nie obejmuje, bo plan ich nie przesuwa. Pełną dobę z historii odtwarza ustawienie doby na zegarze.

Zegar rusza ze `stop_at` na koniec planu, więc hub sam staje o 06:00 następnego dnia. Hub jest jedynym
źródłem czasu i stanu, więc status przebiegu sprawdzamy przy odczycie: hub z innym `simulation_id` zaczął
nową symulację (`superseded`), a zegar na końcu planu kończy przebieg (`completed`).
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
from app.schemas.plan_run import PlanRunActionOut, PlanRunDeviceOut, PlanRunErrorOut, PlanRunOut
from app.schemas.smart_home import (
    CommandType,
    HomeReplay,
    HubClock,
    HubCommand,
    HubCommandResult,
    HubCommandStatus,
)
from app.services.home_control_service import (
    INVALID_RESPONSE_MESSAGE,
    day_midnight,
    hub_http_error,
    require_hub,
    send_batch,
    update_hub_clock,
)
from app.services.home_replay import ReplayRun, moved_runs, replay_commands, replay_runs, replay_summary
from app.services.home_state_service import day_energy
from app.services.plan_history import local_day
from app.services.planning_service import HEAT_PUMP_TYPE, WATER_HEATER_TYPE


logger = logging.getLogger(__name__)

PLAN_NOT_FOUND_MESSAGE = "Nie ma takiego planu."
RUN_NOT_FOUND_MESSAGE = "Nie ma takiego przebiegu planu."
PLAN_NOT_APPROVED_MESSAGE = "Zatwierdź plan, zanim uruchomisz go w symulacji."
PLAN_OUTDATED_MESSAGE = (
    "Ten plan ułożono, zanim można było go uruchomić w symulacji. Ułóż go ponownie i zatwierdź."
)
PLAN_FAILED_MESSAGE = "Doba planu została ustawiona, ale hub nie przyjął planu. Uruchom plan ponownie."
# Urządzenia pracujące same na termostacie, gdy plan ich nie układa: odtwarzamy je z historii jak stałe.
THERMOSTAT_TYPES = (HEAT_PUMP_TYPE, WATER_HEATER_TYPE)
MAX_REPORTED_ERRORS = 50


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
        horizon_start = datetime.fromisoformat(plan.result["horizon_start"])
        horizon_end = datetime.fromisoformat(plan.result["horizon_end"])
        history_day, runs = self._unplanned_history(owner, plan, {item.device_id for item in items})

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
        run = self.run_repository.add(PlanRun(
            user_id=owner.id,
            day_plan_id=plan.id,
            plan_date=plan.plan_date,
            simulation_id=clock.simulation_id,
            status=PlanRun.RUNNING,
            horizon_start=horizon_start,
            horizon_end=horizon_end,
            history_day=history_day,
            items=[
                self._action(item, result).model_dump(mode="json")
                for (item, _), result in zip(planned, plan_results, strict=True)
            ],
            replay=replay_summary(runs, replay_results).model_dump(mode="json"),
            replayed_devices=sorted({
                run.device_id for run, result in zip(runs, replay_results, strict=True)
                if result.status != HubCommandStatus.REJECTED
            }),
            started_at=now,
        ))
        # Zegar sam stanie o końcu planu: później nie ma już czego symulować.
        clock = update_hub_clock(hub_client, running=True, stop_at=horizon_end)
        self.run_repository.commit()
        return self._out(owner, run, clock)

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

    def _unplanned_history(
        self, owner: User, plan: DayPlan, planned_devices: set[str],
    ) -> tuple[date | None, list[ReplayRun]]:
        """Pompa ciepła i bojler spoza planu: doba dnia referencyjnego (00:00–24:00) przeniesiona na dobę planu.

        Tylko doba, bez nocy po niej, tak jak plan liczy te urządzenia, gdy są zaznaczone: bojler na dobę planu,
        a pompa ciepła bloki z jednego dnia. Noc należy do planu na kolejny dzień, a porównanie z planem
        (ZP-114) ma po obu stronach ten sam zakres.
        """
        devices = [
            device_id for device_id in self.home_repository.device_ids_of_types(owner.id, THERMOSTAT_TYPES)
            if device_id not in planned_devices
        ]
        last = self.home_repository.last_slot_before(
            owner.id, devices, day_midnight(plan.plan_date + timedelta(days=1)).astimezone(timezone.utc),
        )
        if last is None:
            return None, []
        source = local_day(last)
        slots = self.home_repository.action_slots(
            owner.id,
            devices,
            day_midnight(source).astimezone(timezone.utc),
            day_midnight(source + timedelta(days=1)).astimezone(timezone.utc),
        )
        return source, moved_runs(replay_runs(slots), source, plan.plan_date)

    @staticmethod
    def _action(item: PlanItemOut, result: HubCommandResult) -> PlanRunActionOut:
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
        )

    # --- odczyt i zakończenie ---

    def latest(self, owner: User) -> PlanRunOut | None:
        """Ostatni przebieg z raportem; status sprawdzamy w hubie, a bez huba zostaje ostatni znany."""
        run = self.run_repository.latest(owner.id)
        if run is None:
            return None
        clock = self._read_clock()
        if self._refresh(owner, run, clock):
            self.run_repository.commit()
        return self._out(owner, run, clock)

    def end(self, owner: User, run_id: UUID) -> PlanRunOut:
        """„Zakończ”: zatrzymuje zegar i zamyka przebieg. Zakończony już przebieg zostaje bez zmian."""
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
            # Bez zatrzymania o końcu planu: ręczny Start po „Zakończ” nie stanie nagle o 06:00.
            clock = update_hub_clock(hub_client, running=False, clear_stop_at=True)
            self._close(owner, run, PlanRun.ENDED, datetime.now(timezone.utc), sim_time=clock.sim_time)
        self.run_repository.commit()
        return self._out(owner, run, clock)

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
        actual = defaultdict(float)
        if sim_time is not None and by_device:
            until = min(sim_time, run.horizon_end)
            steps = self.event_repository.energy_steps(
                owner.id, run.simulation_id, run.horizon_start, until, device_ids=list(by_device),
            )
            actual = day_energy(steps, run.horizon_start, until).by_device
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
            replay=HomeReplay.model_validate(run.replay),
            replayed_devices=run.replayed_devices,
            planned_kwh=_kwh(sum(device.planned_kwh for device in devices)),
            actual_kwh=_kwh(sum(device.actual_kwh for device in devices)),
            devices=devices,
            errors=errors,
        )
