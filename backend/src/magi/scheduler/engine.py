"""Run synchronous scheduling off-loop while retaining runtime task ownership."""

from __future__ import annotations

import asyncio
from concurrent.futures import Future
from datetime import datetime

from apscheduler.events import JobExecutionEvent
from apscheduler.executors.base import BaseExecutor, run_coroutine_job
from apscheduler.job import Job
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import STATE_STOPPED


class RuntimeLoopExecutor(BaseExecutor):
    """Submit scheduled coroutines to the worker's existing event loop."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__()
        self._loop = loop
        self._futures: set[Future] = set()
        self._tasks: set[asyncio.Task] = set()

    def _do_submit_job(self, job: Job, run_times: list[datetime]) -> None:
        future = asyncio.run_coroutine_threadsafe(self._run(job, run_times), self._loop)
        self._futures.add(future)
        # Always complete on the runtime loop, even if the future already finished.
        # BaseExecutor must increment its instance count before completion decrements it.
        future.add_done_callback(
            lambda completed: self._loop.call_soon_threadsafe(self._complete, job.id, completed)
        )

    async def _run(self, job: Job, run_times: list[datetime]) -> list[JobExecutionEvent]:
        task = asyncio.current_task()
        assert task is not None
        self._tasks.add(task)
        try:
            return await run_coroutine_job(job, job._jobstore_alias, run_times, self._logger.name)
        finally:
            self._tasks.discard(task)

    def _complete(self, job_id: str, future: Future) -> None:
        with self._lock:
            self._futures.discard(future)
        if future.cancelled():
            self._run_job_success(job_id, [])
            return
        try:
            events = future.result()
        except BaseException as exc:
            self._run_job_error(job_id, exc, exc.__traceback__)
        else:
            self._run_job_success(job_id, events)

    def shutdown(self, wait: bool = True) -> None:
        """Stop accepted jobs; the asynchronous owner subsequently drains them."""
        with self._lock:
            futures = list(self._futures)
        for future in futures:
            future.cancel()

    async def drain(self) -> None:
        """Wait for coroutine cleanup after the scheduler thread has stopped."""
        await asyncio.sleep(0)
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)


class ResilientBackgroundScheduler(BackgroundScheduler):
    """Keep retrying persistent scheduling failures outside the runtime loop."""

    def _process_jobs(self) -> float | None:
        try:
            # Shutdown acquires executors before jobstores. Match that order before
            # the due-job scan takes the jobstore lock and looks up an executor.
            with self._executors_lock:
                # A tick may have entered before shutdown and waited on this lock.
                # It must not submit work after the executor's cancellation sweep.
                if self.state == STATE_STOPPED:
                    return None
                return super()._process_jobs()
        except Exception:
            self._logger.exception(
                "Scheduler wakeup failed; retrying after %s seconds",
                self.jobstore_retry_interval,
            )
            return max(float(self.jobstore_retry_interval), 0.0)
