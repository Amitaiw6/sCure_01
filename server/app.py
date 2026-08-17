#!/usr/bin/env python3
"""
sCure Hardware API Server (Python)
Runs on Raspberry Pi CM5.

Architecture:
    React UI (frontend) → Python Flask API → io_bridge → io_controller
    (off-Pi / no IO board: built-in simulation, see hardware_controller.py)

Modules: hardware_controller.py (HardwareController), storage.py (JSON
file stores, ComponentCounters), cloud_sync.py (CloudSync). This file owns
the routes, the wiring/construction order and the atexit registrations.

Install:
    pip install flask flask-cors

Run:
    sudo python3 app.py
    (sudo needed for GPIO/reboot/shutdown)
"""

import os
import sys
import atexit
import signal
import logging
import subprocess
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

from hardware_controller import HardwareController
from storage import (DATA_DIR, PRINT_HISTORY_FILE, PHASE_TIMINGS_FILE,
                     history_lock, load_json_file, save_json_file,
                     load_user_materials, save_user_materials,
                     CureFileStore, ComponentCounters)
from cloud_sync import CloudSync

# PostgreSQL data layer (print data, released materials, cure reports).
# Safe to import without a DB / driver — falls back to JSON files (see db.available()).
try:
    import db
except Exception as _e:  # pragma: no cover
    db = None
    print(f"[DB] data layer unavailable: {_e}")

app = Flask(__name__)
CORS(app)

# Werkzeug logs every request at INFO; the UI polls /api/state at 1 Hz, so that
# is ~86k lines/day into journald (Pi) / scure-desktop.log (desktop.py, which
# imports this module). Keep only warnings unless SCURE_ACCESS_LOG=1.
if not os.environ.get('SCURE_ACCESS_LOG'):
    logging.getLogger('werkzeug').setLevel(logging.WARNING)


def run(cmd, timeout=15):
    """Run a shell command and return its stripped stdout ('' on failure)."""
    try:
        out = subprocess.run(cmd, shell=True, capture_output=True,
                             text=True, timeout=timeout)
        return (out.stdout or '').strip()
    except Exception as e:  # noqa: BLE001 - diagnostics must never raise
        print(f"[SYS] command failed ({cmd}): {e}")
        return ''

# Real IO-board drivers (io_controller/ at the repo root), via the bridge.
# Off-Pi (no I2C / smbus2) the bridge reports unavailable and the simulation
# below keeps serving the UI.
io_bridge = None
try:
    from io_bridge import IOBridge
    _bridge = IOBridge()
    if _bridge.available:
        io_bridge = _bridge
        print("[API] IO board connected (io_controller bridge)")
    else:
        print(f"[API] IO board not available ({_bridge.error}) - simulation mode")
except Exception as _e:  # pragma: no cover
    print(f"[API] IO bridge failed to load: {_e} - simulation mode")

if io_bridge is not None:
    atexit.register(io_bridge.shutdown)   # everything OFF when the API exits


# ============================================================
# Hardware abstraction (hardware_controller.py) - IOBridge or simulation
# ============================================================
hw = HardwareController(io_bridge)


# ============================================================
# Component runtime counters (storage.ComponentCounters, real ON-hours)
# ============================================================
counters = ComponentCounters(os.path.join(DATA_DIR, 'component_counters.json'),
                             hw.get_state)

atexit.register(counters.flush)

# ============================================================
# API Endpoints
# (Print data, released materials and cure data are managed in PostgreSQL — db.py.)
# ============================================================

@app.route('/api/state', methods=['GET'])
def get_state():
    """Get current hardware state - polled by frontend"""
    state = hw.get_state()
    state['counters'] = counters.hours()
    state['cloudSync'] = cloud_sync.status()
    return jsonify(state)


@app.route('/api/network/status', methods=['GET'])
def network_status():
    """Get network info - IP, MAC, gateway, interfaces"""
    info = {
        'connected': True,
        'ip': '0.0.0.0',
        'mac': '00:00:00:00:00:00',
        'gateway': '',
        'interfaces': [],
    }
    try:
        # LAN IP — eth0 ONLY. `hostname -I` must not be used here: it also
        # lists the WireGuard/VPN address, which stays assigned when the
        # cable is pulled and kept `connected` green forever.
        eth_ip = run("ip -4 -j addr show eth0 2>/dev/null")
        if eth_ip:
            import json as _json
            try:
                for iface in _json.loads(eth_ip):
                    for a in iface.get('addr_info', []):
                        if a.get('family') == 'inet' and a.get('local'):
                            info['ip'] = a['local']
                            break
            except Exception:            # noqa: BLE001 - unparsable ip output
                pass
        if info['ip'] == '0.0.0.0' and not run("ip link show eth0 2>/dev/null"):
            # no eth0 on this device (e.g. dev laptop): old generic behavior
            info['ip'] = run("hostname -I | awk '{print $1}'") or '0.0.0.0'

        # Physical link state: /sys carrier is 1 only when a cable is
        # actually plugged in and the link is up.
        carrier = run("cat /sys/class/net/eth0/carrier 2>/dev/null")

        # Get MAC
        result = run("cat /sys/class/net/eth0/address 2>/dev/null || echo '00:00:00:00:00:00'")
        info['mac'] = result

        # Get gateway
        result = run("ip route | grep default | awk '{print $3}'")
        info['gateway'] = result or ''

        # Get interfaces
        ifaces = run("ip -j addr show 2>/dev/null")
        if ifaces:
            import json as _json
            for iface in _json.loads(ifaces):
                addrs = [a.get('local', '') for a in iface.get('addr_info', []) if a.get('family') == 'inet']
                info['interfaces'].append({
                    'name': iface.get('ifname', ''),
                    'status': 'UP' if 'UP' in iface.get('flags', []) else 'DOWN',
                    'ip': addrs[0] if addrs else '',
                })

        # Connected = the wired link is physically up AND eth0 has an IPv4.
        # (carrier '' = no eth0 on this device: fall back to IP presence only)
        has_ip = info['ip'] != '0.0.0.0'
        info['connected'] = has_ip and (carrier == '1' or carrier == '')
    except Exception as e:
        info['connected'] = False
        info['code'] = 9084               # NETWORK_STATUS_UNAVAILABLE
        print(f"[NET] Error getting network status: {e}")

    # Live internet reachability from the automatic background watch
    # (io_bridge StatusLeds._net_watch). 'connected' above = LAN/IP level;
    # 'internet' = the machine actually reaches the outside world.
    if io_bridge is not None and getattr(io_bridge, 'status_leds', None):
        info['internet'] = bool(io_bridge.status_leds._internet_ok)
    else:
        info['internet'] = info['connected']   # simulation: mirror LAN state

    return jsonify(info)


@app.route('/api/network/diagnostics', methods=['POST'])
def network_diagnostics():
    """Run network diagnostic tool"""
    tool = request.json.get('tool', 'ping')
    address = request.json.get('address', '8.8.8.8')

    cmd_map = {
        'ping': f'ping -c 4 -W 3 {address}',
        'traceroute': f'traceroute -m 15 -w 3 {address}',
        'nslookup': f'nslookup {address}',
    }

    cmd = cmd_map.get(tool)
    if not cmd:
        return jsonify({'ok': False, 'code': 9080, 'result': 'Unknown tool'})

    try:
        result = run(cmd, timeout=45)
        return jsonify({'ok': True, 'result': result})
    except Exception as e:
        return jsonify({'ok': False, 'code': 9085, 'result': str(e)})


@app.route('/api/network/static', methods=['POST'])
def network_static():
    """Apply a static-IP (or DHCP) configuration to eth0 via NetworkManager."""
    d = request.get_json(silent=True) or {}
    use_dhcp = bool(d.get('dhcp'))
    ip, gateway = d.get('ip', ''), d.get('gateway', '')
    subnet, dns = d.get('subnet', '255.255.255.0'), d.get('dns', '')
    if not _on_device():
        return jsonify({'ok': True, 'message': 'Network config simulated (off-device)'})
    try:
        conn = run("nmcli -t -f NAME,DEVICE connection show --active | grep ':eth0' | cut -d: -f1") or 'eth0'
        if use_dhcp:
            run(f'nmcli connection modify "{conn}" ipv4.method auto ipv4.addresses "" ipv4.gateway "" ipv4.dns ""')
        else:
            # subnet mask -> prefix length
            prefix = sum(bin(int(o)).count('1') for o in subnet.split('.')) if subnet else 24
            run(f'nmcli connection modify "{conn}" ipv4.method manual '
                f'ipv4.addresses {ip}/{prefix} ipv4.gateway {gateway}'
                + (f' ipv4.dns {dns}' if dns else ''))
        run(f'nmcli connection up "{conn}"', timeout=30)
        return jsonify({'ok': True, 'message': 'Network configuration applied'})
    except Exception as e:
        return jsonify({'ok': False, 'code': 9084, 'message': str(e)})


def _db_on():
    return db is not None and db.available()


def _require_db():
    return jsonify({'ok': False, 'message': 'Database not configured (set DATABASE_URL)'}), 503


# --- Persistent user-program store: storage.py (JSON file, atomic writes) --

@app.route('/api/materials/presets', methods=['GET'])
def get_preset_materials():
    """System-provided material programs (presets), from Postgres."""
    if not _db_on():
        return _require_db()          # UI falls back to its bundled presets
    return jsonify(db.get_materials(presets_only=True))


# --- Durable file store for histories: storage.CureFileStore ---------------
_cure_files = CureFileStore()


# --- Data access shared by the routes and the cloud agent -----------------
# Postgres when configured (db.py), else the durable JSON files on disk
# (storage.py, survive power-off).
def _programs():
    return db.get_materials(presets_only=False) if _db_on() \
        else load_user_materials()


def _save_programs(mats):
    if _db_on():
        db.replace_user_materials(mats)
    else:
        save_user_materials(mats)


def _prints():
    if _db_on():
        return db.get_print_history()
    with history_lock:
        return load_json_file(PRINT_HISTORY_FILE, [])


def _save_prints(logs):
    if _db_on():
        db.replace_print_history(logs)
    else:
        with history_lock:
            save_json_file(PRINT_HISTORY_FILE, logs)


def _cure_list():
    return db.get_cure_history() if _db_on() else _cure_files.list()


@app.route('/api/materials/user', methods=['GET'])
def get_user_materials():
    """User-created work programs."""
    return jsonify(_programs())


@app.route('/api/materials/user', methods=['POST'])
def save_all_user_materials():
    """Save all user work programs (full replace)."""
    _save_programs(request.json or [])
    return jsonify({'ok': True})


# ============================================================
# Cloud sync agent (cloud_sync.CloudSync -> cloud/portal.py)
# ============================================================
def _make_cloud_sync():
    return CloudSync(DATA_DIR, hw.get_state, counters,
                     get_programs=_programs,
                     put_programs=_save_programs,
                     get_prints=_prints,
                     put_prints=_save_prints,
                     list_cures=_cure_list)


cloud_sync = _make_cloud_sync()


@app.route('/api/cloud/config', methods=['POST'])
def cloud_config():
    """Write the cloud-portal sync config (server/data/cloud.json).

    The server runs as root, so this is the supported way to configure the
    agent (the data dir is not writable by the desktop user). If the agent
    is not yet running it starts immediately; if it was already running with
    an old config, a server restart applies the new one.
    """
    global cloud_sync
    d = request.get_json(silent=True) or {}
    if not (d.get('url') and d.get('key')):
        return jsonify({'ok': False, 'message': 'url and key required'}), 400
    os.makedirs(DATA_DIR, exist_ok=True)
    cfg = {'url': d['url'], 'key': d['key'],
           'name': d.get('name', 'CureBox'),
           'interval': d.get('interval', 10)}
    save_json_file(os.path.join(DATA_DIR, 'cloud.json'), cfg)
    if cloud_sync.enabled:
        return jsonify({'ok': True,
                        'message': 'Config saved - restart to apply (agent already running)'})
    cloud_sync = _make_cloud_sync()       # starts the agent with the new config
    return jsonify({'ok': True, 'message': 'Cloud sync agent started'})


@app.route('/api/print-history', methods=['GET'])
def get_print_history():
    """Print history (received prints)."""
    return jsonify(_prints())


@app.route('/api/print-history', methods=['POST'])
def save_print_history():
    """Save print history (full replace)."""
    _save_prints(request.json or [])
    return jsonify({'ok': True})


# ---- Cure runs, telemetry & the persisted cure report --------------------

@app.route('/api/cure-history', methods=['GET'])
def cure_history_list():
    """Cure History (§8)."""
    return jsonify(_cure_list())


@app.route('/api/cure-runs/<ext_id>/start', methods=['POST'])
def cure_run_start(ext_id):
    d = request.get_json(silent=True) or {}
    if _db_on():
        db.start_cure_run(ext_id, d.get('materialName'), d.get('steps'),
                          d.get('phases'), d.get('targetTemp'), d.get('serialNumber'))
    else:
        _cure_files.start(ext_id, d)
    return jsonify({'ok': True})


@app.route('/api/cure-runs/<ext_id>/telemetry', methods=['POST'])
def cure_run_telemetry(ext_id):
    sample = request.get_json(silent=True) or {}
    if _db_on():
        ok = db.record_telemetry(ext_id, sample)
    else:
        ok = _cure_files.telemetry(ext_id, sample)
    return jsonify({'ok': ok})


@app.route('/api/cure-runs/<ext_id>/finish', methods=['POST'])
def cure_run_finish(ext_id):
    d = request.get_json(silent=True) or {}
    if _db_on():
        ok = db.finish_cure_run(ext_id, d.get('status', 'completed'), d.get('stepsCompleted'))
    else:
        ok = _cure_files.finish(ext_id, d.get('status', 'completed'), d.get('stepsCompleted'))
    return jsonify({'ok': ok})


@app.route('/api/cure-runs/<ext_id>/report', methods=['POST'])
def cure_run_report_save(ext_id):
    """Persist a generated cure report for a run."""
    d = request.get_json(silent=True) or {}
    if _db_on():
        rid = db.save_report(ext_id, d.get('content'), d.get('summary'), d.get('format', 'html'))
    else:
        rid = _cure_files.save_report(ext_id, d)
    return jsonify({'ok': True, 'reportId': rid})


@app.route('/api/cure-runs/<ext_id>/report', methods=['GET'])
def cure_run_report_get(ext_id):
    rep = db.get_report(ext_id) if _db_on() else _cure_files.get_report(ext_id)
    if not rep:
        return jsonify({'ok': False, 'message': 'No report'}), 404
    return jsonify({'ok': True, **rep})


# ---- Real phase-timing analytics ------------------------------------------
# Every phase the UI completes reports its TRUE wall-clock duration here -
# including the ramp time the program's step list does not account for. The
# records accumulate in server/data/phase_timings.json (same durable folder
# as everything else) and are the raw data for estimating what each program
# REALLY takes: heating rate to each target, drying/cure holds, cooling time.
# File: storage.PHASE_TIMINGS_FILE


@app.route('/api/phase-timings', methods=['GET'])
def phase_timings_list():
    """All collected phase timings (newest last)."""
    with history_lock:
        return jsonify(load_json_file(PHASE_TIMINGS_FILE, []))


@app.route('/api/cure-runs/<ext_id>/phase', methods=['POST'])
def cure_run_phase(ext_id):
    """Record one finished phase's real timing (fire-and-forget from the UI)."""
    d = request.get_json(silent=True) or {}
    if not d.get('process') or d.get('seconds') is None:
        return jsonify({'ok': False, 'message': 'process and seconds required'}), 400
    rec = {
        'run': ext_id,
        'program': d.get('program'),
        'step': d.get('step'),
        'process': d.get('process'),
        'targetTemp': d.get('targetTemp'),
        'plannedMin': d.get('plannedMin'),      # what the program asked for
        'startedAt': d.get('startedAt'),
        'endedAt': d.get('endedAt'),
        'seconds': d.get('seconds'),            # what it REALLY took
        'rampSeconds': d.get('rampSeconds'),    # part of `seconds` spent ramping
        'tempStart': d.get('tempStart'),
        'tempEnd': d.get('tempEnd'),
    }
    with history_lock:
        rows = load_json_file(PHASE_TIMINGS_FILE, [])
        rows.append(rec)
        save_json_file(PHASE_TIMINGS_FILE, rows)
    return jsonify({'ok': True, 'count': len(rows)})


def _on_device():
    """True when running on the machine itself (Pi / any Linux host)."""
    return sys.platform.startswith('linux')


@app.route('/api/system/reboot', methods=['POST'])
def reboot():
    print("[SYSTEM] Rebooting...")
    if not _on_device():
        return jsonify({'ok': True, 'message': 'Reboot simulated'})
    subprocess.Popen(['sudo', 'reboot'], stdout=subprocess.DEVNULL)
    return jsonify({'ok': True, 'message': 'Rebooting...'})


@app.route('/api/system/shutdown', methods=['POST'])
def shutdown():
    print("[SYSTEM] Shutting down...")
    if not _on_device():
        return jsonify({'ok': True, 'message': 'Shutdown simulated'})
    subprocess.Popen(['sudo', 'shutdown', '-h', 'now'], stdout=subprocess.DEVNULL)
    return jsonify({'ok': True, 'message': 'Shutting down...'})


@app.route('/api/door/open', methods=['POST'])
def door_open():
    hw.open_door()
    return jsonify({'ok': True, 'message': 'Door opened'})


@app.route('/api/door-abort/ack', methods=['POST'])
def door_abort_ack():
    """The user tapped 'Understood' on the Err 6016 alert - clear the abort
    flag so the RGB status strip returns from red to the normal color."""
    hw.ack_door_abort()
    return jsonify({'ok': True, 'message': 'Door abort acknowledged'})


@app.route('/api/chamber/temperature', methods=['POST'])
def set_temperature():
    # Same bounds as the driver (heating.target_min=30): anything below is
    # silently clamped up by the control loop, so reject it here instead.
    target = float(request.args.get('target', 25))
    if not (30 <= target <= 80):
        return jsonify({'ok': False, 'code': 7001,
                        'message': f'Invalid target {target} (30-80°C)'})
    ok, why = hw.set_target_temp(target)
    return jsonify({'ok': ok, 'message': why or f'Target set to {target}°C'})

@app.route('/api/chamber/stop', methods=['POST'])
def stop_heating():
    hw.stop_heating()
    return jsonify({'ok': True, 'message': 'Heating stopped'})


@app.route('/api/fans/<fan>', methods=['POST'])
def set_fan(fan):
    speed = int(request.args.get('speed', 0))
    hw.set_fan_speed(fan, speed)
    return jsonify({'ok': True, 'message': f'{fan} set to {speed}%'})


@app.route('/api/damper/<action>', methods=['POST'])
def damper(action):
    hw.set_damper(action == 'open')
    return jsonify({'ok': True, 'message': f'Damper {"opened" if action == "open" else "closed"}'})


# ============================================================
# Cure operation functions (one endpoint per recipe process)
# Each step is defined only by process + (target temp / UV intensity /
# UV wavelength / cooling mode). There is NO user-configured time — the
# function decides when its process is complete.
#
# Ranges mirror the REAL driver limits (io_controller/components.json):
#   heating.target_min = 30°C  → heat/dry/cure targets are 30-80°C
#   led_power.min_intensity = 10 → below 10% the LEDs stay dark
# Error codes come from the central registry (public/config/errors.json).
# ============================================================
HEAT_TARGET_MIN = 30    # io_controller heating.target_min — heater refuses below this
TEMP_MAX = 80
COOL_TARGET_MIN = 20
UV_INTENSITY_MIN = 10   # io_controller led_power.min_intensity — LEDs off below this

ERR_INVALID_TARGET_TEMP = 7001
ERR_INVALID_UV_INTENSITY = 7002
ERR_INVALID_COOLING_MODE = 7003
ERR_PRECURE_CHECK_FAILED = 6015


def _valid_heat_temp(t):
    return HEAT_TARGET_MIN <= t <= TEMP_MAX

def _valid_cool_temp(t):
    return COOL_TARGET_MIN <= t <= TEMP_MAX

def _valid_intensity(i):
    return UV_INTENSITY_MIN <= i <= 100

def _hw_result(ok, why, success_msg):
    """Uniform cure-route response; hardware refusals carry code 6015."""
    if ok:
        return jsonify({'ok': True, 'message': success_msg})
    return jsonify({'ok': False, 'code': ERR_PRECURE_CHECK_FAILED,
                    'message': why or 'Hardware refused the operation'})

@app.route('/api/cure/heat', methods=['POST'])
def cure_heat():
    target = float(request.args.get('target', 60))
    if not _valid_heat_temp(target):
        return jsonify({'ok': False, 'code': ERR_INVALID_TARGET_TEMP,
                        'message': f'Invalid target {target} ({HEAT_TARGET_MIN}-{TEMP_MAX}°C)'})
    ok, why = hw.heat_to_target_temperature(target)
    return _hw_result(ok, why, f'Heating to {target}°C')

@app.route('/api/cure/dry', methods=['POST'])
def cure_dry():
    target = float(request.args.get('target', 60))
    if not _valid_heat_temp(target):
        return jsonify({'ok': False, 'code': ERR_INVALID_TARGET_TEMP,
                        'message': f'Invalid target {target} ({HEAT_TARGET_MIN}-{TEMP_MAX}°C)'})
    ok, why = hw.dry_to_target_temperature(target)
    return _hw_result(ok, why, f'Drying to {target}°C')

@app.route('/api/cure/cure-405', methods=['POST'])
def cure_405():
    target = float(request.args.get('target', 60))
    intensity = int(request.args.get('intensity', 30))
    if not _valid_heat_temp(target):
        return jsonify({'ok': False, 'code': ERR_INVALID_TARGET_TEMP,
                        'message': f'Invalid target {target} ({HEAT_TARGET_MIN}-{TEMP_MAX}°C)'})
    if not _valid_intensity(intensity):
        return jsonify({'ok': False, 'code': ERR_INVALID_UV_INTENSITY,
                        'message': f'Invalid intensity {intensity} ({UV_INTENSITY_MIN}-100%)'})
    ok, why = hw.cure_uv_405(target, intensity)
    return _hw_result(ok, why, f'Cure UV 405nm @ {intensity}%, {target}°C')

@app.route('/api/cure/cure-450', methods=['POST'])
def cure_450():
    target = float(request.args.get('target', 60))
    intensity = int(request.args.get('intensity', 30))
    if not _valid_heat_temp(target):
        return jsonify({'ok': False, 'code': ERR_INVALID_TARGET_TEMP,
                        'message': f'Invalid target {target} ({HEAT_TARGET_MIN}-{TEMP_MAX}°C)'})
    if not _valid_intensity(intensity):
        return jsonify({'ok': False, 'code': ERR_INVALID_UV_INTENSITY,
                        'message': f'Invalid intensity {intensity} ({UV_INTENSITY_MIN}-100%)'})
    ok, why = hw.cure_uv_450(target, intensity)
    return _hw_result(ok, why, f'Bleaching UV 450nm @ {intensity}%, {target}°C')

@app.route('/api/cure/cool', methods=['POST'])
def cure_cool():
    target = float(request.args.get('target', 25))
    mode = request.args.get('mode', 'medium')
    if not _valid_cool_temp(target):
        return jsonify({'ok': False, 'code': ERR_INVALID_TARGET_TEMP,
                        'message': f'Invalid target {target} ({COOL_TARGET_MIN}-{TEMP_MAX}°C)'})
    if mode not in ('fast', 'medium', 'slow'):
        return jsonify({'ok': False, 'code': ERR_INVALID_COOLING_MODE,
                        'message': f'Invalid cooling mode {mode}'})
    ok, why = hw.cool_to_target_temperature(target, mode)
    return _hw_result(ok, why, f'Cooling ({mode}) to {target}°C')

@app.route('/api/cure/nitrogen', methods=['POST'])
def cure_nitrogen():
    """Open/close the N2 purge valve. ?on=1 opens, ?on=0 closes."""
    on = request.args.get('on', '1') not in ('0', 'false', 'off')
    ok, why = hw.set_nitrogen(on)
    return _hw_result(ok, why, f'Nitrogen valve {"opened" if on else "closed"}')

@app.route('/api/cure/stop', methods=['POST'])
def cure_stop():
    """Stop all cure outputs. The heater fan always runs its cooldown run-on
    after heating (30% / 10 min); only the door-open safety abort skips it.
    ?immediate=1 is kept for compatibility (same behavior)."""
    immediate = request.args.get('immediate', '0') not in ('0', 'false', '')
    hw.stop_all(immediate)
    return jsonify({'ok': True, 'message': 'All cure outputs stopped'
                    + (' immediately' if immediate else '')})


@app.route('/api/uv', methods=['POST'])
def set_uv_output():
    """Standalone UV control (diagnostics): ?on=1&intensity=30&wavelength=405."""
    on = request.args.get('on', '0') not in ('0', 'false', 'off')
    intensity = int(request.args.get('intensity', 30))
    wavelength = int(request.args.get('wavelength', 405))
    if on and not _valid_intensity(intensity):
        return jsonify({'ok': False, 'code': ERR_INVALID_UV_INTENSITY,
                        'message': f'Invalid intensity {intensity} ({UV_INTENSITY_MIN}-100%)'})
    if on and wavelength not in (405, 450):
        return jsonify({'ok': False, 'message': f'Invalid wavelength {wavelength} (405|450)'})
    ok, why = hw.set_uv(on, intensity, wavelength if on else None)
    return _hw_result(ok, why, f'UV {"on" if on else "off"}')


@app.route('/api/bofa', methods=['POST'])
def set_bofa():
    """BOFA fume-extraction on/off. ?on=1|0"""
    on = request.args.get('on', '1') not in ('0', 'false', 'off')
    ok, why = hw.set_bofa(on)
    return _hw_result(ok, why, f'BOFA {"on" if on else "off"}')


@app.route('/api/rgb', methods=['POST'])
def set_rgb_strip():
    """Manual RGB strip override: ?on=1&color=purple|RRGGBB&brightness=40.
    While on, the automatic status colors pause; ?on=0 hands the strip back."""
    on = request.args.get('on', '1') not in ('0', 'false', 'off')
    color = request.args.get('color', 'white')
    brightness = request.args.get('brightness', type=float)
    ok, why = hw.set_rgb(on, color if on else None, brightness)
    return _hw_result(ok, why, f'RGB {("on: " + color) if on else "off"}')


@app.route('/api/diagnostics/fan-test', methods=['POST'])
def fan_test():
    """Per-fan diagnostic: ?fan=led_cooling|chamber_intake|chamber_heating."""
    fan = request.args.get('fan')
    result = hw.run_fan_test(fan)
    return jsonify({'ok': True, **result})


@app.route('/api/diagnostics/led-test', methods=['POST'])
def led_test():
    result = hw.run_led_test()
    return jsonify({'ok': True, **result})


@app.route('/api/system/export-logs', methods=['POST'])
def export_logs():
    print("[SYSTEM] Exporting logs...")
    try:
        os.system('mkdir -p /media/usb && mount /dev/sda1 /media/usb 2>/dev/null')
        os.system('cp -r /var/log/scure /media/usb/scure-logs-$(date +%Y%m%d) 2>/dev/null')
        os.system('sync && umount /media/usb 2>/dev/null')
        return jsonify({'ok': True, 'message': 'Logs exported to USB'})
    except Exception as e:
        return jsonify({'ok': False, 'code': 9083, 'message': str(e)})


@app.route('/api/system/export-csv', methods=['POST'])
def export_csv_to_usb():
    """Write a generated cure-program CSV to the USB drive connected to the machine."""
    data = request.get_json(silent=True) or {}
    content = data.get('content', '')
    filename = os.path.basename(data.get('filename') or 'untitled.csv')
    if not filename.lower().endswith('.csv'):
        filename += '.csv'
    print(f"[SYSTEM] Exporting CSV '{filename}' to USB...")
    try:
        from updater import find_usb_mount
        usb = find_usb_mount()
        if not usb:
            return jsonify({'ok': False, 'code': 9081,
                            'message': 'No Disk-on-Key found. Please connect a Disk-on-Key (USB drive).'})
        dest = os.path.join(usb, filename)
        with open(dest, 'w', newline='') as f:
            f.write(content)
        os.system('sync')
        return jsonify({'ok': True, 'message': f'Saved {filename} to USB', 'path': dest})
    except Exception as e:
        return jsonify({'ok': False, 'code': 9082, 'message': str(e)})


@app.route('/api/system/export-report', methods=['POST'])
def export_report_to_usb():
    """Write a generated cure-report HTML to the USB drive connected to the machine."""
    data = request.get_json(silent=True) or {}
    content = data.get('content', '')
    filename = os.path.basename(data.get('filename') or 'cure-report.html')
    if not filename.lower().endswith('.html'):
        filename += '.html'
    print(f"[SYSTEM] Exporting report '{filename}' to USB...")
    try:
        from updater import find_usb_mount
        usb = find_usb_mount()
        if not usb:
            return jsonify({'ok': False, 'code': 9081,
                            'message': 'No Disk-on-Key found. Please connect a Disk-on-Key (USB drive).'})
        dest = os.path.join(usb, filename)
        with open(dest, 'w', encoding='utf-8') as f:
            f.write(content)
        os.system('sync')
        return jsonify({'ok': True, 'message': f'Saved {filename} to USB', 'path': dest})
    except Exception as e:
        return jsonify({'ok': False, 'code': 9082, 'message': str(e)})


@app.route('/api/system/version', methods=['GET'])
def system_version():
    """All live version/build info. The single source of truth for the app
    version is the VERSION file at the repo root (bumped per release, with a
    matching entry in public/config/versions.json); everything else is read
    from the machine at call time - nothing here is hardcoded."""
    repo = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), '..'))
    try:
        with open(os.path.join(repo, 'VERSION'), encoding='utf-8') as f:
            app_version = f.read().strip()
    except Exception:                     # noqa: BLE001 - file missing
        app_version = 'unknown'
    return jsonify({
        'appVersion': app_version,
        'gitCommit': run(f'git -C "{repo}" rev-parse --short HEAD') or None,
        'gitDate': run(f'git -C "{repo}" log -1 --format=%cs') or None,
        'lastBoot': run('uptime -s') or None,
        'os': run('. /etc/os-release && echo $PRETTY_NAME') or None,
        'kernel': run('uname -r') or None,
        'python': sys.version.split()[0],
    })


@app.route('/api/system/datetime', methods=['POST'])
def set_datetime():
    """Set the system clock: {date: 'YYYY-MM-DD', time: 'HH:MM'}."""
    d = request.get_json(silent=True) or {}
    date_s, time_s = d.get('date', ''), d.get('time', '')
    import re
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date_s) or \
       not re.fullmatch(r'\d{2}:\d{2}(:\d{2})?', time_s):
        return jsonify({'ok': False, 'message': 'Invalid date/time format'})
    if not _on_device():
        return jsonify({'ok': True, 'message': f'Clock set simulated ({date_s} {time_s})'})
    try:
        run('sudo timedatectl set-ntp false')
        out = subprocess.run(['sudo', 'timedatectl', 'set-time', f'{date_s} {time_s}:00'
                              if len(time_s) == 5 else f'{date_s} {time_s}'],
                             capture_output=True, text=True, timeout=15)
        if out.returncode != 0:
            return jsonify({'ok': False, 'message': out.stderr.strip() or 'set-time failed'})
        return jsonify({'ok': True, 'message': f'Clock set to {date_s} {time_s}'})
    except Exception as e:
        return jsonify({'ok': False, 'message': str(e)})


def _find_update_package():
    """Locate the newest .scu package on USB. Returns (path, error)."""
    try:
        from updater import find_usb_mount, find_update_package
        usb = find_usb_mount()
        if not usb:
            return None, ('No USB drive found', 9081)
        pkg = find_update_package(usb)
        if not pkg:
            return None, ('No .scu update file found on USB', 9087)
        return pkg, None
    except Exception as e:
        return None, (str(e), 9086)


@app.route('/api/system/update/manifest', methods=['GET'])
def update_manifest():
    """Version + SHA-256 of the update package, for UI-side integrity check."""
    pkg, err = _find_update_package()
    if not pkg:
        msg, code = err
        return jsonify({'ok': False, 'code': code, 'message': msg}), 404
    import hashlib
    h = hashlib.sha256()
    with open(pkg, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    version = os.path.basename(pkg)
    try:
        from updater import extract_and_verify, read_manifest
        update_dir, _msg = extract_and_verify(pkg)
        if update_dir:
            version = read_manifest(update_dir).get('version', version)
            import shutil as _sh
            _sh.rmtree(os.path.dirname(update_dir), ignore_errors=True)
    except Exception:  # pragma: no cover - version stays as filename
        pass
    return jsonify({'ok': True, 'version': version, 'sha256': h.hexdigest()})


@app.route('/api/system/update/package', methods=['GET'])
def update_package():
    """Raw update-package bytes (integrity-checked by the UI against the manifest)."""
    pkg, err = _find_update_package()
    if not pkg:
        msg, code = err
        return jsonify({'ok': False, 'code': code, 'message': msg}), 404
    return send_from_directory(os.path.dirname(pkg), os.path.basename(pkg),
                               as_attachment=True)


@app.route('/api/system/update', methods=['POST'])
def update_software():
    print("[SYSTEM] Starting update process...")
    try:
        from updater import run_update
        result = run_update()
        if not result.get('ok'):
            result.setdefault('code',
                              9087 if 'No .scu' in (result.get('message') or '')
                              else 9081 if 'USB' in (result.get('message') or '')
                              else 9086)
        return jsonify(result)
    except ImportError:
        return jsonify({'ok': True, 'message': 'Update simulated', 'steps': []})


# ============================================================
# Built UI (dist/) — served by Flask so one process runs everything.
# All /api/* rules above are static and win over this catch-all.
# ============================================================
DIST_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'dist'))


@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_ui(path):
    if path.startswith('api/'):           # unknown API route: JSON 404, not index.html
        return jsonify({'ok': False, 'code': 404,
                        'message': 'Unknown API endpoint'}), 404
    if path and os.path.exists(os.path.join(DIST_DIR, path)):
        return send_from_directory(DIST_DIR, path)
    if os.path.exists(os.path.join(DIST_DIR, 'index.html')):
        return send_from_directory(DIST_DIR, 'index.html')
    return jsonify({'ok': False,
                    'message': 'UI not built — run `npm run build` in the repo root'}), 404


if __name__ == '__main__':
    # systemctl stop sends SIGTERM; Python's default handler exits WITHOUT
    # running atexit (io_bridge.shutdown -> all outputs OFF, counters.flush).
    # Turn it into SystemExit so those handlers run. Main thread only:
    # desktop.py imports this module from a worker thread, where
    # signal.signal() would raise.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    port = int(os.environ.get('PORT', 3001))
    print(f"[sCure API] Starting on port {port}")
    if io_bridge is not None:
        print("[sCure API] Hardware driver: IO BOARD (io_controller bridge)")
    else:
        print("[sCure API] Hardware driver: SIMULATION")
    if db is not None and db.available():
        try:
            db.init_schema()
            print("[sCure API] Data store: POSTGRES (schema ensured)")
        except Exception as e:
            print(f"[sCure API] Data store: POSTGRES — schema init failed: {e}")
    else:
        print("[sCure API] Data store: JSON files (set DATABASE_URL to use PostgreSQL)")
    app.run(host='0.0.0.0', port=port, debug=False)
