from ai.llm import get_llm
from schemas.rule import Rule


def extract_attendance_rule(policy_text):
    structured_llm = get_llm().with_structured_output(Rule)

    prompt = f"""
Extract the minimum attendance percentage from this policy.
Return only the structured attendance requirement.

Policy text:
{policy_text}
"""

    return structured_llm.invoke(prompt)
