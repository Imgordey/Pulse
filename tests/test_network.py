from pulse.core.network import NetworkTotals, network_activity


def test_rates_use_elapsed_monotonic_time() -> None:
    rates = network_activity(NetworkTotals(100, 200, 1), NetworkTotals(300, 600, 3))
    assert rates.sent_per_second == 100
    assert rates.received_per_second == 200


def test_counter_reset_and_invalid_clock_are_unknown() -> None:
    before = NetworkTotals(100, 200, 2)
    for after in (NetworkTotals(1, 2, 3), NetworkTotals(300, 600, 1)):
        assert network_activity(before, after).sent_per_second is None
