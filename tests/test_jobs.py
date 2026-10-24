import threading

from pocketagent.jobs import JobQueue


def test_jobs_run_one_at_a_time_in_order():
    queue, order = JobQueue(), []
    jobs = [queue.submit(f"job {i}", lambda i=i: order.append(i) or i * 10) for i in range(3)]
    for job in jobs:
        assert job.done.wait(5)
    assert order == [0, 1, 2]
    assert [j.result for j in jobs] == [0, 10, 20] and all(j.status == "done" for j in jobs)
    assert queue.get(jobs[0].id) is jobs[0]


def test_a_failing_job_keeps_its_error_and_the_queue_goes_on():
    queue = JobQueue()
    bad = queue.submit("bad", lambda: 1 / 0)
    good = queue.submit("good", lambda: "fine")
    assert good.done.wait(5) and bad.done.is_set()
    assert bad.status == "failed" and "ZeroDivisionError" in bad.error
    assert good.result == "fine"


def test_waiting_jobs_can_be_cancelled():
    queue, started, release, ran = JobQueue(), threading.Event(), threading.Event(), []
    queue.submit("busy", lambda: started.set() or release.wait())
    assert started.wait(5)
    waiting = [queue.submit(f"later {i}", lambda i=i: ran.append(i)) for i in range(2)]
    assert queue.cancel_waiting() == 2
    release.set()
    for job in waiting:
        assert job.done.wait(5) and job.status == "cancelled"
    assert ran == []
    assert [j["status"] for j in queue.recent()][:2] == ["cancelled", "cancelled"]
