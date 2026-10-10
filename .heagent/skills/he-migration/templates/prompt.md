{workflow_instructions}

# Declarative workflow step
Goal: {goal}
Goal directory: {goal_dir}
Goal document: {goal_document}
Project output root: {output_root}
Step: {step}
{story_context}Role instructions:
{role}
Open question policy:
{open_question_policy}
Declared inputs:
{inputs}
{gate}Execute only this declared step. Durable non-code artifacts go under the project output root. Return the complete artifact body as your final response; never perform an irreversible operation without a frozen rollback plan.
