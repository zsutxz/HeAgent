"""Internal events that drive Goal workflow status changes."""

from enum import StrEnum


class WorkflowEvent(StrEnum):
    START = "start"
    STEP_COMPLETED = "step_completed"
    CHECKPOINT_REQUIRED = "checkpoint_required"
    # 步骤做完了自己的工作、但声明了 ``approval: required``：挂起等一个人工决策
    # （Story 51-5）。它与 CHECKPOINT_REQUIRED 语义不同——检查点可由普通 resume 推进，
    # 审批门只有 approve / reject / amend 三种人工决策能离开。
    APPROVAL_REQUIRED = "approval_required"
    USER_RESUME = "user_resume"
    USER_PAUSE = "user_pause"
    # 人工决策三事件（Story 51-5，AD-3）：approve / reject / amend 语义独立，不得互相顶替。
    USER_APPROVE = "user_approve"
    USER_REJECT = "user_reject"
    USER_AMEND = "user_amend"
    INPUT_MISSING = "input_missing"
    GATE_FAILED = "gate_failed"
    EXECUTOR_FAILED = "executor_failed"
    FINAL_STEP_COMPLETED = "final_step_completed"
    CANCELLED = "cancelled"
