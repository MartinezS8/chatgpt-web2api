"""Bounded local JSONL harness for a synthetic Codex app-server peer only.

The fixed child module is bundled with this package. This API cannot launch an
arbitrary executable or a real Codex process and provides no live-send or task
finalization authority. Unknown responses quarantine the attempt in memory.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .app_server_contract import OfflineAppServerContract, ProtocolRejected

_LOG = logging.getLogger(__name__)
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_EOF = object()
_MAX_MODEL_CHARS = 256
_MAX_EFFORT_CHARS = 32


class UnknownDelivery(RuntimeError):
    """A request was attempted but no unambiguous response was received."""


class _FrameTooLarge(ProtocolRejected):
    """An outbound JSONL frame was rejected before any bytes were written."""


class FakeAppServerScenario(StrEnum):
    """Fixed synthetic peer behaviors used by offline integration tests."""

    SUCCESS = "success"
    MALFORMED_JSON = "malformed_json"
    TRUNCATED_JSONL = "truncated_jsonl"
    DUPLICATE_JSON_KEYS = "duplicate_json_keys"
    OVERSIZED_OUTPUT = "oversized_output"
    WRONG_REQUEST_ID = "wrong_request_id"
    APPROVAL_REQUEST = "approval_request"
    FOREIGN_THREAD = "foreign_thread"
    FOREIGN_TURN = "foreign_turn"
    FOREIGN_TURN_AFTER_ACK = "foreign_turn_after_ack"
    DUPLICATE_TERMINAL = "duplicate_terminal"
    BROKEN_PIPE_BEFORE_TURN = "broken_pipe_before_turn"
    DIE_AFTER_TURN_REQUEST = "die_after_turn_request"
    TIMEOUT_AFTER_TURN_REQUEST = "timeout_after_turn_request"
    INTERRUPTED = "interrupted"
    ECHO_PROMPT = "echo_prompt"
    MODEL_MISMATCH = "model_mismatch"
    OUTPUT_FLOOD = "output_flood"


@dataclass(frozen=True, slots=True)
class AttemptBinding:
    """Immutable controller/worker/task association for one offline attempt."""

    controller_id: str
    worker_id: str
    account_id: str
    project_id: str
    task_id: str
    attempt_id: str

    def __post_init__(self) -> None:
        for name in (
            "controller_id", "worker_id", "account_id", "project_id", "task_id", "attempt_id"
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not _ID.fullmatch(value):
                raise ValueError(f"invalid offline attempt {name}")


def _pairs_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _message_sha256(message: dict[str, Any]) -> str:
    """Hash bounded protocol data without retaining or logging its contents."""
    encoded = json.dumps(
        message, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _json_string_encoded_size(value: str, *, limit: int) -> int | None:
    """Return exact ensure_ascii=False JSON string bytes, stopping over limit."""
    size = 2  # Opening and closing quote.
    short_escapes = {'"', "\\", "\b", "\f", "\n", "\r", "\t"}
    for character in value:
        codepoint = ord(character)
        if character in short_escapes:
            size += 2
        elif codepoint < 0x20:
            size += 6  # \u00xx
        elif 0xD800 <= codepoint <= 0xDFFF:
            raise ProtocolRejected("synthetic prompt contains invalid Unicode")
        else:
            size += len(character.encode("utf-8"))
        if size > limit:
            return None
    return size


def _require_jsonl_string_fits(
    probe_request: dict[str, Any],
    value: str,
    *,
    max_frame_bytes: int,
) -> None:
    """Reject a large request string before serializing its full contents."""
    probe_frame = json.dumps(
        probe_request, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8") + b"\n"
    value_size = _json_string_encoded_size(value, limit=max_frame_bytes)
    if value_size is None or len(probe_frame) - 3 + value_size > max_frame_bytes:
        raise _FrameTooLarge("outbound JSONL frame exceeds limit")


class _FakeJsonlProcess:
    """One fixed fake child, one outstanding request, bounded stdout queue."""

    def __init__(
        self,
        scenario: FakeAppServerScenario,
        *,
        max_frame_bytes: int,
        max_queued_messages: int,
    ) -> None:
        self._scenario = scenario
        self._max_frame_bytes = max_frame_bytes
        self._lines: queue.Queue[bytes | object] = queue.Queue(maxsize=max_queued_messages)
        self._fatal = threading.Event()
        self._fatal_message = "app-server output exceeded a transport limit"
        self._write_lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None
        self._reader: threading.Thread | None = None
        self._stdin_closed = False
        self._unknown = False
        self._request_counts: dict[str, int] = {}
        self._notification_counts: dict[str, int] = {}
        self.shutdown_mode: str | None = None
        self.exit_code: int | None = None

    @staticmethod
    def _child_environment() -> dict[str, str]:
        temp_path = tempfile.gettempdir()
        env = {"TEMP": temp_path, "TMP": temp_path}
        for key in ("SYSTEMROOT", "WINDIR"):
            value = os.environ.get(key)
            if value:
                env[key] = value
        return env

    def start(self) -> None:
        if self._process is not None:
            raise RuntimeError("offline fake process was already started")
        module_name = f"{__package__}._fake_app_server"
        command = [sys.executable, "-I", "-m", module_name,
                   "--scenario", self._scenario.value]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=tempfile.gettempdir(),
                env=self._child_environment(),
                close_fds=True,
                creationflags=creationflags,
                bufsize=-1,
            )
        except OSError:
            raise ProtocolRejected("offline fake process could not be started") from None
        self._reader = threading.Thread(
            target=self._read_stdout, name="w2a-offline-app-server-reader", daemon=True
        )
        self._reader.start()

    def _set_fatal(self, message: str) -> None:
        self._fatal_message = message
        self._fatal.set()

    def _read_stdout(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        try:
            while True:
                line = self._process.stdout.readline(self._max_frame_bytes + 1)
                if not line:
                    break
                if len(line) > self._max_frame_bytes:
                    self._set_fatal("app-server output frame exceeded the byte limit")
                    return
                if not line.endswith(b"\n"):
                    self._set_fatal("app-server emitted an unterminated JSONL frame")
                    return
                try:
                    self._lines.put_nowait(line)
                except queue.Full:
                    self._set_fatal("app-server output queue exceeded its message limit")
                    return
        except OSError:
            self._set_fatal("app-server output pipe failed")
        finally:
            try:
                self._lines.put_nowait(_EOF)
            except queue.Full:
                self._set_fatal("app-server output queue exceeded its message limit")

    def _next_raw(self, deadline: float) -> bytes | object:
        while True:
            if self._fatal.is_set():
                self._unknown = True
                raise UnknownDelivery(self._fatal_message)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._unknown = True
                raise UnknownDelivery("app-server response timed out")
            try:
                return self._lines.get(timeout=min(0.05, remaining))
            except queue.Empty:
                process = self._process
                reader = self._reader
                if (process is not None and process.poll() is not None
                        and reader is not None and not reader.is_alive() and self._lines.empty()):
                    return _EOF

    @staticmethod
    def _decode(line: bytes) -> dict[str, Any]:
        try:
            message = json.loads(
                line[:-1].decode("utf-8"),
                object_pairs_hook=_pairs_without_duplicates,
                parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            )
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
            raise UnknownDelivery("app-server emitted malformed JSONL") from None
        if not isinstance(message, dict):
            raise UnknownDelivery("app-server emitted a non-object JSONL message")
        return message

    def _write(self, message: dict[str, Any], *, request: bool) -> None:
        process = self._process
        if process is None or process.stdin is None or self._stdin_closed:
            self._unknown = True
            raise UnknownDelivery("app-server stdin is unavailable")
        if self._unknown:
            raise UnknownDelivery("attempt is already quarantined")
        try:
            frame = json.dumps(
                message, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode("utf-8") + b"\n"
        except (TypeError, UnicodeEncodeError, ValueError):
            raise ProtocolRejected("outbound JSONL message is invalid") from None
        if len(frame) > self._max_frame_bytes:
            raise _FrameTooLarge("outbound JSONL frame exceeds limit")
        method = message.get("method")
        if not isinstance(method, str) or not method:
            raise ProtocolRejected("outbound JSONL method is invalid")
        with self._write_lock:
            if request:
                self._request_counts[method] = self._request_counts.get(method, 0) + 1
            else:
                self._notification_counts[method] = self._notification_counts.get(method, 0) + 1
            try:
                assert process.stdin is not None
                process.stdin.write(frame)
                process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                self._unknown = True
                raise UnknownDelivery("app-server stdin failed after a request attempt") from None

    def request(
        self,
        message: dict[str, Any],
        *,
        on_notification: Callable[[dict[str, Any]], Any],
        on_written: Callable[[], Any] | None = None,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        # The caller drives requests serially and does not issue the next one
        # until the previous response has been consumed.  Historical request
        # counts are intentionally retained for the no-retry assertions; they
        # must not be mistaken for an in-flight request.
        request_id = message.get("id")
        if type(request_id) is not int:
            raise ProtocolRejected("outbound request id must be an integer")
        self._write(message, request=True)
        if on_written is not None:
            on_written()
        deadline = time.monotonic() + timeout_seconds
        while True:
            raw = self._next_raw(deadline)
            if raw is _EOF:
                self._unknown = True
                raise UnknownDelivery("app-server exited before acknowledging a request")
            response = self._decode(raw)
            if isinstance(response.get("method"), str):
                # JSON-RPC notifications may be interleaved with responses,
                # including turn/started before turn/start is acknowledged.
                # Server-initiated requests carry an id and are never answered.
                if "id" in response:
                    self._unknown = True
                    on_notification(response)
                    raise ProtocolRejected("server-initiated request was rejected")
                on_notification(response)
                continue
            if type(response.get("id")) is not int or response["id"] != request_id:
                self._unknown = True
                raise UnknownDelivery("app-server response id did not match the request")
            if "error" in response or not isinstance(response.get("result"), dict):
                self._unknown = True
                raise UnknownDelivery("app-server request was rejected or omitted its result")
            return response

    def notify(self, message: dict[str, Any], *, on_written: Callable[[], Any] | None = None) -> None:
        if "id" in message:
            raise ProtocolRejected("client notification must not contain a request id")
        self._write(message, request=False)
        if on_written is not None:
            on_written()

    def read_notification(
        self,
        *,
        on_notification: Callable[[dict[str, Any]], Any],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        raw = self._next_raw(time.monotonic() + timeout_seconds)
        if raw is _EOF:
            self._unknown = True
            raise UnknownDelivery("app-server exited before a terminal turn event")
        message = self._decode(raw)
        if isinstance(message.get("method"), str):
            on_notification(message)
            return message
        self._unknown = True
        raise UnknownDelivery("unexpected app-server response without a pending request")

    def finish(
        self,
        *,
        on_notification: Callable[[dict[str, Any]], Any],
        timeout_seconds: float,
    ) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise ProtocolRejected("offline fake process is unavailable at shutdown")
        if not self._stdin_closed:
            try:
                process.stdin.close()
            except OSError:
                self._unknown = True
                raise UnknownDelivery("app-server stdin failed during shutdown") from None
            self._stdin_closed = True
            self.shutdown_mode = "stdin_eof"
        deadline = time.monotonic() + timeout_seconds
        while True:
            raw = self._next_raw(deadline)
            if raw is _EOF:
                break
            message = self._decode(raw)
            if not isinstance(message.get("method"), str):
                raise ProtocolRejected("unexpected message during app-server shutdown")
            on_notification(message)
        try:
            self.exit_code = process.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            self._unknown = True
            raise UnknownDelivery("offline fake process did not exit after stdin EOF") from None
        if self.exit_code != 0:
            raise ProtocolRejected("offline fake process exited unsuccessfully")

    def close(self, *, graceful: bool) -> int | None:
        process = self._process
        if process is None:
            return self.exit_code
        if not self._stdin_closed and process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
            self._stdin_closed = True
            if graceful:
                self.shutdown_mode = "stdin_eof"
        if process.poll() is None and not graceful:
            process.terminate()
            self.shutdown_mode = "forced_terminate"
        try:
            self.exit_code = process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            process.kill()
            self.shutdown_mode = "forced_kill"
            self.exit_code = process.wait(timeout=0.5)
        if self._reader is not None:
            self._reader.join(timeout=0.5)
        for pipe in (process.stdout, process.stdin):
            if pipe is not None and not pipe.closed:
                pipe.close()
        return self.exit_code

    def request_count(self, method: str) -> int:
        return self._request_counts.get(method, 0)

    def notification_count(self, method: str) -> int:
        return self._notification_counts.get(method, 0)


class OfflineFakeAppServer:
    """One bounded JSONL attempt against the bundled synthetic fake process."""

    __slots__ = (
        "_binding", "_scenario", "_model", "_effort", "_timeout_seconds",
        "_max_frame_bytes", "_max_queued_messages", "_run_started", "_run_guard",
        "_transport",
        "_delivery_status", "_process_exit_code", "_shutdown_mode",
    )

    def __init__(
        self,
        binding: AttemptBinding,
        *,
        scenario: FakeAppServerScenario = FakeAppServerScenario.SUCCESS,
        model: str = "offline-fake-model-0.157",
        effort: str = "medium",
        timeout_seconds: float = 2.0,
        max_frame_bytes: int = 65_536,
        max_queued_messages: int = 16,
    ) -> None:
        if not isinstance(binding, AttemptBinding):
            raise TypeError("an immutable offline AttemptBinding is required")
        if not isinstance(scenario, FakeAppServerScenario):
            raise TypeError("scenario must be an enumerated fake-only behavior")
        if (not isinstance(model, str) or not model or model.isspace()
                or len(model) > _MAX_MODEL_CHARS
                or not isinstance(effort, str) or not effort or effort.isspace()
                or len(effort) > _MAX_EFFORT_CHARS):
            raise ValueError("exact synthetic model and effort are required")
        try:
            # Check strict UTF-8 while the values are bounded above; these
            # fixed protocol fields are included in every serialized request.
            if (len(model.encode("utf-8", errors="strict")) > _MAX_MODEL_CHARS * 4
                    or len(effort.encode("utf-8", errors="strict")) > _MAX_EFFORT_CHARS * 4):
                raise ValueError("exact synthetic model and effort are required")
        except UnicodeEncodeError:
            raise ValueError("exact synthetic model and effort are required") from None
        if (type(timeout_seconds) not in {int, float}
                or not math.isfinite(timeout_seconds)
                or not 0 < timeout_seconds <= 60
                or type(max_frame_bytes) is not int
                or not 128 <= max_frame_bytes <= 65_536
                or type(max_queued_messages) is not int
                or not 1 <= max_queued_messages <= 64):
            raise ValueError("invalid bounded fake transport settings")
        self._binding = binding
        self._scenario = scenario
        self._model = model
        self._effort = effort
        self._timeout_seconds = timeout_seconds
        self._max_frame_bytes = max_frame_bytes
        self._max_queued_messages = max_queued_messages
        self._run_started = False
        self._run_guard = threading.Lock()
        self._transport: _FakeJsonlProcess | None = None
        self._delivery_status = "not_started"
        self._process_exit_code: int | None = None
        self._shutdown_mode: str | None = None

    @property
    def binding(self) -> AttemptBinding:
        return self._binding

    @property
    def live_send_permitted(self) -> bool:
        return False

    @property
    def delivery_status(self) -> str:
        return self._delivery_status

    @property
    def process_exit_code(self) -> int | None:
        return self._process_exit_code

    @property
    def shutdown_mode(self) -> str | None:
        return self._shutdown_mode

    def request_count(self, method: str) -> int:
        return self._transport.request_count(method) if self._transport is not None else 0

    def notification_count(self, method: str) -> int:
        return (self._transport.notification_count(method)
                if self._transport is not None else 0)

    def run(self, *, prompt: str, cwd: str) -> dict[str, Any]:
        if not self._run_guard.acquire(blocking=False):
            raise ProtocolRejected("offline fake attempt is already running")
        try:
            return self._run_once(prompt=prompt, cwd=cwd)
        finally:
            self._run_guard.release()

    def _run_with_journal(self, *, prompt: str, cwd: str, journal) -> dict[str, Any]:
        """Private hook used only by the durable offline-fake coordinator."""
        from .app_server_delivery import AppServerDeliveryLedger

        if type(journal) is not AppServerDeliveryLedger:
            raise TypeError("offline fake journal must be the canonical app-server ledger")
        if not self._run_guard.acquire(blocking=False):
            raise ProtocolRejected("offline fake attempt is already running")
        try:
            return self._run_once(prompt=prompt, cwd=cwd, journal=journal)
        finally:
            self._run_guard.release()

    def _run_once(self, *, prompt: str, cwd: str, journal=None) -> dict[str, Any]:
        if self._run_started:
            if self._delivery_status == "unknown_delivery":
                raise UnknownDelivery("attempt is already quarantined; no retry is allowed")
            raise ProtocolRejected("offline fake attempt can run only once")
        self._run_started = True
        if not isinstance(prompt, str) or not isinstance(cwd, str):
            self._delivery_status = "not_sent"
            raise ProtocolRejected("synthetic prompt and explicit working directory are required")
        binding = self._binding
        model = self._model
        effort = self._effort
        scenario = self._scenario
        timeout_seconds = self._timeout_seconds
        max_frame_bytes = self._max_frame_bytes
        max_queued_messages = self._max_queued_messages
        try:
            for value in (prompt, cwd):
                if _json_string_encoded_size(value, limit=max_frame_bytes) is None:
                    raise _FrameTooLarge("outbound JSONL frame exceeds limit")
            if not prompt or prompt.isspace() or not cwd or cwd.isspace():
                raise ProtocolRejected(
                    "synthetic prompt and explicit working directory are required"
                )
        except ProtocolRejected:
            self._delivery_status = "not_sent"
            raise
        self._delivery_status = "running_offline_fake"
        contract = OfflineAppServerContract(model, effort)
        transport = _FakeJsonlProcess(
            scenario,
            max_frame_bytes=max_frame_bytes,
            max_queued_messages=max_queued_messages,
        )
        self._transport = transport
        try:
            transport.start()

            def receive_notification(message: dict[str, Any]) -> Any:
                state = contract.receive_event(message)
                if journal is not None:
                    method = message.get("method")
                    if method in {"turn/started", "turn/completed"}:
                        journal._capture_notification(
                            binding.attempt_id,
                            method=method,
                            thread_id=contract.thread_id,
                            turn_id=contract.turn_id or contract.early_turn_id,
                        )
                return state

            def exchange(request: dict[str, Any]) -> None:
                message_seq = None
                if journal is not None:
                    message_seq = journal._message_intent(
                        binding.attempt_id,
                        message_kind="request",
                        request_id=request["id"],
                        method=request["method"],
                        message_sha256=_message_sha256(request),
                    )
                response = transport.request(
                    request,
                    on_notification=receive_notification,
                    on_written=(
                        lambda: journal._message_written(binding.attempt_id, message_seq)
                        if journal is not None else None
                    ),
                    timeout_seconds=timeout_seconds,
                )
                contract.receive_response(response)
                if journal is not None:
                    journal._message_acknowledged(
                        binding.attempt_id,
                        message_seq,
                        response_sha256=_message_sha256(response),
                        thread_id=contract.thread_id,
                        turn_id=contract.turn_id or contract.early_turn_id,
                    )

            exchange(contract.initialize())
            initialized = contract.initialized()
            initialized_seq = None
            if journal is not None:
                initialized_seq = journal._message_intent(
                    binding.attempt_id,
                    message_kind="notification",
                    request_id=None,
                    method=initialized["method"],
                    message_sha256=_message_sha256(initialized),
                )
            transport.notify(
                initialized,
                on_written=(
                    lambda: journal._message_written(binding.attempt_id, initialized_seq)
                    if journal is not None else None
                ),
            )
            exchange(contract.model_list())
            thread_request = contract.thread_start(cwd=cwd)
            thread_params = thread_request["params"]
            thread_probe = {
                **thread_request,
                "params": {**thread_params, "cwd": "x"},
            }
            _require_jsonl_string_fits(
                thread_probe, cwd, max_frame_bytes=max_frame_bytes
            )
            exchange(thread_request)
            turn_request = contract.turn_start(prompt)
            turn_params = turn_request["params"]
            text_item = turn_params["input"][0]
            probe_request = {
                **turn_request,
                "params": {
                    **turn_params,
                    "input": [{**text_item, "text": "x"}],
                },
            }
            _require_jsonl_string_fits(
                probe_request, prompt, max_frame_bytes=max_frame_bytes
            )
            exchange(turn_request)
            while contract.state == "turn_active":
                transport.read_notification(
                    on_notification=receive_notification,
                    timeout_seconds=timeout_seconds,
                )
            transport.finish(
                on_notification=receive_notification,
                timeout_seconds=timeout_seconds,
            )
            self._delivery_status = contract.state
            self._process_exit_code = transport.exit_code
            self._shutdown_mode = transport.shutdown_mode
            return {
                "state": contract.state,
                "thread_id": contract.thread_id,
                "turn_id": contract.turn_id,
                "model": model,
                "effort": effort,
                "worker_id": binding.worker_id,
                "attempt_id": binding.attempt_id,
                "assurance": "offline_fake_only",
                "live_send_permitted": False,
                "production_finalization_permitted": False,
            }
        except UnknownDelivery:
            self._delivery_status = "unknown_delivery"
            _LOG.warning("offline fake app-server attempt is quarantined as unknown delivery")
            raise
        except _FrameTooLarge:
            self._delivery_status = "not_sent"
            _LOG.warning("offline fake app-server rejected an oversized frame before writing")
            raise
        except ProtocolRejected:
            self._delivery_status = "needs_human"
            _LOG.warning("offline fake app-server protocol rejected; operator review required")
            raise
        finally:
            graceful = self._delivery_status in {
                "transport_completed_unverified", "needs_human"
            }
            self._process_exit_code = transport.close(graceful=graceful)
            self._shutdown_mode = transport.shutdown_mode

    def __repr__(self) -> str:
        return (
            f"<OfflineFakeAppServer scenario={self._scenario.value!r} "
            f"delivery_status={self._delivery_status!r}>"
        )
