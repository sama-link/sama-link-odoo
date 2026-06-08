"""Shared mocking helpers for Edara proxy tests (no live network)."""


class FakeResponse:
    """Minimal stand-in for a requests.Response."""

    def __init__(self, status_code, payload, raise_json=False):
        self.status_code = status_code
        self._payload = payload
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("Not JSON")
        return self._payload


def envelope(data=None, success=True, status=None, warnings=None, errors=None,
             data_type=None, page=1, page_size=500, total_count=None):
    """Build a standard Edara envelope payload."""
    if total_count is None:
        total_count = len(data or [])
    payload = {
        'success': success,
        'request_id': 'req-test',
        'generated_at': '2026-06-08T00:00:00',
        'source': 'edara_proxy',
        'data_type': data_type,
        'period': {'date_from': '2026-04-01', 'date_to': '2026-04-30'},
        'pagination': {'page': page, 'page_size': page_size, 'total_count': total_count},
        'warnings': warnings or [],
        'errors': errors or [],
        'data': data if data is not None else [],
    }
    if status is not None:
        payload['status'] = status
    return payload


# Endpoint segments in match priority order (longest/most-specific first so
# '/sales-targets' is not shadowed by '/sales').
_SEGMENTS = [
    ('health', '/health'),
    ('schema', '/schema'),
    ('sales_targets', '/sales-targets'),
    ('stock_purchasing', '/stock-purchasing'),
    ('branch_profitability', '/branch-profitability'),
    ('installations', '/installations'),
    ('employees', '/employees'),
    ('sales', '/sales'),
]


def make_router(responses, page_responses=None):
    """Return a requests.request side_effect routing by URL segment.

    ``responses``: {scope_key: (status_code, payload)}.
    ``page_responses``: optional {scope_key: [(status_code, payload), ...]} that
    yields a different response per call (for pagination tests).
    """
    state = {'calls': []}
    page_index = {}

    def _handler(method=None, url=None, headers=None, params=None, timeout=None, **kw):
        state['calls'].append((url, dict(params or {})))
        for key, seg in _SEGMENTS:
            if seg in (url or ''):
                if page_responses and key in page_responses:
                    idx = page_index.get(key, 0)
                    seq = page_responses[key]
                    code, payload = seq[min(idx, len(seq) - 1)]
                    page_index[key] = idx + 1
                    return FakeResponse(code, payload)
                code, payload = responses[key]
                return FakeResponse(code, payload)
        return FakeResponse(404, {'success': False, 'errors': [{'code': 'NOT_FOUND'}]})

    _handler.calls = state['calls']
    return _handler
