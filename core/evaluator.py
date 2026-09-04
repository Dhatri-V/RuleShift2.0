def check_attendance(attendance, requirement):
    if attendance is None:
        return "UNKNOWN"

    if attendance >= requirement:
        return "PASS"

    return "FAIL"
