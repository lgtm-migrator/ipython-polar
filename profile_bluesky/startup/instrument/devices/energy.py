"""
Beamline energy
"""
__all__ = ['energy']

from ophyd import Signal
from ophyd.status import Status, AndStatus, wait as status_wait
from ..framework import sd
from .monochromator import mono
from .aps_source import undulator
from .phaseplates import pr1, pr2, pr3
from ..session_logs import logger
logger.info(__file__)


class EnergySignal(Signal):

    """
    Beamline energy.
    Here it is setup so that the monochromator is the beamline energy, but note
    that this can be changed.
    """
    def get(self, **kwargs):
        """ Uses the mono as the standard beamline energy. """
        self._readback = mono.energy.readback.get(**kwargs)
        return self._readback

    def set(self, position, *, wait=False, timeout=None, settle_time=None,
            moved_cb=None):

        # In case nothing needs to be moved, just create a finished status
        status = Status()
        status.set_finished()

        # Mono
        if abs(self.get()-position) > mono.energy.tolerance.get():
            mono_status = mono.energy.set(
                position, wait=wait, timeout=timeout, moved_cb=moved_cb
            )
            status = AndStatus(status, mono_status)

        # Phase retarders
        for pr in [pr1, pr2, pr3]:
            if pr.tracking.get():
                pr_status = pr.energy.move(
                    position, wait=wait, timeout=timeout, moved_cb=moved_cb
                )
                status = AndStatus(status, pr_status)

        # Undulator
        if undulator.downstream.tracking.get():
            und_pos = position + undulator.downstream.energy.offset.get()
            und_status = undulator.downstream.energy.move(
                und_pos, wait=wait, timeout=timeout, moved_cb=moved_cb
            )
            status = AndStatus(status, und_status)

        if wait:
            status_wait(status)

        return status

    def stop(self, *, success=False):
        """
        Stops only energy devices that are tracking.
        """
        mono.energy.stop(success=success)
        for positioner in [pr1, pr2, pr3, undulator.downstream]:
            if positioner.tracking.get():
                positioner.energy.stop(success=success)


energy = EnergySignal(name='energy', value=10, kind='hinted')
sd.baseline.append(energy)
