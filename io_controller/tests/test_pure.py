"""
Pure-function tests for the live driver (io_controller.py / cooling_mode.py).
No hardware: only math, config loading and the set_and_verify contract.
"""
import math

import pytest

import io_controller as ioc
from io_controller import (ntc_resistance_to_temp, ntc_voltage_to_resistance,
                           load_component_config, parse_rgb_color,
                           set_and_verify, verify_each, VerificationError,
                           NTC_R0, NTC_VREF, NTC_R_SERIES)
from cooling_mode import CoolingController


# ------------------------------------------------------------------ NTC ---
def test_ntc_resistance_to_temp_reference_point():
    assert ntc_resistance_to_temp(NTC_R0) == pytest.approx(25.0, abs=1e-9)
    assert ntc_resistance_to_temp(10000) == 25.0


def test_ntc_resistance_to_temp_edge_cases():
    assert ntc_resistance_to_temp(None) is None
    assert ntc_resistance_to_temp(0) is None
    assert ntc_resistance_to_temp(-5) is None


def test_ntc_temp_monotonic_decreasing_in_resistance():
    rs = [1000, 2000, 5000, 10000, 20000, 50000, 100000]
    ts = [ntc_resistance_to_temp(r) for r in rs]
    assert all(a > b for a, b in zip(ts, ts[1:]))
    assert ts[0] > 80 and ts[-1] < 0


def test_ntc_voltage_to_resistance():
    assert ntc_voltage_to_resistance(0) is None
    assert ntc_voltage_to_resistance(-0.1) is None
    assert ntc_voltage_to_resistance(NTC_VREF) is None
    assert ntc_voltage_to_resistance(NTC_VREF + 1) is None
    # pull-up divider: at Vref/2 the NTC equals the series resistor
    assert ntc_voltage_to_resistance(NTC_VREF / 2) == pytest.approx(NTC_R_SERIES)
    # and the chain gives 25.0 C at that point
    assert ntc_resistance_to_temp(ntc_voltage_to_resistance(NTC_VREF / 2)) == pytest.approx(25.0)
    # monotonic: higher voltage -> larger resistance (pull-up wiring)
    vs = [0.5, 1.0, 1.65, 2.5, 3.0]
    rr = [ntc_voltage_to_resistance(v) for v in vs]
    assert all(a < b for a, b in zip(rr, rr[1:]))


# --------------------------------------------------- component config -----
def test_load_component_config_finds_default():
    cfg = load_component_config()
    for k in ('heating', 'cooling', 'heater', 'door_sensor', 'led_power', 'leds'):
        assert k in cfg, k
    # the values app.py mirrors as its validation limits
    assert cfg['heating']['target_min'] == 30
    assert cfg['led_power']['min_intensity'] == 10


def test_load_component_config_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_component_config(str(tmp_path / 'nope.json'))


def test_load_component_config_explicit_path(tmp_path):
    p = tmp_path / 'c.json'
    p.write_text('{"heating": {"target_min": 31}}', encoding='utf-8')
    assert load_component_config(str(p)) == {'heating': {'target_min': 31}}


# ------------------------------------------------------------ RGB color ---
def test_parse_rgb_color():
    assert parse_rgb_color('red') == (255, 0, 0)
    assert parse_rgb_color(' RED ') == (255, 0, 0)
    assert parse_rgb_color('#00ff00') == (0, 255, 0)
    assert parse_rgb_color('0000FF') == (0, 0, 255)
    assert parse_rgb_color('off') == (0, 0, 0)
    for bad in ('nope', '#12345', 'gggggg', ''):
        with pytest.raises(ValueError):
            parse_rgb_color(bad)


# ---------------------------------------------------- set_and_verify -----
def test_set_and_verify_success_first_try():
    calls = []
    attempt, observed = set_and_verify('x', lambda: calls.append('apply'),
                                       lambda: (True, 'on'))
    assert (attempt, observed) == (1, 'on')
    assert calls == ['apply']


def test_set_and_verify_retries_then_succeeds():
    calls = []
    def check():
        return (len(calls) >= 2, len(calls))
    attempt, observed = set_and_verify('x', lambda: calls.append(1), check)
    assert attempt == 2 and observed == 2
    assert len(calls) == 2


def test_set_and_verify_raises_after_retries():
    calls = []
    with pytest.raises(VerificationError) as ei:
        set_and_verify('heater', lambda: calls.append(1), lambda: (False, 'off'), retries=3)
    assert len(calls) == 3
    assert 'heater' in str(ei.value) and '3 attempts' in str(ei.value) and "'off'" in str(ei.value)
    assert issubclass(VerificationError, RuntimeError)


def test_verify_each_runs_all_and_aggregates():
    ran = []
    def ok():
        ran.append('ok')
    def bad():
        ran.append('bad'); raise VerificationError('nope')
    with pytest.raises(VerificationError) as ei:
        verify_each([('a', bad), ('b', ok), ('c', bad)])
    assert ran == ['bad', 'ok', 'bad']         # all attempted
    assert '2 component(s) not confirmed' in str(ei.value)
    verify_each([('a', ok)])                   # no raise


# --------------------------------------------- CoolingController slope ----
def test_slope_c_per_min():
    assert CoolingController._slope_c_per_min([(0, 50), (30, 49), (60, 48)]) == pytest.approx(2.0)
    assert CoolingController._slope_c_per_min([(0, 50), (30, 49)]) is None            # < 3 samples
    assert CoolingController._slope_c_per_min([(0, 50), (2, 49.9), (4, 49.8)]) is None  # < 10 s span
    assert CoolingController._slope_c_per_min([]) is None
    # heating (temperature rising) -> negative cooling rate
    assert CoolingController._slope_c_per_min([(0, 40), (30, 41), (60, 42)]) == pytest.approx(-2.0)
    # flat -> 0
    assert CoolingController._slope_c_per_min([(0, 40), (30, 40), (60, 40)]) == pytest.approx(0.0)


def test_verify_constants_unchanged():
    # safety invariant: retry policy and door sensor level
    assert ioc.VERIFY_RETRIES == 3
    assert ioc.GPIO_INPUTS == {'DOOR_STATUS': 27}
    assert ioc.GPIO_INPUT_OPEN_LEVEL == {'DOOR_STATUS': 0}
