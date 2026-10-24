"""In-process task manager: long-running work streamed to the UI over SSE.

A task runs as an asyncio task on the server loop. It reports progress with
``task.emit(event, data)``, which is thread-safe (browser work runs on a
separate thread, see api.browser_thread). Every event is kept, so a client
that subscribes late (or reconnects with Last-Event-ID) gets the full stream.
The stream always ends with a ``done`` or ``error`` event.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
from collections import OrderedDict
from datetime import datetime
from typing import Any, AsyncIterator, Awaitable, Callable

log = logging.getLogger("job_mcp.api.tasks")

TERMINAL_EVENTS = ("done", "error")
MAX_TASKS = 50


def _now() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


class TaskCancelled(Exception):
    """Raised inside a task body to finish it as cancelled with a custom result."""


class Task:
    def __init__(self, kind: str, loop: asyncio.AbstractEventLoop):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.status = "running"
        self.result: Any = None
        self.error: dict | None = None
        self.created_at = _now()
        self.finished_at: str | None = None
        self.meta: dict = {}  # small facts the UI needs to re-attach (e.g. dry_run for apply)
        self.events: list[tuple[int, str, Any]] = []
        self.cancel_event = threading.Event()
        self._loop = loop
        self._subscribers: set[asyncio.Queue] = set()
        self._handle: asyncio.Task | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------- events
    def emit(self, event: str, data: Any) -> None:
        """Record and broadcast an event (callable from any thread)."""
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            self._emit_local(event, data)
        else:
            self._loop.call_soon_threadsafe(self._emit_local, event, data)

    def _emit_local(self, event: str, data: Any) -> None:
        if self.events and self.events[-1][1] in TERMINAL_EVENTS:
            return  # stream already closed
        ev = (len(self.events), event, data)
        self.events.append(ev)
        for q in list(self._subscribers):
            q.put_nowait(ev)

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def snapshot(self) -> dict:
        out = {"id": self.id, "kind": self.kind, "status": self.status,
               "created_at": self.created_at, "finished_at": self.finished_at, "meta": self.meta}
        progress = next((d for _, e, d in reversed(self.events) if e == "progress"), None)
        if progress is not None:
            out["progress"] = progress
        if self.result is not None:
            out["result"] = self.result
        if self.error is not None:
            out["error"] = self.error
        return out

    async def stream(self, last_event_id: int | None = None) -> AsyncIterator[tuple[int, str, Any]]:
        q: asyncio.Queue = asyncio.Queue()
        start = 0 if last_event_id is None else last_event_id + 1
        backlog = self.events[start:]
        self._subscribers.add(q)
        try:
            for ev in backlog:
                yield ev
                if ev[1] in TERMINAL_EVENTS:
                    return
            next_id = start + len(backlog)
            while True:
                ev = await q.get()
                if ev[0] < next_id:
                    continue  # already sent from the backlog
                next_id = ev[0] + 1
                yield ev
                if ev[1] in TERMINAL_EVENTS:
                    return
        finally:
            self._subscribers.discard(q)


TaskBody = Callable[[Task], Awaitable[Any]]


class TaskManager:
    def __init__(self) -> None:
        self.tasks: "OrderedDict[str, Task]" = OrderedDict()

    def start(self, kind: str, body: TaskBody) -> Task:
        loop = asyncio.get_running_loop()
        task = Task(kind, loop)
        self.tasks[task.id] = task
        while len(self.tasks) > MAX_TASKS:
            oldest_id, oldest = next(iter(self.tasks.items()))
            if oldest.status == "running":
                break
            self.tasks.pop(oldest_id)
        task._handle = loop.create_task(self._run(task, body))
        return task

    async def _run(self, task: Task, body: TaskBody) -> None:
        try:
            result = await body(task)
            task.result = result
            task.status = "cancelled" if task.cancelled else "done"
            task.emit("done", result if result is not None else {})
        except asyncio.CancelledError:
            task.status = "cancelled"
            task.error = {"code": "cancelled", "message": "Cancelled."}
            task.emit("error", task.error)
        except TaskCancelled as exc:
            task.status = "cancelled"
            task.error = {"code": "cancelled", "message": str(exc) or "Cancelled."}
            task.emit("error", task.error)
        except Exception as exc:
            code = getattr(exc, "code", None) or "task_failed"
            message = getattr(exc, "message", None) or f"{type(exc).__name__}: {exc}"
            if code == "task_failed":
                log.exception("task %s (%s) failed", task.id, task.kind)
            task.status = "error"
            task.error = {"code": code, "message": message}
            task.emit("error", task.error)
        finally:
            task.finished_at = _now()

    def get(self, task_id: str) -> Task | None:
        return self.tasks.get(task_id)

    def list(self, kind: str | None = None, status: str | None = None) -> list[Task]:
        """Tasks, newest first, optionally filtered by kind and status."""
        return [t for t in reversed(self.tasks.values())
                if (kind is None or t.kind == kind) and (status is None or t.status == status)]

    def cancel(self, task_id: str, hard: bool = True) -> Task | None:
        """Ask a task to stop. Tasks that honour ``cancel_event`` (apply) finish
        their current step; others (``hard``) are cancelled right away."""
        task = self.tasks.get(task_id)
        if task is None:
            return None
        if task.status != "running":
            return task
        task.cancel_event.set()
        if hard and task.kind not in SOFT_CANCEL_KINDS and task._handle is not None:
            task._handle.cancel()
        return task


# Kinds whose body watches cancel_event and stops cleanly by itself.
SOFT_CANCEL_KINDS = {"apply"}


def sse_format(event_id: int, event: str, data: Any) -> dict:
    """An item for sse_starlette's EventSourceResponse."""
    return {"id": str(event_id), "event": event, "data": json.dumps(data, default=str)}


manager = TaskManager()
