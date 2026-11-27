"""/goal 命令族子包：命令面、执行面、验证面与输出漏斗的内聚分模块。

`__init__` 全量 `X as X` 再导出保持 `heagent.cli.goal` 命名空间零变化（62.1 catalog
先例）：生产消费者（wiring/interactive/gui chat）与测试的 patch/import 面不改导入路径。
"""

from __future__ import annotations

from heagent.cli.goal.commands import (
    _DECISION_TEXT_DISPLAY_LIMIT as _DECISION_TEXT_DISPLAY_LIMIT,
)
from heagent.cli.goal.commands import (
    _GOAL_SUBCOMMAND_NAMES as _GOAL_SUBCOMMAND_NAMES,
)
from heagent.cli.goal.commands import (
    _decision_display_text as _decision_display_text,
)
from heagent.cli.goal.commands import (
    _goal_auto_goal_id as _goal_auto_goal_id,
)
from heagent.cli.goal.commands import (
    _goal_auto_remove as _goal_auto_remove,
)
from heagent.cli.goal.commands import (
    _goal_bound_workflow as _goal_bound_workflow,
)
from heagent.cli.goal.commands import (
    _goal_declarative_advance as _goal_declarative_advance,
)
from heagent.cli.goal.commands import (
    _goal_declarative_decision as _goal_declarative_decision,
)
from heagent.cli.goal.commands import (
    _goal_declarative_decisions as _goal_declarative_decisions,
)
from heagent.cli.goal.commands import (
    _goal_declarative_dispatch as _goal_declarative_dispatch,
)
from heagent.cli.goal.commands import (
    _goal_declarative_doctor as _goal_declarative_doctor,
)
from heagent.cli.goal.commands import (
    _goal_declarative_new as _goal_declarative_new,
)
from heagent.cli.goal.commands import (
    _goal_declarative_pause_resume as _goal_declarative_pause_resume,
)
from heagent.cli.goal.commands import (
    _goal_declarative_run as _goal_declarative_run,
)
from heagent.cli.goal.commands import (
    _goal_declarative_status as _goal_declarative_status,
)
from heagent.cli.goal.commands import (
    _goal_declarative_verify as _goal_declarative_verify,
)
from heagent.cli.goal.commands import (
    _goal_reset as _goal_reset,
)
from heagent.cli.goal.commands import (
    _goal_resolve_bound as _goal_resolve_bound,
)
from heagent.cli.goal.commands import (
    _goal_runner as _goal_runner,
)
from heagent.cli.goal.commands import (
    _goal_runner_inner as _goal_runner_inner,
)
from heagent.cli.goal.commands import (
    _goal_start_new as _goal_start_new,
)
from heagent.cli.goal.commands import (
    _goal_typo_subcommand as _goal_typo_subcommand,
)
from heagent.cli.goal.commands import (
    _goal_usage as _goal_usage,
)
from heagent.cli.goal.commands import (
    _goal_workflow_option as _goal_workflow_option,
)
from heagent.cli.goal.commands import (
    _render_decision_records as _render_decision_records,
)
from heagent.cli.goal.execution import (
    _GOAL_ADVANCED as _GOAL_ADVANCED,
)
from heagent.cli.goal.execution import (
    _GOAL_DONE as _GOAL_DONE,
)
from heagent.cli.goal.execution import (
    _GOAL_FAILED as _GOAL_FAILED,
)
from heagent.cli.goal.execution import (
    _GOAL_WAITING as _GOAL_WAITING,
)
from heagent.cli.goal.execution import (
    _SCRIPT_READ_OPERATIONS as _SCRIPT_READ_OPERATIONS,
)
from heagent.cli.goal.execution import (
    _active_goal_dir_or_hint as _active_goal_dir_or_hint,
)
from heagent.cli.goal.execution import (
    _goal_active_md as _goal_active_md,
)
from heagent.cli.goal.execution import (
    _goal_checkpoint_mode as _goal_checkpoint_mode,
)
from heagent.cli.goal.execution import (
    _goal_checkpoint_prompt as _goal_checkpoint_prompt,
)
from heagent.cli.goal.execution import (
    _goal_declarative_active_dir as _goal_declarative_active_dir,
)
from heagent.cli.goal.execution import (
    _goal_declarative_prepare as _goal_declarative_prepare,
)
from heagent.cli.goal.execution import (
    _goal_declarative_prompt as _goal_declarative_prompt,
)
from heagent.cli.goal.execution import (
    _goal_declarative_workflow as _goal_declarative_workflow,
)
from heagent.cli.goal.execution import (
    _goal_execute_script_step as _goal_execute_script_step,
)
from heagent.cli.goal.execution import (
    _goal_execute_step as _goal_execute_step,
)
from heagent.cli.goal.execution import (
    _goal_script_declaration_error as _goal_script_declaration_error,
)
from heagent.cli.goal.execution import (
    _goal_script_validate as _goal_script_validate,
)
from heagent.cli.goal.execution import (
    _goal_session as _goal_session,
)
from heagent.cli.goal.execution import (
    _goal_workflow_package as _goal_workflow_package,
)
from heagent.cli.goal.execution import (
    _script_operation_names as _script_operation_names,
)
from heagent.cli.goal.execution import (
    _script_validate_clauses as _script_validate_clauses,
)
from heagent.cli.goal.execution import (
    _submit_script_requests as _submit_script_requests,
)
from heagent.cli.goal.messages import (
    _MESSAGE_SINK as _MESSAGE_SINK,
)
from heagent.cli.goal.messages import (
    _echo as _echo,
)
from heagent.cli.goal.verify import (
    _GOAL_GATE_LOCKS as _GOAL_GATE_LOCKS,
)
from heagent.cli.goal.verify import (
    _VERIFY_COMMAND_TIMEOUT_SECONDS as _VERIFY_COMMAND_TIMEOUT_SECONDS,
)
from heagent.cli.goal.verify import (
    _emit_goal_gate_event as _emit_goal_gate_event,
)
from heagent.cli.goal.verify import (
    _goal_gate_lock as _goal_gate_lock,
)
from heagent.cli.goal.verify import (
    _goal_live_git_evidence as _goal_live_git_evidence,
)
from heagent.cli.goal.verify import (
    _goal_step_output_text as _goal_step_output_text,
)
from heagent.cli.goal.verify import (
    _goal_structured_gate as _goal_structured_gate,
)
from heagent.cli.goal.verify import (
    _goal_verify_command_runner as _goal_verify_command_runner,
)
from heagent.cli.goal.verify import (
    _goal_verify_report as _goal_verify_report,
)
from heagent.cli.goal.verify import (
    _goal_verify_workspace as _goal_verify_workspace,
)
from heagent.cli.goal.verify import (
    _run_governed_verify_command as _run_governed_verify_command,
)
from heagent.cli.goal.verify import (
    _workflow_event_emitter as _workflow_event_emitter,
)
from heagent.cli.goal.verify import (
    _workspace_cd_prefix as _workspace_cd_prefix,
)
from heagent.goal.application import (
    GoalAdvanceContext as GoalAdvanceContext,
)
from heagent.goal.application import (
    restore_runner,
)
from heagent.goal.document import (
    goal_description as goal_description,
)
from heagent.goal.document import (
    goal_document as goal_document,
)
from heagent.goal.document import (
    goal_document_path as goal_document_path,
)
from heagent.goal.document import (
    goal_document_title as goal_document_title,
)
from heagent.goal.document import (
    goal_record_user_response as goal_record_user_response,
)
from heagent.goal.document import (
    goal_step_artifact_path as goal_step_artifact_path,
)
from heagent.goal.document import (
    goal_user_responses as goal_user_responses,
)
from heagent.goal.quality_gates import verify_step as verify_step

# 测试仍经 ``heagent.cli.goal`` 访问的 re-export 符号：确定性内核迁
# goal/application 后，goal_record_user_response / goal_user_responses 在子模块
# 已无内部调用点，靠 ``__all__`` 钉住 ruff F401 与 mypy no_implicit_reexport。
__all__ = ["goal_record_user_response", "goal_user_responses"]

# 别名再导出（restore_runner 的测试侧历史名）：非同名导入不能走 ``X as X``
# 再导出形态，显式赋值即显式定义（mypy no_implicit_reexport 认可）。
_goal_declarative_runner = restore_runner
