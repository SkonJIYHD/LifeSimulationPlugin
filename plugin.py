# plugin.py — Life Simulation Plugin v2.0
# All SDK decorators (@HookHandler/@Tool/@API/@Command) MUST be defined
# directly on methods of this MaiBotPlugin subclass.
# Business logic is delegated to components/ pure functions.
from __future__ import annotations
import logging
import os
from typing import Any

from maibot_sdk import MaiBotPlugin, HookHandler, Tool, API, Command
from maibot_sdk.types import HookMode, HookOrder, ErrorPolicy, ToolParameterInfo, ToolParamType

from core.state import LifeStateManager
from core.database import Database
from core.budget import ResourceBudget
from core.orchestrator import Orchestrator, BackgroundTaskRegistry, StreamRegistry
from systems.schedule import ScheduleSystem
from systems.relation import RelationSystem
from systems.proactive import ProactiveSystem
from components import hooks as hook_logic
from components import tools as tool_logic
from components import apis as api_logic
from components import commands as cmd_logic

logger = logging.getLogger(__name__)


class LifeSimulationPlugin(MaiBotPlugin):

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def on_load(self) -> None:
        config = await self._load_config()
        self._config = config

        os.makedirs("data", exist_ok=True)
        self._db = Database("data/life_simulation.db")
        self._manager = LifeStateManager(config)
        self._budget = ResourceBudget(config.budget)
        self._stream_registry = StreamRegistry()
        self._registry = BackgroundTaskRegistry()

        self._schedule_sys = ScheduleSystem(
            manager=self._manager, db=self._db,
            budget=self._budget, ctx=self.ctx, config=config,
        )
        self._relation = RelationSystem(
            db=self._db, ctx=self.ctx,
            budget=self._budget, config=config.relation,
        )
        self._proactive = ProactiveSystem(
            db=self._db, ctx=self.ctx,
            manager=self._manager, budget=self._budget, config=config,
        )
        self._orchestrator = Orchestrator(
            manager=self._manager, db=self._db, budget=self._budget,
            schedule_sys=self._schedule_sys, relation_sys=self._relation,
            proactive_sys=self._proactive, ctx=self.ctx, config=config,
            stream_registry=self._stream_registry,
        )
        await self._orchestrator.start()
        self.ctx.logger.info("Life Simulation Plugin v2.0 loaded")

    async def on_unload(self) -> None:
        if hasattr(self, "_orchestrator"):
            await self._orchestrator.stop()
        self.ctx.logger.info("Life Simulation Plugin unloaded")

    async def on_config_update(self, scope: str, config_data: dict, version: str) -> None:
        if scope == "self":
            config = self._parse_config(config_data)
            self._config = config
            self._orchestrator.reload_config(config)
            self.ctx.logger.info("Config updated, version=%s", version)

    # ── HookHandlers ───────────────────────────────────────────────────────

    @HookHandler(
        "chat.receive.before_process",
        name="life_sim_sleep_gate",
        description="Intercept messages while sleeping",
        mode=HookMode.BLOCKING,
        order=HookOrder.EARLY,
        error_policy=ErrorPolicy.SKIP,
    )
    async def _hook_sleep_gate(self, **kwargs) -> dict:
        return await hook_logic.handle_sleep_gate(
            self._manager, self._stream_registry, **kwargs
        )

    @HookHandler(
        "chat.receive.after_process",
        name="life_sim_interaction_observer",
        description="Observe messages to update relation network",
        mode=HookMode.OBSERVE,
        order=HookOrder.NORMAL,
    )
    async def _hook_observe_interaction(self, **kwargs) -> None:
        await hook_logic.observe_interaction(self._relation, self._registry, **kwargs)

    # ── Tools ──────────────────────────────────────────────────────────────

    @Tool(
        "get_life_state",
        brief_description="Get current life simulation status",
        detailed_description="Returns current activity, sleep state, and a natural language status hint.",
        parameters=None,
    )
    async def _tool_get_life_state(self, **kwargs) -> dict:
        return await tool_logic.get_life_state_data(self._manager)

    @Tool(
        "get_today_schedule",
        brief_description="Get today's schedule",
        detailed_description="Returns current and upcoming activities (up to 3, within 4 hours).",
        parameters=None,
    )
    async def _tool_get_today_schedule(self, **kwargs) -> dict:
        return await tool_logic.get_schedule_data(self._manager, self._config)

    @Tool(
        "get_person_impression",
        brief_description="Get impression of a person by name",
        detailed_description="Returns traits and affinity hint for the named person.",
        parameters=[
            ToolParameterInfo(
                name="person_name",
                param_type=ToolParamType.STRING,
                description="The display name of the person",
                required=True,
            ),
        ],
    )
    async def _tool_get_person_impression(self, person_name: str, **kwargs) -> dict | None:
        return await tool_logic.get_impression_data(self.ctx, self._db, person_name)

    # ── APIs ───────────────────────────────────────────────────────────────

    @API("life_sim.get_current_state")
    async def _api_get_current_state(self, schema_version: str = "v1", **kwargs) -> dict:
        return api_logic.build_state_dto(self._manager.snapshot(), schema_version)

    @API("life_sim.get_schedule")
    async def _api_get_schedule(self, **kwargs) -> list[dict]:
        return api_logic.build_schedule_list(
            self._manager.snapshot(), self._config.plugin.timezone
        )

    @API("life_sim.get_impression")
    async def _api_get_impression(self, person_id: str, **kwargs) -> dict | None:
        return await api_logic.get_impression_for_api(self._db, person_id)

    @API("life_sim.get_frequency_factor")
    async def _api_get_frequency_factor(self, **kwargs) -> float:
        snap = self._manager.snapshot()
        freq = self._config.frequency
        return getattr(freq, snap.current_activity.value, 0.0)

    @API("life_sim.get_sleep_state")
    async def _api_get_sleep_state(self, **kwargs) -> str:
        return self._manager.snapshot().sleep_state.value

    # ── Commands ───────────────────────────────────────────────────────────

    @Command("life_status", pattern=r"^/life_status")
    async def _cmd_life_status(self, **kwargs) -> tuple:
        stream_id = kwargs.get("stream_id", "")
        text = await cmd_logic.build_life_status_text(self._manager, self._config)
        await self.ctx.send.text(text, stream_id)
        return True, text, 1

    # ── Config helpers ─────────────────────────────────────────────────────

    async def _load_config(self) -> Any:
        raw = await self.ctx.config.get_all()
        return self._parse_config(raw)

    def _parse_config(self, raw: dict) -> Any:
        from types import SimpleNamespace

        def ns(d: dict) -> Any:
            obj = SimpleNamespace()
            for k, v in d.items():
                setattr(obj, k, ns(v) if isinstance(v, dict) else v)
            return obj

        defaults = {
            "plugin": {"enabled": True, "timezone": "Asia/Shanghai"},
            "schedule": {
                "sleep_start": "23:00", "sleep_end": "07:00",
                "breakfast_start": "07:30", "breakfast_end": "08:00",
                "lunch_start": "12:00", "lunch_end": "12:30",
                "dinner_start": "18:00", "dinner_end": "18:30",
            },
            "sleep": {"sleepy_duration_minutes": 30, "waking_duration_minutes": 15},
            "frequency": {
                "sleeping": -1.0, "exercising": -0.6,
                "studying": -0.4, "working": -0.4,
                "eating": -0.2, "leisure": 0.0, "other": 0.0,
            },
            "relation": {
                "min_update_interval_minutes": 30,
                "dirty_queue_max_size": 500,
                "dirty_queue_ttl_seconds": 7200,
            },
            "proactive": {
                "enabled": True, "schedule_transition_probability": 0.4,
                "waking_probability_factor": 0.3, "global_cooldown_minutes": 30,
                "per_group_cooldown_minutes": 60, "quiet_hours_start": "23:00",
                "quiet_hours_end": "07:00", "daily_limit": 5, "max_consecutive": 2,
                "consecutive_reset_after_minutes": 120, "score_threshold": 0.7,
                "debounce_seconds": 5,
            },
            "llm": {"timeout_seconds": 30, "max_retries": 2, "max_repair_attempts": 2},
            "budget": {
                "llm_schedule_per_day": 3, "llm_impression_per_hour": 50,
                "llm_proactive_intent_per_hour": 20, "dirty_flush_per_heartbeat": 10,
            },
            "db": {"checkpoint_interval_minutes": 60, "max_size_mb": 50},
            "heartbeat": {"interval_seconds": 600},
            "tool": {"upcoming_count": 3, "upcoming_hours_ahead": 4},
            "prompts": {"schedule_generation": "", "impression_update": "", "proactive_intent": ""},
        }

        def deep_merge(base: dict, override: dict) -> dict:
            result = dict(base)
            for k, v in override.items():
                if isinstance(v, dict) and isinstance(result.get(k), dict):
                    result[k] = deep_merge(result[k], v)
                else:
                    result[k] = v
            return result

        merged = deep_merge(defaults, raw or {})
        config = ns(merged)
        config.max_recent_events = 20
        return config


def create_plugin() -> LifeSimulationPlugin:
    return LifeSimulationPlugin()
