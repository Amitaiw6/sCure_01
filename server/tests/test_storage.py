"""
storage.py (JSON files, CureFileStore, ComponentCounters), hardware_controller
tiers and cloud_sync construction - unit tests without Flask.
"""
import os
import json
import time

import pytest

import storage
from storage import (load_json_file, save_json_file, CureFileStore,
                     ComponentCounters, DATA_DIR)
from hardware_controller import HardwareController, SIM_AMBIENT
from cloud_sync import CloudSync


# ------------------------------------------------------------- DATA_DIR ----
def test_data_dir_respects_env(data_dir):
    assert os.path.abspath(DATA_DIR) == os.path.abspath(os.environ['SCURE_DATA_DIR'])
    assert os.path.abspath(DATA_DIR) == os.path.abspath(data_dir)
    # every file constant lives under it
    for p in (storage.USER_MATERIALS_FILE, storage.PRINT_HISTORY_FILE,
              storage.CURE_HISTORY_FILE, storage.CURE_REPORTS_FILE,
              storage.PHASE_TIMINGS_FILE):
        assert os.path.dirname(p) == DATA_DIR
    # and NOT under the repo's server/data
    assert 'server' + os.sep + 'data' not in DATA_DIR


# --------------------------------------------------- save/load_json_file --
def test_save_load_json_atomic(data_dir):
    path = os.path.join(data_dir, 'unit_test.json')
    save_json_file(path, {'a': 1, 'b': [1, 2]})
    assert not os.path.exists(path + '.tmp')
    assert load_json_file(path, {}) == {'a': 1, 'b': [1, 2]}
    # type mismatch -> default
    assert load_json_file(path, []) == []
    # missing -> default
    assert load_json_file(path + '.nope', [7]) == [7]


def test_load_json_corrupt_returns_default(data_dir):
    path = os.path.join(data_dir, 'corrupt.json')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('{"a": 1,,,')
    assert load_json_file(path, {'d': True}) == {'d': True}
    assert load_json_file(path, []) == []


def test_user_materials_roundtrip(data_dir):
    storage.save_user_materials([{'id': 'x'}])
    assert storage.load_user_materials() == [{'id': 'x'}]
    assert not os.path.exists(storage.USER_MATERIALS_FILE + '.tmp')
    # non-list content -> []
    with open(storage.USER_MATERIALS_FILE, 'w', encoding='utf-8') as f:
        f.write('{"not": "a list"}')
    assert storage.load_user_materials() == []
    storage.save_user_materials([])


# ---------------------------------------------------------- CureFileStore --
def test_cure_file_store_flush_semantics(data_dir, monkeypatch):
    # isolate from the app's store: point the module constants at temp files
    hist = os.path.join(data_dir, 'cfs_history.json')
    reps = os.path.join(data_dir, 'cfs_reports.json')
    monkeypatch.setattr(storage, 'CURE_HISTORY_FILE', hist)
    monkeypatch.setattr(storage, 'CURE_REPORTS_FILE', reps)
    monkeypatch.setattr(storage, 'TELEMETRY_FLUSH_EVERY', 3)

    st = CureFileStore()
    assert st.list() == []
    st.start('r1', {'materialName': 'M', 'steps': 2, 'targetTemp': 50})
    assert json.load(open(hist, encoding='utf-8'))[0]['id'] == 'r1'      # start flushes
    # duplicate start does not create a second run
    st.start('r1', {'materialName': 'M2'})
    assert len(st.list()) == 1 and st.list()[0]['materialName'] == 'M'

    assert st.telemetry('r1', {'t': 0}) is True
    assert st.telemetry('r1', {'t': 1}) is True
    on_disk = json.load(open(hist, encoding='utf-8'))
    assert on_disk[0]['telemetry'] == []                                  # not yet flushed (2 < 3)
    assert st.telemetry('r1', {'t': 2}) is True
    on_disk = json.load(open(hist, encoding='utf-8'))
    assert len(on_disk[0]['telemetry']) == 3                              # flushed at 3
    assert st.telemetry('nope', {'t': 0}) is False

    assert st.finish('r1', 'completed', 2) is True
    on_disk = json.load(open(hist, encoding='utf-8'))
    assert on_disk[0]['status'] == 'completed' and on_disk[0]['stepsCompleted'] == 2
    assert on_disk[0]['endedAt'] and isinstance(on_disk[0]['duration'], int)
    assert st.finish('nope', 'completed', 0) is False

    assert st.get_report('r1') is None
    assert st.save_report('r1', {'content': 'c', 'summary': 's'}) == 'r1'
    assert st.get_report('r1') == {'content': 'c', 'summary': 's', 'format': 'html'}
    assert json.load(open(reps, encoding='utf-8'))['r1']['content'] == 'c'

    # a run left 'running' (power cut) is marked error on the next construction
    st.start('r2', {})
    st2 = CureFileStore()
    r2 = next(r for r in st2.list() if r['id'] == 'r2')
    assert r2['status'] == 'error'
    r1 = next(r for r in st2.list() if r['id'] == 'r1')
    assert r1['status'] == 'completed'


# ------------------------------------------------------ ComponentCounters --
def _counters(data_dir, state, name='cc.json'):
    path = os.path.join(data_dir, name)
    return ComponentCounters(path, lambda: state), path


def test_counters_sample_mapping(data_dir):
    state = {'uvOn': True, 'uvWavelength': 405, 'isHeating': True, 'heaterOut': True,
             'fanRpm': {'chamber_heating': 2000, 'chamber_intake': 0},
             'fans': {'chamber_heating': 0, 'chamber_intake': 0}}
    c, _ = _counters(data_dir, state, 'cc1.json')
    on = c._sample()
    assert on == {'led405': True, 'led450': False, 'heater': True,
                  'heaterFan': True, 'coolingFan': False}

    # heater counts ONLY while isHeating - stale heaterOut must not count
    state.update({'isHeating': False, 'heaterOut': True, 'heaterPwm': 50})
    assert c._sample()['heater'] is False
    # isHeating with heaterOut False -> not energized right now
    state.update({'isHeating': True, 'heaterOut': False})
    assert c._sample()['heater'] is False
    # no heaterOut key: fallback to heaterPwm > 0
    state.pop('heaterOut'); state.update({'isHeating': True, 'heaterPwm': 0})
    assert c._sample()['heater'] is False
    state['heaterPwm'] = 10
    assert c._sample()['heater'] is True
    # neither: heating mode alone counts
    state.pop('heaterPwm')
    assert c._sample()['heater'] is True

    # 450 nm and cooling fan by commanded duty
    state.update({'uvWavelength': 450, 'fans': {'chamber_intake': 60}, 'fanRpm': {}})
    on = c._sample()
    assert on['led405'] is False and on['led450'] is True and on['coolingFan'] is True
    assert on['heaterFan'] is False


def test_counters_hours_flush_and_reload(data_dir):
    c, path = _counters(data_dir, {}, 'cc2.json')
    assert c.hours() == {k: 0.0 for k in ComponentCounters.KEYS}
    c.seconds['heater'] = 3600 * 2.55
    c.seconds['led405'] = 90.0
    assert c.hours()['heater'] == 2.5 or c.hours()['heater'] == 2.6   # 1-decimal rounding
    c.flush()
    assert os.path.exists(path) and not os.path.exists(path + '.tmp')
    saved = json.load(open(path, encoding='utf-8'))
    assert saved['heater'] == pytest.approx(9180.0) and saved['led405'] == 90.0
    # reload picks the values up
    c2 = ComponentCounters(path, lambda: {})
    assert c2.seconds['heater'] == pytest.approx(9180.0)
    # corrupt file -> zeros, no exception
    with open(path, 'w', encoding='utf-8') as f:
        f.write('nope')
    c3 = ComponentCounters(path, lambda: {})
    assert c3.hours()['heater'] == 0.0


# --------------------------------------------------- HardwareController ---
def test_hardware_controller_simulation_tier():
    hw = HardwareController(None)
    s = hw.get_state()
    assert s['hwSource'] == 'simulation'
    assert s['chamberTemp'] == SIM_AMBIENT and s['doorClosed'] is True
    assert hw.heat_to_target_temperature(50) == (True, None)
    assert hw.heating is True and hw.target_temp == 50
    # sim thermal model moves toward the target
    hw._sim_time -= 4.0
    assert hw.get_state()['chamberTemp'] > SIM_AMBIENT
    assert hw.cool_to_target_temperature(40, 'fast') == (True, None)
    assert hw.heating is False and hw.cooling is True and hw.cooling_mode == 'fast'
    assert hw.stop_all() == (True, None)
    assert hw.cooling is False and hw.fans['chamber_intake'] == 0


def test_hardware_controller_bridge_tier_delegates():
    class FakeBridge:
        def __init__(self):
            self.calls = []
        def get_state(self):
            return {'hwSource': 'io_controller', 'chamberTemp': 33.0}
        def heat_to_target(self, t):
            self.calls.append(('heat', t)); return True, None
        def cool_to_target(self, t, m):
            self.calls.append(('cool', t, m)); return True, None
        def stop_all(self, immediate):
            self.calls.append(('stop', immediate)); return True, None
        def open_door(self):
            self.calls.append(('door',)); return True, None
        def ack_door_abort(self):
            self.calls.append(('ack',)); return True, None
        def set_uv(self, on, i, w):
            self.calls.append(('uv', on, i, w)); return False, 'refused'
        def set_target_temp(self, t):
            self.calls.append(('target', t)); return False, 'door open'
    b = FakeBridge()
    hw = HardwareController(b)
    assert hw.get_state()['hwSource'] == 'io_controller'
    assert hw.heat_to_target_temperature(55) == (True, None)
    assert hw.cool_to_target_temperature(40, 'slow') == (True, None)
    assert hw.stop_all(True) == (True, None)
    assert hw.open_door() == (True, None)
    assert hw.door_closed is True                  # sim door flag untouched with a bridge
    assert hw.ack_door_abort() == (True, None)
    assert hw.set_uv(True, 40, 405) == (False, 'refused')
    assert hw.set_target_temp(50) == (False, 'door open') and hw.heating is False
    assert b.calls == [('heat', 55), ('cool', 40, 'slow'), ('stop', True), ('door',),
                       ('ack',), ('uv', True, 40, 405), ('target', 50)]


def test_hardware_controller_bridge_state_failure_falls_back_to_sim():
    class Broken:
        def get_state(self):
            raise RuntimeError('i2c')
    hw = HardwareController(Broken())
    assert hw.get_state()['hwSource'] == 'simulation'


# ------------------------------------------------------------ CloudSync ---
def test_cloud_sync_disabled_without_config(tmp_path):
    cs = CloudSync(str(tmp_path), lambda: {}, None,
                   get_programs=lambda: [], put_programs=lambda m: None,
                   get_prints=lambda: [], put_prints=lambda p: None,
                   list_cures=lambda: [])
    assert cs.enabled is False
    assert cs.status() == {'enabled': False, 'lastSyncOk': None, 'error': None}


def test_cloud_sync_bad_config_reports_error(tmp_path):
    (tmp_path / 'cloud.json').write_text('{"url": "http://x"}', encoding='utf-8')
    cs = CloudSync(str(tmp_path), lambda: {}, None,
                   get_programs=lambda: [], put_programs=lambda m: None,
                   get_prints=lambda: [], put_prints=lambda p: None,
                   list_cures=lambda: [])
    assert cs.enabled is False
    assert 'url' in cs.status()['error'] and 'key' in cs.status()['error']
    (tmp_path / 'cloud.json').write_text('{bad json', encoding='utf-8')
    cs = CloudSync(str(tmp_path), lambda: {}, None,
                   get_programs=lambda: [], put_programs=lambda m: None,
                   get_prints=lambda: [], put_prints=lambda p: None,
                   list_cures=lambda: [])
    assert cs.enabled is False and cs.status()['error'].startswith('bad cloud.json')


def test_cloud_sync_apply_commands_use_injected_callables(tmp_path):
    programs = [{'id': 'a', 'name': 'A', 'steps': [1, 2], 'totalDuration': 15}]
    prints = []
    cs = CloudSync(str(tmp_path), lambda: {'chamberTemp': 24}, None,
                   get_programs=lambda: list(programs),
                   put_programs=lambda m: (programs.clear(), programs.extend(m)),
                   get_prints=lambda: list(prints),
                   put_prints=lambda p: (prints.clear(), prints.extend(p)),
                   list_cures=lambda: [])
    assert cs._apply({'type': 'upsert_program', 'payload': {'id': 'a', 'name': 'A2'}}) is True
    assert programs == [{'id': 'a', 'name': 'A2'}]
    assert cs._apply({'type': 'send_print', 'payload': {'printName': 'P', 'materialName': 'A2'}}) is True
    assert prints[0]['printName'] == 'P' and prints[0]['status'] == 'completed'
    assert cs._apply({'type': 'delete_program', 'payload': {'id': 'a'}}) is True
    assert programs == []
    assert cs._apply({'type': 'reboot'}) is False       # no hardware / system commands
    assert cs._apply({'type': 'set_heater'}) is False
