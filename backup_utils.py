"""Safe metadata-only backups for PostDrive.

Session strings, API hashes, proxy credentials and other authentication
material are intentionally excluded.  This module is usable without an
optional crypto package and therefore cannot accidentally create a misleading
"encrypted" backup.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import zipfile
from typing import Any, Dict


_ACCOUNT_FIELDS = (
    'id', 'user_id', 'phone', 'account_name', 'status', 'health',
    'health_reason', 'restricted_until', 'flood_count',
    'flood_total_seconds', 'last_flood_at', 'last_health_check_at',
    'last_success_at', 'last_error_at', 'last_error',
    'operation_success_count', 'operation_error_count', 'created_at',
)


def _safe_account(account: Dict[str, Any]) -> Dict[str, Any]:
    result = {field: account.get(field) for field in _ACCOUNT_FIELDS}
    result['has_proxy'] = bool((account.get('proxy') or '').strip())
    result['has_session'] = bool((account.get('session_string') or '').strip())
    result['has_api_credentials'] = bool(
        account.get('api_id') and (account.get('api_hash') or '').strip()
    )
    return result


def create_safe_backup(db, user_id: int, output_dir: str | None = None):
    """Create a ZIP containing only user-owned non-secret metadata.

    Returns ``(path, sha256, size_bytes)``.  The caller owns the returned file
    and may remove it after sending it to the user.
    """
    accounts = [_safe_account(row) for row in db.get_user_accounts(int(user_id))]
    reports = db.get_user_operation_reports(int(user_id), limit=10000)
    blacklist, _pages = db.get_blacklist_page(int(user_id), page=0, per_page=10000)
    drafts = db.get_campaign_drafts(int(user_id), limit=10000)
    audit, _audit_pages = db.get_audit_log(int(user_id), page=0, per_page=10000)

    manifest = {
        'format': 'postdrive-safe-metadata-v1',
        'created_at': int(time.time()),
        'user_id': int(user_id),
        'includes_sessions': False,
        'includes_api_credentials': False,
        'includes_proxy_credentials': False,
    }
    payloads = {
        'manifest.json': manifest,
        'accounts.json': accounts,
        'operation_reports.json': reports,
        'blacklist.json': blacklist,
        'campaign_drafts.json': drafts,
        'audit_log.json': audit,
    }
    output_dir = output_dir or tempfile.gettempdir()
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f'postdrive-safe-backup-{user_id}-{int(time.time())}.zip')
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in payloads.items():
            archive.writestr(
                name,
                json.dumps(data, ensure_ascii=False, indent=2, default=str),
            )
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return path, digest.hexdigest(), os.path.getsize(path)
