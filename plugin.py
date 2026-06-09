# plugin.py — Life Simulation Plugin v2.0
# All SDK decorators (@HookHandler/@Tool/@API/@Command) MUST be defined
# directly on methods of this MaiBotPlugin subclass.
# Business logic is delegated to components/ pure functions.
from __future__ import annotations
import os
import sys

# 确保插件根目录在 Python 路径中，以便宿主程序加载时能找到本地模块
_plugin_dir = os.path.dirname(os.path.abspath(__file__))
if _plugin_dir not in sys.path:
    sys.path.insert(0, _plugin_dir)

from maibot_sdk import MaiBotPlugin, HookHandler, Tool, API, Command, CONFIG_RELOAD_SCOPE_SELF
from maibot_sdk.types import HookMode, HookOrder, ErrorPolicy, ToolParameterInfo, ToolParamType

from config_model import LifeSimConfig

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


class LifeSimulationPlugin(MaiBotPlugin):

    config_model = LifeSimConfig

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def on_load(self) -> None:
        os.makedirs("data", exist_ok=True)
        self._db = Database("data/life_simulation.db")
        self._manager = LifeStateManager(self.config)
        self._budget = ResourceBudget(self.config.budget)
        self._stream_registry = StreamRegistry()
        self._registry = BackgroundTaskRegistry()

        self._schedule_sys = ScheduleSystem(
            manager=self._manager, db=self._db,
            budget=self._budget, ctx=self.ctx, config=self.config,
        )
        self._relation = RelationSystem(
            db=self._db, ctx=self.ctx,
            budget=self._budget, config=self.config.relation,
        )
        self._proactive = ProactiveSystem(
            db=self._db, ctx=self.ctx,
            manager=self._manager, budget=self._budget, config=self.config,
        )
        self._orchestrator = Orchestrator(
            manager=self._manager, db=self._db, budget=self._budget,
            schedule_sys=self._schedule_sys, relation_sys=self._relation,
            proactive_sys=self._proactive, ctx=self.ctx, config=self.config,
            stream_registry=self._stream_registry,
        )
        await self._orchestrator.start()
        self.ctx.logger.info("Life Simulation Plugin v2.0 loaded")

    async def on_unload(self) -> None:
        if hasattr(self, "_orchestrator"):
            await self._orchestrator.stop()
        self.ctx.logger.info("Life Simulation Plugin unloaded")

    async def on_config_update(self, scope: str, config_data: dict, version: str) -> None:
        if scope == CONFIG_RELOAD_SCOPE_SELF:
            # self.config 已由 SDK 自动更新为最新值
            self._orchestrator.reload_config(self.config)
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
        return await tool_logic.get_schedule_data(self._manager, self.config)

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
            self._manager.snapshot(), self.config.plugin.timezone
        )

    @API("life_sim.get_impression")
    async def _api_get_impression(self, person_id: str, **kwargs) -> dict | None:
        return await api_logic.get_impression_for_api(self._db, person_id)

    @API("life_sim.get_frequency_factor")
    async def _api_get_frequency_factor(self, **kwargs) -> float:
        snap = self._manager.snapshot()
        freq = self.config.frequency
        return getattr(freq, snap.current_activity.value, 0.0)

    @API("life_sim.get_sleep_state")
    async def _api_get_sleep_state(self, **kwargs) -> str:
        return self._manager.snapshot().sleep_state.value

    # ── Commands ───────────────────────────────────────────────────────────

    @Command("life_status", pattern=r"^/life_status")
    async def _cmd_life_status(self, **kwargs) -> tuple:
        stream_id = kwargs.get("stream_id", "")
        text = await cmd_logic.build_life_status_text(self._manager, self.config)
        await self.ctx.send.text(text, stream_id)
        return True, text, 1


def create_plugin() -> LifeSimulationPlugin:
    return LifeSimulationPlugin()
