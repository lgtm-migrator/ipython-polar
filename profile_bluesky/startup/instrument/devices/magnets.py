"""
Magnet motors
"""

__all__ = [
    'mag6t',
    ]

from ..session_logs import logger
logger.info(__file__)

from ophyd import Component, Device, EpicsMotor, FormattedComponent
from .lakeshore import lakeshore_336

## Magnet and sample motors ##
class Magnet6T(Device):

    ## Motors ##
    tabth = Component(EpicsMotor,'m53', labels=('motor','6T magnet'))  # 4T Mag Th
    tabx = Component(EpicsMotor,'m49', labels=('motor','6T magnet'))  # 4T MagTab X
    taby = Component(EpicsMotor,'m50', labels=('motor','6T magnet'))  # 4T MagTab Y

    tabth2 = Component(EpicsMotor,'m56', labels=('motor','6T magnet'))  # AMIMagnetPhi
    tabz2 = Component(EpicsMotor,'m51', labels=('motor','6T magnet'))  # AMIMagnetZ
    tabx2 = Component(EpicsMotor,'m52', labels=('motor','6T magnet'))  # AMIMagenetX

    sampy = Component(EpicsMotor,'m63', labels=('motor','6T magnet'))  # CIATRA
    sampth = Component(EpicsMotor,'m58', labels=('motor','6T magnet'))  # CIA ROT

    Tvaporizer = None
    Tsample = None


mag6t = Magnet6T('4iddx:',name='6T magnet')
# Tvaporizer = lakeshore_336.loop1
# Tsample = lakeshore_336.loop2

# TODO: Is it ok to add the lakeshores here?
# TODO: should we add the magnet field controls here?
