from app.ext import main as sup


def test_limits_from_manifest_are_clamped() -> None:
    assert sup.limits({}) == (sup.MEM_LIMIT, sup.CPU_LIMIT)
    assert sup.limits({"runtime": {"memory": 64, "cpu": 30}}) == (64, 30)
    assert sup.limits({"runtime": {"memory": 999999, "cpu": 500}}) == (sup.MEM_LIMIT * 4, 100)
    assert sup.limits({"runtime": {"memory": 1, "cpu": 1}}) == (32, 5)


def test_over_memory_and_sustained_cpu() -> None:
    reason, hot = sup.over({"mem": 300.0, "cpu": 1.0}, 256, 80, 0)
    assert reason and "memory" in reason and hot == 0
    hot = 0
    for _ in range(sup.CPU_SAMPLES - 1):
        reason, hot = sup.over({"mem": 50.0, "cpu": 95.0}, 256, 80, hot)
        assert reason is None
    reason, hot = sup.over({"mem": 50.0, "cpu": 95.0}, 256, 80, hot)
    assert reason and "cpu" in reason
    reason, hot = sup.over({"mem": 50.0, "cpu": 95.0}, 256, 80, 3)
    reason, hot = sup.over({"mem": 50.0, "cpu": 10.0}, 256, 80, hot)
    assert reason is None and hot == 0
