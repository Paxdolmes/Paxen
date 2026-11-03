import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ["PAXEN_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["PAXEN_RUN_WORKERS"] = "0"
os.environ["PAXEN_PROVIDER"] = "sim"
os.environ["PAXEN_SIM_SCENARIO"] = "normal"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from paxen.db import Base, make_engine  # noqa: E402
from paxen.engine import clear_status_cache  # noqa: E402

# Tuesday 3 Nov 2026, 08:20 London (GMT == UTC in November)
MORNING = datetime(2026, 11, 3, 8, 20, tzinfo=timezone.utc)
HOME = (51.5826, -0.0128)  # Walthamstow Village
WORK = (51.5141, -0.1405)  # Regent Street


@pytest.fixture
def session():
    eng = make_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng, expire_on_commit=False)()
    clear_status_cache()
    yield s
    s.close()
