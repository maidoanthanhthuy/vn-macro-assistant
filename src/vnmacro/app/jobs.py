"""Background question jobs for the Streamlit app.

A question runs in a worker thread, not in the Streamlit script thread, so a rerun of
the script (e.g. a feedback click) does not stop it: the job is kept in session state
and the next run keeps waiting for it. Progress steps are recorded on the job.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Executor, Future
from dataclasses import dataclass, field
from typing import Any


@dataclass
class QuestionJob:
    """One question running in the background, with the steps reached so far."""

    question: str
    future: Future | None = None
    steps: list[str] = field(default_factory=list)

    @property
    def done(self) -> bool:
        """True once the worker finished (with a result or an exception)."""
        return self.future is not None and self.future.done()


def start_job(
    executor: Executor, ask: Callable[..., Any], question: str, **kwargs: Any
) -> QuestionJob:
    """Submit ask(question, on_step=..., **kwargs); each step name goes to job.steps."""
    job = QuestionJob(question)
    job.future = executor.submit(ask, question, on_step=job.steps.append, **kwargs)
    return job
