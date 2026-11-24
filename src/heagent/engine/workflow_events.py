"""驱动 Goal 工作流状态变更的内部事件。"""

from enum import StrEnum


class WorkflowEvent(StrEnum):
    """驱动 Goal 工作流状态跃迁的内部事件词汇表。

    只描述「发生了什么」，不携带处理策略——谁消费某个事件、能否离开某个挂起态由
    ``workflow_runner`` 决定。取值同时是 checkpoint ``last_event`` 字段的封闭词汇表
    （见 ``checkpoint._WORKFLOW_EVENT_VALUES``），故新增成员即放宽该字段的合法域。
    """

    START = "start"
    STEP_COMPLETED = "step_completed"
    CHECKPOINT_REQUIRED = "checkpoint_required"
    # 步骤做完了自己的工作、但声明了 ``approval: required``：挂起等一个人工决策。
    # 它与 CHECKPOINT_REQUIRED 语义不同——检查点可由普通 resume 推进，
    # 审批门只有 approve / reject / amend 三种人工决策能离开。
    APPROVAL_REQUIRED = "approval_required"
    USER_RESUME = "user_resume"
    USER_PAUSE = "user_pause"
    # 人工决策三事件：approve / reject / amend 语义独立，不得互相顶替。
    USER_APPROVE = "user_approve"
    USER_REJECT = "user_reject"
    USER_AMEND = "user_amend"
    INPUT_MISSING = "input_missing"
    GATE_FAILED = "gate_failed"
    EXECUTOR_FAILED = "executor_failed"
    FINAL_STEP_COMPLETED = "final_step_completed"
    CANCELLED = "cancelled"
