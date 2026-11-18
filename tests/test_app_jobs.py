import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from vnmacro.app.jobs import start_job


def test_job_records_steps_and_result():
    release = threading.Event()

    def ask(question, on_step, today=None):
        on_step("route")
        release.wait(5)
        on_step("answer")
        return f"{question}|{today}"

    with ThreadPoolExecutor(1) as pool:
        job = start_job(pool, ask, "Q?", today="d")
        assert job.question == "Q?" and not job.done
        release.set()
        assert job.future.result(5) == "Q?|d"
    assert job.done and job.steps == ["route", "answer"]


def test_job_keeps_the_exception():
    def ask(question, on_step):
        raise RuntimeError("boom")

    with ThreadPoolExecutor(1) as pool:
        job = start_job(pool, ask, "Q")
        with pytest.raises(RuntimeError):
            job.future.result(5)
    assert job.done
