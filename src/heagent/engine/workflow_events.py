"""Internal events that drive Goal workflow status changes."""

from enum import StrEnum


class WorkflowEvent(StrEnum):
    START = "start"
    STEP_COMPLETED = "step_completed"
    CHECKPOINT_REQUIRED = "checkpoint_required"
    USER_RESUME = "user_resume"
    USER_PAUSE = "user_pause"
    INPUT_MISSING = "input_missing"
    GATE_FAILED = "gate_failed"
    EXECUTOR_FAILED = "executor_failed"
    FINAL_STEP_COMPLETED = "final_step_completed"
    CANCELLED = "cancelled"
