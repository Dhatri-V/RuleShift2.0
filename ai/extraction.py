from ai.llm import get_llm
from core.attendance_source import attendance_provisions
from schemas.rule import Rule


def extract_attendance_rule(policy_text):
    facts = attendance_provisions(policy_text)
    values = {fact['value'] for fact in facts}
    if len(values) == 1:
        return Rule(attendance_requirement=values.pop())
    if len(values) > 1:
        raise ValueError("Conflicting source attendance requirements; manual review is required.")
    if len(policy_text) > 6000:
        raise ValueError("No unambiguous explicit attendance rule found; refusing to truncate a long source.")
    structured_llm = get_llm().with_structured_output(Rule)

    prompt = f"""
Extract the minimum attendance percentage from this policy.
Return only the structured attendance requirement.

Policy text:
{policy_text}
"""

    return structured_llm.invoke(prompt)
