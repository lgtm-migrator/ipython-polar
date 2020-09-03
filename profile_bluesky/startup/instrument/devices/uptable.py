'''
Other motor/counters
'''

__all__ = [
    'uptab'
    ]

from ..session_logs import logger
logger.info(__file__)

from ophyd import Component, MotorBundle, EpicsMotor
from ..framework import sd

class UpTable(MotorBundle):
    y = Component(EpicsMotor, 'm10', labels=('motor','uptable'))  # Uptable Y
    x = Component(EpicsMotor, 'm9', labels=('motor','uptable'))  # Uptable Y

uptab = UpTable('4iddx:',name='uptable')
sd.baseline.append(uptab)
