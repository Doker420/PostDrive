"""Regression checks for persistent autopost limits and warmup safety paths."""
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
    assert "mode in ('prompt', 'post_prompt', 'auto')" in source

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


if __name__ == "__main__":
    test_persistent_autopost_limits_and_warmup_state()
    test_user_safety_guards_are_present()
    print("SMART SAFETY TESTS PASSED")
