"""
initialize the bluesky framework
"""

__all__ = [
    "bec",
    "bp",
    "bpp",
    "bps",
    "callback_db",
    "db",
    "np",
    "peaks",
    "RE",
    "sd",
    "summarize_plan",
]

from ..session_logs import logger

logger.info(__file__)

from bluesky import RunEngine
from bluesky import SupplementalData
from bluesky.callbacks.best_effort import BestEffortCallback
from bluesky.callbacks.broker import verify_files_saved
from bluesky.magics import BlueskyMagics
from bluesky.simulators import summarize_plan
from bluesky.utils import PersistentDict
from bluesky.utils import ProgressBarManager
from bluesky.utils import ts_msg_hook
from IPython import get_ipython
from ophyd.signal import EpicsSignalBase
import databroker
import os
import warnings


# convenience imports
import bluesky.plans as bp
import bluesky.plan_stubs as bps
import bluesky.preprocessors as bpp
import numpy as np


# Set up a RunEngine and use metadata-backed PersistentDict
RE = RunEngine({})
RE.md = PersistentDict(
    os.path.join(os.environ["HOME"], ".config", "Bluesky_RunEngine_md")
)

# keep track of callback subscriptions
callback_db = {}

# Connect with mongodb database.
db = databroker.catalog["mongodb_config"]

# Subscribe metadatastore to documents.
# If this is removed, data is not saved to metadatastore.
callback_db["db"] = RE.subscribe(db.insert)

# Set up SupplementalData.
sd = SupplementalData()
RE.preprocessors.append(sd)

# Add a progress bar.
pbar_manager = ProgressBarManager()
RE.waiting_hook = pbar_manager

# Register bluesky IPython magics.
get_ipython().register_magics(BlueskyMagics)

# Set up the BestEffortCallback.
bec = BestEffortCallback()
callback_db["bec"] = RE.subscribe(bec)
peaks = bec.peaks  # just an alias, for less typing
bec.disable_baseline()

# At the end of every run, verify that files were saved and
# print a confirmation message.
# _prv_ = RE.subscribe(post_run(verify_files_saved), 'stop')
# callback_db['post_run_verify'] = _prv_

# Uncomment the following lines to turn on
# verbose messages for debugging.
# ophyd.logger.setLevel(logging.DEBUG)

# diagnostics
# RE.msg_hook = ts_msg_hook

# set default timeout for all EpicsSignal connections & communications
try:
    EpicsSignalBase.set_defaults(
        auto_monitor=True,
        timeout=60,
        write_timeout=60,
        connection_timeout=5,
    )
except Exception as exc:
    warnings.warn(
        "ophyd version is old, upgrade to 1.6.0+ "
        "to get set_defaults() method"
    )
    EpicsSignalBase.set_default_timeout(timeout=10, connection_timeout=5)
