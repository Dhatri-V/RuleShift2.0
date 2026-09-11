"""Conservative recognition of explicit ordinary attendance provisions.

No inferred thresholds: multiple different values require human resolution.
Offsets refer to the supplied source text; quoted evidence retains qualifiers.
"""
import re

PROVISION = re.compile(
    r'\b(?:the\s+)?(?:ordinary\s+)?minimum\s+attendance(?:\s+requirement)?\s+(?:is|of)\s+'
    r'(?P<value>\d+(?:\.\d+)?)\s*(?:%|percent\b)[^.\n]*(?:\.|$)', re.I
)


# A normative "must maintain" clause is distinct from a student's measured
# attendance or a conditional condonation boundary. Require course-wide scope.
COURSE_PROVISION = re.compile(
    r"\bStudents\s+must\s+maintain\s+(?:at\s+least|a\s+minimum\s+of)\s+"
    r"(?P<value>\d+(?:\.\d+)?)\s*(?:%|percent\b)\s+attendance\s+"
    r"in\s+each\s+(?:registered\s+)?course\b[^.]*\.", re.I
)
NON_GOVERNING_BLOCK = re.compile(
    r"^(?:\d+(?:\.\d+)*\.?\s*)?(?:worked\s+(?:example|review\s+case)|"
    r"example|review\s+and\s+decision)\b", re.I
)


def attendance_provisions(text):
    facts = []
    # Retain paragraph boundaries so labelled examples do not become rules when
    # line-wrap whitespace is normalised. Bare numbers are never candidates.
    for paragraph in re.split(r"\n\s*\n", text):
        normal = re.sub(r"\s+", " ", paragraph).strip()
        if NON_GOVERNING_BLOCK.match(normal):
            continue
        for pattern in (PROVISION, COURSE_PROVISION):
            for match in pattern.finditer(normal):
                # A quoted/hypothetical must-maintain statement is not itself
                # an operative provision. Accept a standalone sentence or an
                # explicitly labelled governing paragraph.
                prefix = normal[:match.start()].strip()
                if pattern is COURSE_PROVISION and prefix and not re.search(
                    r"(?:governing requirement|governing provision)\.\s*$", prefix, re.I
                ):
                    continue
                value = float(match['value'])
                if 0 <= value <= 100:
                    fact = dict(value=value, quote=match.group().strip())
                    if fact not in facts:
                        facts.append(fact)
    return facts


def ordinary_attendance_question(question):
    return bool(re.fullmatch(
        r'\s*(?:what attendance (?:should i maintain|is required)|'
        r'what is the (?:minimum |ordinary )?attendance requirement|'
        r'how much attendance is required|what attendance percentage (?:do i need|is required))\s*[?.!]*\s*',
        question, re.I))
