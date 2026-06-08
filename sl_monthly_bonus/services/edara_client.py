"""Edara Proxy HTTP client.

Thin, stateless wrapper around the Edara Monthly-Bonus proxy contract. It only
*reads* from the proxy and validates the response envelope; it performs NO ORM
writes. Persistence (staging upsert, sync logging) is the caller's job.

Authoritative envelope (NOT rows/page/total/error)::

    {
      "success": true,
      "request_id": "...",
      "generated_at": "ISO",
      "source": "edara_proxy",
      "data_type": "sales",
      "period": {"date_from": "YYYY-MM-DD", "date_to": "YYYY-MM-DD"},
      "pagination": {"page": 1, "page_size": 500, "total_count": 0},
      "warnings": [],
      "errors": [],
      "data": []
    }

Privacy: this module NEVER logs the token, Authorization header, or raw payload
rows. Error messages are sanitized to codes / HTTP status only.
"""
import logging
import time
import uuid

from odoo import _
from odoo.exceptions import UserError, ValidationError

try:
    import requests
except ImportError:  # pragma: no cover - guarded by manifest external_dependencies
    requests = None

_logger = logging.getLogger(__name__)

API_PREFIX = '/api/monthly-bonus'
TRANSIENT_HTTP = (502, 503, 504)

# scope -> proxy endpoint path segment
ENDPOINTS = {
    'health': 'health',
    'schema': 'schema',
    'employees': 'employees',
    'sales': 'sales',
    'sales_targets': 'sales-targets',
    'stock_purchasing': 'stock-purchasing',
    'installations': 'installations',
    'branch_profitability': 'branch-profitability',
}


class EdaraConfigMissing(UserError):
    """Proxy / data-source configuration is missing (operator-fixable).

    Maps to CONFIGURATION_MISSING. Per-scope: fails the affected scope only
    unless ``strict_schema`` escalates it.
    """


class EdaraSchemaError(ValidationError):
    """Envelope / schema / data-contract violation.

    Maps to MISSING_REQUIRED_FIELD_MAPPING and malformed payloads. Per-scope:
    aborts the scope with no partial ingest.
    """


class EdaraProxyClient:
    """Stateless Edara proxy client. Construct with an Odoo ``env``."""

    def __init__(self, env):
        self.env = env
        Param = env['ir.config_parameter'].sudo()
        self.base_url = (Param.get_param('sl_monthly_bonus.edara_base_url') or '').rstrip('/')
        self._token = Param.get_param('sl_monthly_bonus.edara_token') or ''
        self.timeout = _safe_int(Param.get_param('sl_monthly_bonus.edara_timeout'), 30)
        self.retry_count = _safe_int(Param.get_param('sl_monthly_bonus.edara_retry_count'), 2)
        self.retry_backoff = _safe_float(Param.get_param('sl_monthly_bonus.edara_retry_backoff'), 1.5)
        self.page_size = _safe_int(Param.get_param('sl_monthly_bonus.edara_page_size'), 500)

    # ── low level ─────────────────────────────────────────────────────
    def _ensure_ready(self):
        if requests is None:
            raise UserError(_(
                "The Python 'requests' library is required for Edara integration "
                "but is not installed."
            ))
        if not self.base_url:
            raise EdaraConfigMissing(_(
                "Edara base URL is not configured. Set it under "
                "Bonus → Edara → Edara Settings."
            ))
        if not self._token:
            raise EdaraConfigMissing(_(
                "Edara API token is not configured. Set it under "
                "Bonus → Edara → Edara Settings."
            ))

    def _headers(self):
        # NOTE: never logged.
        return {
            'Authorization': 'Bearer %s' % self._token,
            'Accept': 'application/json',
            'X-Request-Id': uuid.uuid4().hex,
        }

    def _url(self, scope_or_path):
        path = ENDPOINTS.get(scope_or_path, scope_or_path)
        return '%s%s/%s' % (self.base_url, API_PREFIX, path)

    def _sleep(self, attempt):
        if self.retry_backoff and self.retry_backoff > 0:
            time.sleep(self.retry_backoff ** attempt)

    def _request(self, scope, params=None):
        """Perform a GET with bounded retries on transient failures only.

        Retries: connection/timeout errors and HTTP 502/503/504. Never retries
        4xx or 500. Raises a sanitized UserError on exhaustion.
        """
        self._ensure_ready()
        url = self._url(scope)
        headers = self._headers()
        attempts = max(1, self.retry_count + 1)
        for attempt in range(attempts):
            try:
                resp = requests.request(
                    'GET', url, headers=headers, params=params or {}, timeout=self.timeout,
                )
            except requests.exceptions.Timeout:
                _logger.warning("Edara request timeout (attempt %s/%s)", attempt + 1, attempts)
                if attempt < attempts - 1:
                    self._sleep(attempt)
                    continue
                raise UserError(_("Edara request timed out after %s attempt(s).") % attempts)
            except requests.exceptions.ConnectionError:
                _logger.warning("Edara connection error (attempt %s/%s)", attempt + 1, attempts)
                if attempt < attempts - 1:
                    self._sleep(attempt)
                    continue
                raise UserError(_("Could not connect to the Edara proxy after %s attempt(s).") % attempts)
            except Exception as exc:  # noqa: BLE001 - sanitize anything else
                # Deliberately do NOT echo the exception text (may carry the URL/token).
                raise UserError(_("Edara request failed (%s).") % type(exc).__name__)
            if resp.status_code in TRANSIENT_HTTP and attempt < attempts - 1:
                _logger.warning(
                    "Edara transient HTTP %s (attempt %s/%s)", resp.status_code, attempt + 1, attempts,
                )
                self._sleep(attempt)
                continue
            return resp
        # Unreachable, but keep static analyzers happy.
        raise UserError(_("Edara request failed."))

    @staticmethod
    def _safe_json(resp):
        try:
            return resp.json()
        except Exception:  # noqa: BLE001
            return None

    def _check_http(self, resp):
        code = resp.status_code
        if code in (401, 403):
            # Token is NEVER included in this message.
            raise UserError(_(
                "Edara authentication failed (HTTP %s). Verify the API token under "
                "Bonus → Edara → Edara Settings."
            ) % code)
        if code >= 400:
            payload = self._safe_json(resp)
            if isinstance(payload, dict) and payload.get('errors'):
                self._raise_for_errors(payload.get('errors'))
            raise UserError(_("Edara returned HTTP %s.") % code)

    def _raise_for_errors(self, errors):
        codes = [str(e.get('code') or '') for e in (errors or []) if isinstance(e, dict)]
        codes = [c for c in codes if c]
        first = codes[0] if codes else ''
        if first == 'CONFIGURATION_MISSING':
            raise EdaraConfigMissing(_(
                "Edara source configuration is missing (CONFIGURATION_MISSING)."
            ))
        if first == 'MISSING_REQUIRED_FIELD_MAPPING':
            raise EdaraSchemaError(_(
                "Edara is missing a required field mapping (MISSING_REQUIRED_FIELD_MAPPING)."
            ))
        if codes:
            raise UserError(_("Edara error: %s") % ', '.join(codes))
        raise UserError(_("Edara reported an unspecified error."))

    def _parse(self, resp, expected_data_type=None, require_list=True):
        """Validate an envelope. Returns a dict of useful fields."""
        self._check_http(resp)
        payload = self._safe_json(resp)
        if not isinstance(payload, dict):
            raise EdaraSchemaError(_("Edara returned a non-JSON or malformed response."))
        success = payload.get('success', True)
        if success is False:
            self._raise_for_errors(payload.get('errors') or [])
            raise UserError(_("Edara reported a failure with no error detail."))
        status = payload.get('status')
        warnings = payload.get('warnings') or []
        data = payload.get('data')
        if require_list:
            if 'data' not in payload:
                # e.g. legacy {"rows": [...]} shape — explicitly unsupported.
                raise EdaraSchemaError(_(
                    "Edara response is missing the 'data' array (unexpected envelope)."
                ))
            # status-discriminated empty responses may legitimately omit rows
            if data is None and status in ('unsupported', 'disabled'):
                data = []
            if not isinstance(data, list):
                raise EdaraSchemaError(_("Edara 'data' field is not a list."))
        return {
            'payload': payload,
            'data': data,
            'status': status,
            'warnings': warnings,
            'request_id': payload.get('request_id'),
            'pagination': payload.get('pagination') or {},
            'http_status': resp.status_code,
            'data_type': payload.get('data_type'),
        }

    # ── public API ────────────────────────────────────────────────────
    def health(self):
        """GET /health. Returns {ok, version, latency_ms, status, raw}."""
        t0 = time.time()
        resp = self._request('health')
        latency_ms = int((time.time() - t0) * 1000)
        self._check_http(resp)
        payload = self._safe_json(resp) or {}
        data = payload.get('data') if isinstance(payload.get('data'), dict) else {}
        version = payload.get('version') or data.get('version') or payload.get('proxy_version')
        status = payload.get('status')
        ok = bool(payload.get('success', True)) and status not in ('error', 'down')
        return {
            'ok': ok,
            'version': version,
            'latency_ms': latency_ms,
            'status': status,
            'raw': payload,
        }

    def schema(self):
        """GET /schema. Returns the parsed envelope payload (dict)."""
        resp = self._request('schema')
        parsed = self._parse(resp, require_list=False)
        return parsed['payload']

    def fetch(self, scope, params=None):
        """Fetch all pages for a scope. Returns a result dict.

        Result keys: rows, status, warnings, request_id, http_status, pages,
        data_type. Raises EdaraConfigMissing / EdaraSchemaError / UserError per
        the contract; the caller decides lenient-vs-strict handling.
        """
        params = dict(params or {})
        params.setdefault('page_size', self.page_size)
        rows, warnings = [], []
        status = request_id = http_status = data_type = None
        page, pages = 1, 0
        while True:
            params['page'] = page
            resp = self._request(scope, params=params)
            parsed = self._parse(resp, expected_data_type=scope, require_list=True)
            http_status = parsed['http_status']
            request_id = parsed['request_id'] or request_id
            data_type = parsed['data_type'] or data_type
            status = parsed['status'] or status
            if parsed['warnings']:
                warnings.extend(parsed['warnings'])
            page_rows = parsed['data'] or []
            rows.extend(page_rows)
            pages += 1
            if status in ('unsupported', 'disabled'):
                break
            if not page_rows:
                break
            pagination = parsed['pagination'] or {}
            total = pagination.get('total_count')
            psize = pagination.get('page_size') or params['page_size'] or len(page_rows)
            if total is not None and len(rows) >= total:
                break
            if psize and len(page_rows) < psize:
                break
            page += 1
            if page > 10000:  # absolute safety backstop
                _logger.warning("Edara fetch for %s exceeded 10000 pages; stopping.", scope)
                break
        return {
            'rows': rows,
            'status': status,
            'warnings': warnings,
            'request_id': request_id,
            'http_status': http_status,
            'pages': pages,
            'data_type': data_type,
        }


def _safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
