from __future__ import annotations

from chatserver.teaching import (
    unsafe_direct_db_write,
    unsafe_no_framing,
    unsafe_no_locks,
    unsafe_no_shutdown,
    unsafe_slow_client,
)


def test_unsafe_framing_actually_breaks_then_decoder_recovers() -> None:
    result = unsafe_no_framing.demonstrate()
    assert result["naive_error"] is not None
    assert "JSON" in result["naive_error"]
    # The safe decoder recovers both frames that the naive parser could not.
    assert result["safe_frames"] == ['{"type":"hello","nick":"ada"}', '{"type":"rooms"}']


def test_unsafe_no_locks_corrupts_shared_iteration() -> None:
    result = unsafe_no_locks.demonstrate()
    assert result["naive_iteration_error"] is not None
    assert "changed size" in result["naive_iteration_error"].lower()
    assert result["safe_iteration_error"] is None


def test_unsafe_slow_client_blocking_broadcast_stalls() -> None:
    result = unsafe_slow_client.demonstrate()
    assert result["naive_broadcast_stalled_at_message"] is not None
    assert result["safe_queue_overflow_signalled"] is True


def test_unsafe_direct_db_write_blocks_handler_vs_queue() -> None:
    result = unsafe_direct_db_write.demonstrate()
    assert result["direct_writes_blocking_handler"] == 5
    assert result["queued_writes_completed_by_worker"] == 5


def test_unsafe_no_shutdown_leaks_thread() -> None:
    result = unsafe_no_shutdown.demonstrate()
    assert result["leaked_thread_alive_after_shutdown"] is True
    assert result["safe_thread_alive_after_shutdown"] is False


def test_unsafe_examples_render_human_readable_strings() -> None:
    for module in (
        unsafe_no_framing,
        unsafe_no_locks,
        unsafe_slow_client,
        unsafe_direct_db_write,
        unsafe_no_shutdown,
    ):
        text = module.unsafe_example()
        assert isinstance(text, str)
        assert len(text) > 40
