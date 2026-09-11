"""Check the transitional scalar against authoritative, version-owned pages."""
from fastapi import HTTPException
from core.attendance_source import attendance_provisions
from database.models import Rule, AuditEvent


def source_check(policy):
    source = policy.source_document
    if source is None:
        return {'status': 'UNAVAILABLE', 'message': 'No persisted PDF source; legacy/manual value is not source-verified.'}
    evidence = []
    for page in source.pages:
        for fact in attendance_provisions(page.source_text):
            evidence.append({**fact, 'page_number': page.page_number})
    values = {e['value'] for e in evidence}
    if not values:
        return {'status': 'ABSENT', 'message': 'Source attendance ABSENT: no supported explicit ordinary attendance provision was found. Review the PDF before verification.', 'evidence': []}
    if len(values) > 1:
        candidates = [
            {'value': value, 'pages': sorted({e['page_number'] for e in evidence if e['value'] == value})}
            for value in sorted(values)
        ]
        summary = '; '.join(
            f"{c['value']:g}% (pages {', '.join(map(str, c['pages']))})" for c in candidates
        )
        return {'status': 'AMBIGUOUS', 'message': f'Source attendance AMBIGUOUS: competing ordinary requirements: {summary}. Resolve the source conflict before verification.',
                'candidates': candidates, 'evidence': evidence}
    value = next(iter(values))
    status = 'MATCH' if policy.attendance_requirement == value else 'MISMATCH'
    return {'status': status, 'expected_value': value, 'evidence': evidence,
            'message': f'Source requires {value:g}% (page {evidence[0]["page_number"]}); stored value is {policy.attendance_requirement}%.'}


def require_source_match(policy, value=None):
    check = source_check(policy)
    # Preserve source-free manual records; the listing explicitly labels them.
    if check['status'] == 'UNAVAILABLE':
        return check
    if 'expected_value' not in check or (policy.attendance_requirement if value is None else value) != check['expected_value']:
        raise HTTPException(status_code=409, detail=check['message'])
    return check


def record_verified_rule(database, policy, admin):
    check = require_source_match(policy)
    if check['status'] == 'UNAVAILABLE':
        return
    # Link the rule to a clause containing the complete explicit source phrase.
    clauses = [c for c in policy.clauses if any(f['value'] == check['expected_value'] for f in attendance_provisions(c.source_text))]
    if not clauses:
        raise HTTPException(status_code=409, detail='No complete attendance source clause is available for verification.')
    if policy.rules:
        rule = policy.rules[0]
    else:
        rule = Rule(version=policy)
        database.add(rule)
    rule.attendance_requirement = check['expected_value']
    rule.source_clause_id = clauses[0].id
    rule.legacy_unverified = False
    database.add(AuditEvent(family_id=policy.family_id, version_id=policy.id,
        actor_type='ADMIN', actor_id=admin['sub'], action='SOURCE_RULE_VERIFIED',
        after_state={'attendance_requirement': rule.attendance_requirement,
                     'source_clause_id': rule.source_clause_id, 'source_sha256': policy.source_document.sha256}))
