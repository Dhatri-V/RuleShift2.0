from core.evaluator import check_attendance


def compare_rules(attendance, old_requirement, new_requirement):
    old_result = check_attendance(attendance, old_requirement)
    new_result = check_attendance(attendance, new_requirement)

    if old_result == "UNKNOWN" or new_result == "UNKNOWN":
        return "MORE_INFORMATION_REQUIRED"

    if old_result == "PASS" and new_result == "PASS":
        return "STILL_COMPLIANT"

    if old_result == "PASS" and new_result == "FAIL":
        return "NEWLY_NON_COMPLIANT"

    if old_result == "FAIL" and new_result == "PASS":
        return "NEWLY_COMPLIANT"

    return "STILL_NON_COMPLIANT"
