"""Candidate review of observed entry facts, never a completed transaction."""

def review_entries(entries):
    calendar = {}
    for entry in entries:
        key = entry['detail_fact']['business_key']
        calendar.setdefault(key, []).append({'event': entry['id'], 'source': entry['source'],
                                             'stall_state': 'not_observed', 'month_complete': False})
    return calendar
