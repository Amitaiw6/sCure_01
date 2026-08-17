"""
Flask API tests in simulation mode (no IO board). Exercises the routes that
app.py kept after the storage / hardware_controller / cloud_sync split.
"""
import os
import time
import json


def _post(client, url, **kw):
    r = client.post(url, **kw)
    return r.status_code, r.get_json()


def _get(client, url):
    r = client.get(url)
    return r.status_code, r.get_json()


# ---------------------------------------------------------------- state ----
def test_state_simulation(client):
    code, s = _get(client, '/api/state')
    assert code == 200
    assert s['hwSource'] == 'simulation'
    for k in ('chamberTemp', 'targetTemp', 'doorClosed', 'isHeating', 'isCooling',
              'uvOn', 'fans', 'fanRpm', 'ledTemps', 'faults', 'counters', 'cloudSync'):
        assert k in s, k
    assert set(s['counters']) == {'led405', 'led450', 'coolingFan', 'heater', 'heaterFan'}
    assert s['cloudSync'] == {'enabled': False, 'lastSyncOk': None, 'error': None}
    assert s['doorClosed'] is True


def test_hw_singleton_is_simulation(app_module):
    assert app_module.io_bridge is None
    assert app_module.hw.bridge is None
    assert app_module.hw.get_state()['hwSource'] == 'simulation'


# ----------------------------------------------------------- validation ----
def test_heat_target_out_of_range_7001(client):
    for t in (200, 29.9, 80.1, -5):
        code, r = _post(client, f'/api/cure/heat?target={t}')
        assert code == 200
        assert r['ok'] is False and r['code'] == 7001, (t, r)
    for t in (30, 80):
        _, r = _post(client, f'/api/cure/heat?target={t}')
        assert r['ok'] is True, (t, r)
    _post(client, '/api/cure/stop')


def test_dry_and_cure_validation(client):
    _, r = _post(client, '/api/cure/dry?target=20')
    assert r['code'] == 7001
    _, r = _post(client, '/api/cure/cure-405?target=50&intensity=5')
    assert r['ok'] is False and r['code'] == 7002
    _, r = _post(client, '/api/cure/cure-450?target=50&intensity=101')
    assert r['ok'] is False and r['code'] == 7002
    _, r = _post(client, '/api/cure/cure-405?target=25&intensity=50')
    assert r['code'] == 7001                     # temp checked before intensity
    _, r = _post(client, '/api/cure/cure-450?target=50&intensity=10')
    assert r['ok'] is True
    _post(client, '/api/cure/stop')


def test_cool_validation(client):
    _, r = _post(client, '/api/cure/cool?target=10&mode=fast')
    assert r['ok'] is False and r['code'] == 7001      # < COOL_TARGET_MIN(20)
    _, r = _post(client, '/api/cure/cool?target=90&mode=fast')
    assert r['code'] == 7001
    _, r = _post(client, '/api/cure/cool?target=40&mode=turbo')
    assert r['ok'] is False and r['code'] == 7003
    _, r = _post(client, '/api/cure/cool?target=20&mode=slow')
    assert r['ok'] is True
    _post(client, '/api/cure/stop')


def test_uv_and_chamber_temperature_validation(client):
    _, r = _post(client, '/api/uv?on=1&intensity=5')
    assert r['code'] == 7002
    _, r = _post(client, '/api/uv?on=1&intensity=30&wavelength=500')
    assert r['ok'] is False
    _, r = _post(client, '/api/chamber/temperature?target=25')
    assert r['ok'] is False and r['code'] == 7001
    _, r = _post(client, '/api/uv?on=0')
    assert r['ok'] is True


# ------------------------------------------------------- heat -> stop ------
def test_heat_state_stop_sequence(client):
    _, r = _post(client, '/api/cure/heat?target=50')
    assert r == {'ok': True, 'message': 'Heating to 50.0°C'}
    _, s = _get(client, '/api/state')
    assert s['isHeating'] is True and s['targetTemp'] == 50.0 and s['isCooling'] is False
    _, r = _post(client, '/api/cure/cool?target=40&mode=fast')
    assert r['ok'] is True
    _, s = _get(client, '/api/state')
    assert s['isCooling'] is True and s['isHeating'] is False
    assert s['coolingMode'] == 'fast' and s['coolingFanPwm'] == 100
    assert s['fans']['led_cooling'] == 100 and s['fans']['chamber_intake'] == 100
    _, r = _post(client, '/api/cure/stop')
    assert r['ok'] is True
    _, s = _get(client, '/api/state')
    assert s['isHeating'] is False and s['isCooling'] is False and s['uvOn'] is False
    assert s['fans']['led_cooling'] == 0 and s['fans']['chamber_intake'] == 0


def test_cure_405_turns_uv_on_and_stop_turns_off(client):
    _, r = _post(client, '/api/cure/cure-405?target=50&intensity=40')
    assert r['ok'] is True
    _, s = _get(client, '/api/state')
    assert s['uvOn'] is True and s['uvIntensity'] == 40 and s['uvWavelength'] == 405
    assert s['isHeating'] is True
    _post(client, '/api/cure/stop?immediate=1')
    _, s = _get(client, '/api/state')
    assert s['uvOn'] is False and s['uvWavelength'] is None and s['isHeating'] is False


def test_nitrogen_valve(client):
    _, r = _post(client, '/api/cure/nitrogen?on=1')
    assert r['ok'] is True
    assert _get(client, '/api/state')[1]['nitrogenActive'] is True
    _, r = _post(client, '/api/cure/nitrogen?on=0')
    assert _get(client, '/api/state')[1]['nitrogenActive'] is False


# --------------------------------------------------------------- door -----
def test_door_open_and_auto_reclose(client, app_module):
    _, r = _post(client, '/api/door/open')
    assert r['ok'] is True
    _, s = _get(client, '/api/state')
    assert s['doorClosed'] is False
    # simulation: door re-reads closed within 5 s. Do not sleep 5 s: move the
    # sim clock instead (deterministic).
    assert app_module.hw._door_reclose_at is not None
    app_module.hw._door_reclose_at = time.time() - 0.01
    _, s = _get(client, '/api/state')
    assert s['doorClosed'] is True
    assert app_module.hw._door_reclose_at is None


def test_door_abort_ack(client):
    code, r = _post(client, '/api/door-abort/ack')
    assert code == 200 and r['ok'] is True


# ---------------------------------------------- materials / print history --
def test_user_materials_roundtrip_and_file(client, data_dir):
    _, before = _get(client, '/api/materials/user')
    assert before == []
    mats = [{'id': 'm1', 'name': 'Test', 'steps': [
        {'step': 1, 'process': 'Heating', 'temperature': 50, 'intensity': None, 'time': 10}]}]
    code, r = _post(client, '/api/materials/user', json=mats)
    assert code == 200 and r == {'ok': True}
    _, after = _get(client, '/api/materials/user')
    assert after == mats
    path = os.path.join(data_dir, 'user_materials.json')
    assert os.path.exists(path)
    assert not os.path.exists(path + '.tmp')
    with open(path, encoding='utf-8') as f:
        assert json.load(f) == mats
    # file really lives under SCURE_DATA_DIR, not server/data
    assert os.path.abspath(data_dir) == os.path.abspath(os.environ['SCURE_DATA_DIR'])


def test_presets_503_without_db(client, app_module):
    assert app_module._db_on() is False
    code, r = _get(client, '/api/materials/presets')
    assert code == 503
    assert r['ok'] is False


def test_print_history_roundtrip(client, data_dir):
    logs = [{'id': 'p1', 'printName': 'Job', 'materialName': 'Test',
             'printerName': 'J55', 'date': '2026-08-17T10:00:00',
             'duration': 20, 'status': 'completed', 'steps': 1, 'csvFile': ''}]
    _, r = _post(client, '/api/print-history', json=logs)
    assert r == {'ok': True}
    _, got = _get(client, '/api/print-history')
    assert got == logs
    assert os.path.exists(os.path.join(data_dir, 'print_history.json'))


# ------------------------------------------------------- cure runs ---------
def test_cure_run_lifecycle_and_report(client, data_dir):
    rid = 'run-test-1'
    _, r = _post(client, f'/api/cure-runs/{rid}/start',
                 json={'materialName': 'Test', 'steps': 2, 'targetTemp': 50,
                       'serialNumber': 'SN1', 'phases': [{'name': 'Heating'}]})
    assert r == {'ok': True}
    for t in range(3):
        _, r = _post(client, f'/api/cure-runs/{rid}/telemetry',
                     json={'t': t, 'temp': 24 + t})
        assert r == {'ok': True}
    # unknown run -> ok False
    _, r = _post(client, '/api/cure-runs/does-not-exist/telemetry', json={'t': 0})
    assert r == {'ok': False}
    _, r = _post(client, f'/api/cure-runs/{rid}/finish',
                 json={'status': 'completed', 'stepsCompleted': 2})
    assert r == {'ok': True}
    _, hist = _get(client, '/api/cure-history')
    run = next(x for x in hist if x['id'] == rid)
    assert run['status'] == 'completed'
    assert run['stepsCompleted'] == 2
    assert run['materialName'] == 'Test'
    assert len(run['telemetry']) == 3
    assert run['endedAt'] is not None and run['duration'] is not None
    # persisted to disk (finish flushes)
    with open(os.path.join(data_dir, 'cure_history.json'), encoding='utf-8') as f:
        assert any(x['id'] == rid for x in json.load(f))

    # report save / get
    code, r = _get(client, f'/api/cure-runs/{rid}/report')
    assert code == 404 and r['ok'] is False
    _, r = _post(client, f'/api/cure-runs/{rid}/report',
                 json={'content': '<html>x</html>', 'summary': {'a': 1}})
    assert r == {'ok': True, 'reportId': rid}
    code, r = _get(client, f'/api/cure-runs/{rid}/report')
    assert code == 200
    assert r == {'ok': True, 'content': '<html>x</html>', 'summary': {'a': 1}, 'format': 'html'}


def test_phase_timing_records(client):
    _, r = _post(client, '/api/cure-runs/run-x/phase', json={'process': 'heating'})
    assert r['ok'] is False
    _, r = _post(client, '/api/cure-runs/run-x/phase',
                 json={'process': 'heating', 'seconds': 12, 'targetTemp': 50})
    assert r['ok'] is True and r['count'] >= 1
    _, rows = _get(client, '/api/phase-timings')
    assert rows[-1]['run'] == 'run-x' and rows[-1]['seconds'] == 12


# ------------------------------------------------------- misc routes -------
def test_system_version(client):
    code, v = _get(client, '/api/system/version')
    assert code == 200
    assert v['appVersion'] not in ('', 'unknown')
    assert v['python'].startswith('3.')


def test_network_status_shape(client):
    code, n = _get(client, '/api/network/status')
    assert code == 200
    for k in ('connected', 'ip', 'mac', 'gateway', 'interfaces', 'internet'):
        assert k in n


def test_diagnostics_and_bofa_rgb(client):
    _, r = _post(client, '/api/diagnostics/fan-test?fan=chamber_intake')
    assert r['ok'] is True and r['rpm'] == 2850
    _, r = _post(client, '/api/diagnostics/led-test')
    assert r['ok'] is True and len(r['results']) == 4
    _, r = _post(client, '/api/bofa?on=1')
    assert r['ok'] is True
    assert _get(client, '/api/state')[1]['bofaOn'] is True
    _post(client, '/api/bofa?on=0')
    _, r = _post(client, '/api/rgb?on=1&color=purple')
    assert r['ok'] is True


def test_cloud_config_requires_url_and_key(client):
    code, r = _post(client, '/api/cloud/config', json={'url': 'http://x'})
    assert code == 400 and r['ok'] is False


def test_ui_catch_all(client, app_module):
    r = client.get('/')
    if os.path.exists(os.path.join(app_module.DIST_DIR, 'index.html')):
        assert r.status_code == 200
        assert b'<html' in r.data.lower() or b'<!doctype' in r.data.lower()
    else:
        assert r.status_code == 404
        assert r.get_json()['ok'] is False
    # unknown non-file path -> index.html (SPA) or 404 json
    r2 = client.get('/some/spa/route')
    assert r2.status_code == r.status_code
    # /api/* rules win over the catch-all
    r3 = client.get('/api/state')
    assert r3.status_code == 200 and r3.get_json()['hwSource'] == 'simulation'


def test_unknown_api_path_is_json_404(client):
    # An unknown /api/* path must not fall through to index.html (SPA)
    r = client.get('/api/nope')
    assert r.status_code == 404
    assert r.get_json() == {'ok': False, 'code': 404,
                            'message': 'Unknown API endpoint'}
    r2 = client.get('/api/nope/deeper')
    assert r2.status_code == 404 and r2.get_json()['ok'] is False


def test_werkzeug_access_log_silenced_by_default(app_module):
    # SCURE_ACCESS_LOG unset -> the per-request access log is at WARNING
    import logging
    assert 'SCURE_ACCESS_LOG' not in os.environ
    assert logging.getLogger('werkzeug').level == logging.WARNING
