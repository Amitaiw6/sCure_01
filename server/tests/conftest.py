"""
Shared pytest fixtures for the sCure API (server/) tests.

SCURE_DATA_DIR is pointed at a pytest temp dir BEFORE `app` is imported so
the module-level stores (storage.DATA_DIR, ComponentCounters, CureFileStore,
CloudSync) never touch server/data/. Importing app starts the
ComponentCounters daemon thread and (off-Pi) puts HardwareController in
simulation mode.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SERVER_DIR = os.path.join(ROOT, 'server')
IO_DIR = os.path.join(ROOT, 'io_controller')

# Data dir MUST be set before app/storage import (module-level constant).
import tempfile
_DATA_DIR = os.path.join(tempfile.mkdtemp(prefix='scure-pytest-'), 'data')
os.environ['SCURE_DATA_DIR'] = _DATA_DIR

for p in (SERVER_DIR, IO_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture(scope='session')
def data_dir():
    return _DATA_DIR


@pytest.fixture(scope='session')
def app_module():
    import app  # noqa: WPS433 - deliberate late import after env is set
    return app


@pytest.fixture(scope='session')
def client(app_module):
    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as c:
        yield c
