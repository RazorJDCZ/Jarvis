from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ActionName(StrEnum):
    APP_OPEN = "app.open"
    BROWSER_OPEN = "browser.open"
    BROWSER_SEARCH = "browser.search"
    BROWSER_BACK = "browser.back"
    BROWSER_FORWARD = "browser.forward"
    BROWSER_REFRESH = "browser.refresh"
    BROWSER_NEW_TAB = "browser.new_tab"
    BROWSER_LIST_TABS = "browser.list_tabs"
    BROWSER_SWITCH_TAB = "browser.switch_tab"
    BROWSER_CLOSE_TAB = "browser.close_tab"
    BROWSER_READ = "browser.read"
    BROWSER_CLICK = "browser.click"
    BROWSER_FILL = "browser.fill"
    BROWSER_OPEN_RESULT = "browser.open_result"
    VOLUME_SET = "volume.set"
    VOLUME_CHANGE = "volume.change"
    VOLUME_MUTE = "volume.mute"
    VOLUME_GET = "volume.get"
    MEDIA_PLAY_PAUSE = "media.play_pause"
    MEDIA_NEXT = "media.next"
    MEDIA_PREVIOUS = "media.previous"
    MEDIA_STOP = "media.stop"
    WINDOW_LIST = "window.list"
    WINDOW_FOCUS = "window.focus"
    WINDOW_MINIMIZE = "window.minimize"
    WINDOW_MAXIMIZE = "window.maximize"
    WINDOW_RESTORE = "window.restore"
    WINDOW_CLOSE = "window.close"
    WINDOW_CURRENT = "window.current"
    UI_INSPECT = "ui.inspect"
    UI_CLICK = "ui.click"
    UI_TYPE = "ui.type"
    UI_HOTKEY = "ui.hotkey"
    UI_KEY = "ui.key"
    POINTER_CLICK = "pointer.click"
    POINTER_SCROLL = "pointer.scroll"
    SCREENSHOT_TAKE = "screenshot.take"
    SCREEN_DESCRIBE = "screen.describe"
    SCREEN_ASK = "screen.ask"
    SCREEN_FIND = "screen.find"
    SCREEN_CLICK = "screen.click"
    DESKTOP_SHOW = "desktop.show"
    CLIPBOARD_READ = "clipboard.read"
    CLIPBOARD_WRITE = "clipboard.write"
    SYSTEM_STATUS = "system.status"
    PATH_OPEN = "path.open"
    PATH_OPEN_FOLDER = "path.open_folder"
    WORKFLOW_RUN = "workflow.run"


class ActionRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKED = "blocked"


class ActionStatus(StrEnum):
    COMPLETED = "completed"
    PENDING = "pending"
    REJECTED = "rejected"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ActionSource(StrEnum):
    DETERMINISTIC = "deterministic"
    LOCAL_MODEL = "local-model"
    CONFIRMATION = "confirmation"
    API = "api"


@dataclass(frozen=True, slots=True)
class ActionPlan:
    name: ActionName
    arguments: dict[str, Any] = field(default_factory=dict)
    source: ActionSource = ActionSource.DETERMINISTIC
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class ActionWorkflowPlan:
    steps: tuple[ActionPlan, ...]
    source: ActionSource = ActionSource.DETERMINISTIC
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class BlockedIntent:
    reason: str


@dataclass(frozen=True, slots=True)
class PreparedAction:
    name: ActionName
    arguments: dict[str, Any]
    risk: ActionRisk
    description: str
    source: ActionSource


@dataclass(frozen=True, slots=True)
class PreparedWorkflow:
    steps: tuple[PreparedAction, ...]
    risk: ActionRisk
    description: str
    source: ActionSource
    name: ActionName = ActionName.WORKFLOW_RUN

    @property
    def arguments(self) -> dict[str, Any]:
        return {
            "steps": [{"name": step.name.value, "arguments": step.arguments} for step in self.steps]
        }


@dataclass(frozen=True, slots=True)
class ActionOutcome:
    status: ActionStatus
    message: str
    action_id: str | None = None
    name: ActionName | None = None
    risk: ActionRisk | None = None
    description: str | None = None
    requires_confirmation: bool = False
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PendingAction:
    action_id: str
    session_id: str
    action: PreparedAction | PreparedWorkflow
    created_at: float
    expires_at: float


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    success: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)
