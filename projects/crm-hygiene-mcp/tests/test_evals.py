from evals.run_evals import evaluate


def test_quality_gates_hold_on_seeded_data():
    results = evaluate(seeds=[11, 12, 13])
    failed = {check: r for check, r in results.items() if not r["passed"]}
    assert not failed, failed
