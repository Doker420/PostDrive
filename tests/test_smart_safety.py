"""Regression checks for persistent autopost limits and warmup safety paths."""
import ast
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import sqliter


def test_persistent_autopost_limits_and_warmup_state():
    path = tempfile.mktemp(suffix=".db")
    db = sqliter.DBConnection(path)
    try:
        db.get_or_create_user(42)
        account_id = db.add_account(42, "session", account_name="test")
        db.update_account_postbot(account_id, "63ff0f7189df5")
        assert db.get_account(account_id)["postbot_post_id"] == "63ff0f7189df5"
        db.set_account_health(account_id, db.HEALTH_RESTRICTED, "UserBannedInChannel: target only")
        assert db.clear_false_channel_bans() == 1
        assert db.get_account_health(account_id)["health"] == db.HEALTH_OK
        db.set_account_health(account_id, db.HEALTH_RESTRICTED, "PeerFlood: аккаунт ограничен Telegram за спам")
        assert db.move_legacy_peerflood_to_cooldown() == 1
        assert db.get_account_health(account_id)["health"] == db.HEALTH_COOLDOWN
        db.configure_autopost_limits(
            account_id, min_delay_seconds=30, max_delay_seconds=60,
            hourly_limit=2, daily_limit=3
        )

        start = (1_700_000_000 // 86400) * 86400 + 100
        assert db.reserve_autopost_slot(account_id, start) == (True, 0, "ok")
        assert db.reserve_autopost_slot(account_id, start + 30) == (True, 0, "ok")
        allowed, wait, reason = db.reserve_autopost_slot(account_id, start + 60)
        assert not allowed and reason == "hourly_limit" and wait > 0

        # The next hour has a fresh hourly bucket, but the daily counter remains.
        assert db.reserve_autopost_slot(account_id, start + 3600) == (True, 0, "ok")
        allowed, _wait, reason = db.reserve_autopost_slot(account_id, start + 7200)
        assert not allowed and reason == "daily_limit"

        state = db.start_account_warmup(account_id, 42, 1)
        assert state["status"] == "running"
        assert state["duration_minutes"] == 15  # lower bound is intentional
        db.update_account_warmup_action(account_id, "subscribe", start + 100)
        db.update_account_warmup_action(account_id, "other", start + 200, "no public channel")
        state = db.get_account_warmup(account_id)
        assert state["action_count"] == 1
        assert state["subscriptions_count"] == 1
        assert state["error_count"] == 1
        db.finish_account_warmup(account_id, "stopped")
        assert db.get_account_warmup(account_id)["status"] == "stopped"
    finally:
        db.close()
        pathlib.Path(path).unlink(missing_ok=True)


def test_user_safety_guards_are_present():
    source = pathlib.Path("user.py").read_text(encoding="utf-8")
    assert "def _is_internal_noise_error" in source
    assert "def _safe_payload_text" in source
    assert "TELEGRAM_CALL_TIMEOUT" in source
    assert "stop_on_flood: bool = False" in source
    assert "await asyncio.wait_for(factory(), timeout=TELEGRAM_CALL_TIMEOUT)" in source
    assert "asyncio.wait_for(collect_one(), timeout=30)" in source
    assert "warmup reaction" in source
    assert "async def send_via_postbot" in source
    assert "get_inline_bot_results(POSTBOT_USERNAME, post_id)" in source
    assert "send_inline_bot_result(target, query_id, result_id)" in source
    assert "client.search_global(query=query, limit=50)" in source
    assert "chat = getattr(message, 'chat', None)" in source
    assert "successful_actions = subscriptions + reactions" in source
    assert "SPAMBLOCK_ERRORS = tuple({PeerFlood}" in source
    assert "UserBannedInChannel, UserAlreadyParticipant" in source
    assert "record_flood_wait(account_id, cooldown)" in source
    assert "create_operation_report" in source
    assert "start_invite_job" in source
    assert "check_account_proxy" in source
    assert "SKIP_TARGET_ERROR_NAMES" in source
    assert "async def _invite_from_shared_queue" in source
    assert "work_queue.get_nowait()" in source
    assert "'privacy': 0" in source
    assert "'already_member': 0" in source
    assert "raise_on_skip=True" in source
    assert "privacy premium required" in source
    assert "minimum_delay is a pacing rule" in source
    assert "while not slot_ok and slot_reason == 'minimum_delay'" in source
    assert "mode in ('prompt', 'post_prompt', 'auto')" in source

    # The API pool parser accepts large line-oriented files, skips malformed
    # rows and preserves the first occurrence of duplicate credentials.
    tree = ast.parse(source)
    parser_node = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "parse_api_hash_lines"
    )
    parser_ns = {}
    exec(compile(ast.Module(body=[parser_node], type_ignores=[]), "user.py", "exec"), parser_ns)
    parse_api_hash_lines = parser_ns["parse_api_hash_lines"]
    assert parse_api_hash_lines([
        "123:abc", "123:abc", "bad", "456:def # comment", "0:nope", "789:ghi"
    ]) == [(123, "abc"), (456, "def"), (789, "ghi")]

    # Regression: the Russian healthy reply contains the word SpamBot, so it
    # must not be classified as a restriction merely because of "spam".
    classifier_node = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_classify_spambot_response"
    )
    classifier_ns = {}
    exec(compile(ast.Module(body=[classifier_node], type_ignores=[]), "user.py", "exec"), classifier_ns)
    classify = classifier_ns["_classify_spambot_response"]
    assert classify("SpamBot: Ваш аккаунт свободен от каких-либо ограничений.") is True
    assert classify("SpamBot: Your account is limited until tomorrow.") is False
    assert classify("SpamBot: непонятный новый ответ") is None

    handlers = pathlib.Path("handlers.py").read_text(encoding="utf-8")
    assert "📮 Через @PostBot" in handlers
    assert "set_postbot_" in handlers
    assert "MassActionStates.WAITING_POSTBOT_ID" in handlers
    assert "nc_mode_auto_" in handlers
    assert "Автоматически по посту" in handlers
    assert "общей очереди" in handlers
    assert "operation_stop_" in handlers
    assert "operation_download_" in handlers
    assert "acc_proxy_check_" in handlers
    assert "auth_pyrogram_file" in handlers
    assert "WAITING_SESSION_FILE" in handlers
    assert "WAITING_SESSION_JSON" in handlers
    assert "import_pyrogram_session_files" in source
    assert "auth_mass_upload" in handlers
    assert "WAITING_MASS_ARCHIVE" in handlers
    assert "WAITING_MASS_PROXY_LIST" in handlers
    assert "_safe_extract_mass_zip" in handlers
    assert "_mass_archive_unrecognized" in handlers
    assert "максимум к 5 аккаунтам" in handlers
    assert "find_duplicate_account" in handlers
    assert "get_tdata_account_count" in source
    assert "_build_tdata_pyrogram_client" in source
    assert "supported = signature(Client.__init__).parameters" in source
    assert "import_tdata_session" in source
    assert "'proxy': parse_proxy_string(proxy_str)" in source
    assert "check_proxy_endpoint" in source
    assert "async def check_spam_block" in source
    assert "def parse_api_hash_lines" in source
    assert "api_hashes_file" in source
    assert "bind_all_account_apis" in source
    assert "def _classify_spambot_response" in source
    assert "свободен от каких-либо ограничений" in source
    assert "status = _classify_spambot_response(response)" in source
    assert "'spam', 'can\\'t send'" not in source
    assert "allow_restricted=True" in source
    assert "acc_spambot_check_" in handlers
    assert "🛡 Проверить спамблок" in handlers

    sqliter_source = pathlib.Path("sqliter.py").read_text(encoding="utf-8")
    assert "api_id INTEGER DEFAULT 0" in sqliter_source
    assert "def update_account_api" in sqliter_source
    assert "def get_assigned_api_credentials" in sqliter_source

    # Account selection menus must stay bounded even when a user has many
    # accounts. The selected IDs are kept in FSM data while only one page is
    # rendered, so moving between pages must not clear the selection.
    assert "ACCOUNT_PAGE_SIZE = 8" in handlers
    assert "def _account_page" in handlers
    assert "accounts_page_" in handlers
    assert "mass_account_page_" in handlers
    assert "selected_accounts=selected" in handlers
    assert "nc_page_" in handlers
    assert "join_pack_page_" in handlers
    assert "await render_accounts_screen(message, user_id, page=0)" in handlers
    assert "accounts_goto_page_" in handlers
    assert "mass_account_goto_" in handlers
    assert "nc_goto_page_" in handlers
    assert "join_pack_goto_page_" in handlers
    assert "account_manager.bind_account_api(account_id)" in handlers
    assert "check_all_proxies" in handlers
    assert "mass_change_bio" in handlers
    assert "MassActionStates.WAITING_BIO" in handlers
    assert "mass_join_link" in handlers
    assert "MassActionStates.WAITING_JOIN_LINKS" in handlers
    assert "mass_spambot_check" in handlers
    assert "mass_select_all_" in handlers
    assert "_run_mass_spambot_check" in handlers
    assert "nc_select_all" in handlers
    assert "nc_start_selected" in handlers
    assert "PAGE_DIGITS" in handlers
    assert "1️⃣" in handlers
    assert "spam_mode_forward" in handlers
    assert "client.forward_messages" in source
    assert "toggle_invite_auto_join" in handlers
    assert "await account_manager.stop_account_warmup(account_id, user_id)" in handlers

    transport = pathlib.Path("telegram_transport.py").read_text(encoding="utf-8")
    assert "MESSAGE_TOO_LONG" in transport
    assert "_split_text" in transport
    assert "_utf16_units" in transport
    assert "_CAPTION_SAFE_LIMIT" in transport
    mirrors = pathlib.Path("mirrors.py").read_text(encoding="utf-8")
    assert "ResilientAiohttpSession" in mirrors


if __name__ == "__main__":
    test_persistent_autopost_limits_and_warmup_state()
    test_user_safety_guards_are_present()
    print("SMART SAFETY TESTS PASSED")
