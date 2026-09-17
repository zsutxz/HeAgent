"""``/goal`` 问卷 —— 声明式问题的解析、校验、收集与写回。

问卷由工作流（而非 CLI 代码）**声明**：``GOAL.md`` 的 ``## Questionnaire`` 段（旧式独立
``QUESTIONNAIRE.md`` 文件仍作兜底）描述 applies_when、问题清单与取值约束。本模块只实现
「按声明校验」的通用规则，任何具体产品规则都不在这里。

依赖：``heagent.persist`` 的原子写 + ``click`` 的终端交互；不依赖 ``cli_goal``，
故可被独立测试（此前这些函数与工作流驱动混在单文件里）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import click
from pydantic import BaseModel

from heagent.persist import atomic_update_text

_GOAL_QUESTIONNAIRE_FILE = "QUESTIONNAIRE.md"


class GoalQuestion(BaseModel):
    """One declarative question parsed from the goal workflow Markdown."""

    number: int
    identifier: str
    prompt: str
    options: list[str] = []
    when_key: str | None = None
    when_values: list[str] = []
    value_type: str = "text"
    minimum: float | None = None


class GoalQuestionnaireSpec(BaseModel):
    """A workflow-defined questionnaire; its product rules never live in CLI code."""

    name: str
    applies_when: str
    questions: list[GoalQuestion]
    include_in_step: str | None = None


class GoalQuestionnaire(BaseModel):
    """Validated responses to a workflow-defined questionnaire."""

    name: str
    answers: dict[str, str]

    def render(self, spec: GoalQuestionnaireSpec) -> str:
        return "\n".join(
            f"Q{question.number} {question.prompt}：{self.answers[question.identifier]}"
            for question in spec.questions
            if question.identifier in self.answers
        )


def _goal_questionnaire_spec(goal_dir: Path) -> GoalQuestionnaireSpec | None:
    """Load a questionnaire owned by the concrete goal directory.

    New goals keep the declarative questionnaire in ``GOAL.md``. The standalone
    file fallback is retained for legacy/test packages that have not migrated.
    """
    goal_path = goal_dir / "GOAL.md"
    text = goal_path.read_text(encoding="utf-8") if goal_path.is_file() else ""
    section = re.search(r"(?ms)^##? Questionnaire\s*$\n(.*?)(?=^##\s|\Z)", text)
    if section is None:
        legacy_path = Path(_GOAL_QUESTIONNAIRE_FILE)
        text = legacy_path.read_text(encoding="utf-8") if legacy_path.is_file() else ""
        section = re.search(r"(?ms)^#(?:#)? Questionnaire\s*$\n(.*)\Z", text)
    if section is None:
        return None
    header, *question_blocks = re.split(r"(?m)^###\s+", section.group(1).strip())
    metadata = dict(re.findall(r"(?m)^(applies_when|include_in_step|name)\s*:\s*(.+?)\s*$", header))
    applies_when = metadata.get("applies_when", "").strip()
    name = metadata.get("name", "Questionnaire").strip()
    if not applies_when:
        raise ValueError("questionnaire requires applies_when")
    questions: list[GoalQuestion] = []
    for block in question_blocks:
        heading, _, body = block.partition("\n")
        match = re.fullmatch(r"Q(\d+)\s+(.+)", heading.strip())
        if match is None:
            raise ValueError(f"invalid questionnaire heading: {heading}")
        fields = dict(re.findall(r"(?m)^(id|options|when|type|minimum)\s*:\s*(.+?)\s*$", body))
        identifier = fields.get("id", "").strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]*", identifier):
            raise ValueError(f"questionnaire Q{match.group(1)} requires id")
        when_key, separator, raw_values = fields.get("when", "").partition("=")
        if fields.get("when") and (not separator or not when_key.strip() or not raw_values.strip()):
            raise ValueError(f"questionnaire Q{match.group(1)} has invalid when")
        value_type = fields.get("type", "text").strip()
        if value_type not in {"text", "number"}:
            raise ValueError(f"questionnaire Q{match.group(1)} type must be text or number")
        try:
            minimum = float(fields["minimum"]) if "minimum" in fields else None
        except ValueError as exc:
            raise ValueError(f"questionnaire Q{match.group(1)} has invalid minimum") from exc
        if minimum is not None and value_type != "number":
            raise ValueError(f"questionnaire Q{match.group(1)} minimum requires type number")
        questions.append(
            GoalQuestion(
                number=int(match.group(1)),
                identifier=identifier,
                prompt=match.group(2).strip(),
                options=[item.strip() for item in fields.get("options", "").split("|") if item.strip()],
                when_key=when_key.strip() or None,
                when_values=[item.strip() for item in raw_values.split("|") if item.strip()],
                value_type=value_type,
                minimum=minimum,
            )
        )
    if not questions or [question.number for question in questions] != list(range(1, len(questions) + 1)):
        raise ValueError("questionnaire questions must start at Q1 and be contiguous")
    identifiers = {question.identifier for question in questions}
    if len(identifiers) != len(questions):
        raise ValueError("questionnaire question ids must be unique")
    for index, question in enumerate(questions):
        if question.when_key is not None and question.when_key not in {prior.identifier for prior in questions[:index]}:
            raise ValueError(f"questionnaire Q{question.number} when must reference an earlier question")
    return GoalQuestionnaireSpec(
        name=name,
        applies_when=applies_when,
        questions=questions,
        include_in_step=metadata.get("include_in_step", "").strip() or None,
    )


def _goal_questionnaire_applies(spec: GoalQuestionnaireSpec | None, description: str) -> bool:
    if spec is None:
        return False
    try:
        return re.search(spec.applies_when, description, re.IGNORECASE) is not None
    except re.error as exc:
        raise ValueError(f"questionnaire applies_when is invalid: {exc}") from exc


def _goal_question_value_error(question: GoalQuestion, value: str) -> str:
    """Validate one answer against its declared question; empty string means valid."""
    if not value:
        return f"缺少 Q{question.number} {question.prompt}"
    if question.options and value not in question.options:
        return f"Q{question.number} 必须是：" + "、".join(question.options)
    if question.value_type == "number":
        try:
            numeric = float(value)
        except ValueError:
            return f"Q{question.number} 必须是数字"
        if question.minimum is not None and numeric < question.minimum:
            return f"Q{question.number} 不能小于 {question.minimum:g}"
    return ""


def _goal_questionnaire_from_text(text: str, spec: GoalQuestionnaireSpec) -> tuple[GoalQuestionnaire | None, str]:
    """Validate answers against the workflow declaration without product-specific rules."""
    values = {
        int(number): answer.strip() for number, answer in re.findall(r"(?mi)^Q(\d+)\s*[^：:\n]*[：:]\s*(.+?)\s*$", text)
    }
    answers = {question.identifier: values.get(question.number, "") for question in spec.questions}
    for question in spec.questions:
        active = question.when_key is None or answers.get(question.when_key, "") in question.when_values
        if not active:
            answers.pop(question.identifier, None)
            continue
        error = _goal_question_value_error(question, answers[question.identifier])
        if error:
            return None, error
    return GoalQuestionnaire(name=spec.name, answers=answers), ""


def _goal_questionnaire(goal_dir: Path, spec: GoalQuestionnaireSpec) -> GoalQuestionnaire | None:
    text = (goal_dir / "GOAL.md").read_text(encoding="utf-8")
    match = re.search(rf"(?ms)^## Questionnaire: {re.escape(spec.name)}\s*$\n(.*?)(?=^##\s|\Z)", text)
    if match is None:
        return None
    questionnaire, error = _goal_questionnaire_from_text(match.group(1), spec)
    if questionnaire is None:
        raise ValueError(f"questionnaire is invalid: {error}")
    return questionnaire


def _goal_record_questionnaire(goal_dir: Path, questionnaire: GoalQuestionnaire, spec: GoalQuestionnaireSpec) -> None:
    if _goal_questionnaire(goal_dir, spec) is not None:
        return

    def update(raw: str) -> tuple[str, None]:
        return raw.rstrip() + f"\n\n## Questionnaire: {spec.name}\n\n{questionnaire.render(spec)}\n", None

    atomic_update_text(goal_dir / "GOAL.md", update)


def _goal_collect_questionnaire(spec: GoalQuestionnaireSpec) -> GoalQuestionnaire | None:
    """Collect only questions declared in the workflow, retaining answers in memory."""
    if not sys.stdin.isatty():
        return None
    answers: dict[str, str] = {}
    try:
        for question in spec.questions:
            if question.when_key is not None and answers.get(question.when_key) not in question.when_values:
                continue
            prompt_type: Any = (
                click.Choice(question.options)
                if question.options
                else float
                if question.value_type == "number"
                else str
            )
            while True:
                value = str(click.prompt(f"Q{question.number} {question.prompt}", type=prompt_type)).strip()
                error = _goal_question_value_error(question, value)
                if error:
                    click.echo(f"请重新输入：{error}", err=True)
                    continue
                answers[question.identifier] = value
                break
        return GoalQuestionnaire(name=spec.name, answers=answers)
    except (EOFError, KeyboardInterrupt, click.Abort, click.BadParameter):
        return None


def _goal_show_questionnaire_prompt(spec: GoalQuestionnaireSpec, error: str = "") -> None:
    if error:
        click.echo(f"[goal] questionnaire invalid: {error}", err=True)
    template = "\n".join(f"Q{question.number} {question.prompt}：<answer>" for question in spec.questions)
    click.echo(f"[goal] answer with /goal resume followed by:\n{template}", err=True)
