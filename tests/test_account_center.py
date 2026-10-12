"""Source and database checks for the account health/productivity modules."""
import ast
import json
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqliter import DBConnection
from backup_utils import create_safe_backup

ROOT = os.path.join(os.path.dirname(__file__), '..')
H = open(os.path.join(ROOT, 'handlers.py'), encoding='utf-8').read()
U = open(os.path.join(ROOT, 'user.py'), encoding='utf-8').read()
S = open(os.path.join(ROOT, 'sqliter.py'), encoding='utf-8').read()

assert 'account_health_center' in H
assert 'health_check_all' in H
assert 'mass_import_continue' in H
assert 'import_preview' in H
assert 'blacklist_menu' in H
assert 'save_spam_draft' in H
assert 'spam_preview' in H
assert 'operation_history' in H
assert 'backup_create' in H
assert 'SESSION_ENCRYPTION_KEY' in S
assert '_protect_session(session_string)' in S
assert 'filter_blacklisted_targets' in U
assert "source='optout'" in U

ast.parse(H)
ast.parse(U)
ast.parse(S)

fd, path = tempfile.mkstemp(prefix='postdrive-health-', suffix='.db')
os.close(fd)
try:
    db = DBConnection(path, pool_size=2)
    db.get_or_create_user(123, 'tester', 'Test', '', 999)
    account_id = db.add_account(123, 'session-secret', phone='+100', account_name='Test account')
    assert db.get_account(account_id)['session_string'] == 'session-secret'

    entry_id = db.add_blacklist_entry(123, '@Example', 'opt-out', source='optout')
    assert entry_id and db.is_blacklisted(123, 'example')
    allowed, blocked = db.filter_blacklisted_targets(123, ['@example', '@other'])
    assert allowed == ['@other'] and blocked == ['@example']

    draft_id = db.create_campaign_draft(123, 'Morning', settings={'spam_speed': 'slow'})
    assert db.get_campaign_draft(draft_id, 123)['settings']['spam_speed'] == 'slow'
    audit_id = db.write_audit(123, 'test', 'draft', draft_id, {'ok': True})
    assert audit_id

    run_id = db.create_import_run(123, 'accounts.zip', total=1, valid_count=1)
    db.add_import_run_item(run_id, 'a.session', 'session')
    assert db.get_import_run(run_id, 123)['status'] == 'preview'

    db.record_account_health_check(account_id, 123, 'session', 'ok', 'ok', 12)
    center = db.get_user_health_center(123)
    assert center[0]['last_health_check']['status'] == 'ok'

    backup_path, digest, size = create_safe_backup(db, 123, tempfile.gettempdir())
    assert digest and size > 0
    with zipfile.ZipFile(backup_path) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read('manifest.json'))
        assert 'accounts.json' in names
        assert manifest['includes_sessions'] is False
        assert b'session-secret' not in archive.read('accounts.json')
    os.remove(backup_path)
finally:
    try:
        os.remove(path)
    except OSError:
        pass

print('ACCOUNT CENTER TESTS PASSED')
