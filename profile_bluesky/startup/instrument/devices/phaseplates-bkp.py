"""
Phase retarders.
"""

from ..framework import sd
from ophyd import Device, EpicsMotor
from ophyd import Component, FormattedComponent
from ophyd import EpicsSignal, EpicsSignalRO, Signal
from ophyd import Kind
from scipy.constants import speed_of_light, Planck
from numpy import arcsin, pi
from .monochromator import mono

# This is here because PRDevice.select_pr has a micron symbol that utf-8
# cannot read. See: https://github.com/bluesky/ophyd/issues/930
from epics import utils3
from ..session_logs import logger

logger.info(__file__)
utils3.EPICS_STR_ENCODING = "latin-1"

__all__ = [
    'pr1', 'pr2', 'pr3', 'pr_setup',
    ]


class ThetaMotor(EpicsMotor):

    def track_theta(self, old_value=None, value=None, **kwargs):
        if value:
            theta = self.convert_energy_to_theta(value)
            # TODO: This does not work when I use mono.energy.put, I don't
            # understand it.
            self.set(theta)
 
    def convert_energy_to_theta(self, energy):
        # lambda in angstroms
        lamb = speed_of_light*Planck*6.241509e15*1e10/energy
        # theta in degrees
        theta = arcsin(lamb/2/self.parent.d_spacing.get())*180./pi
        return theta


# class EnergySignal(Signal):
#     def update_energy(self, old_value=None, value=None, **kwargs):
#         if value:
#             self.put(value)


class PRPzt(Device):
    remote_setpoint = Component(EpicsSignal, 'set_microns.VAL',
                                kind=Kind.omitted)
    remote_readback = Component(EpicsSignalRO, 'microns')

    # TODO: LocalDC readback is usually a bit different from the setpoint,
    # check if tolerance = 0.01 is good.
    # TODO: The value doesnt change in the MEDM screen, not sure why.
    localDC = Component(EpicsSignal, 'DC_read_microns',
                        write_pv='DC_set_microns.VAL', auto_monitor=True,
                        kind=Kind.hinted, tolerance=0.01)

    center = Component(EpicsSignal, 'AC_put_center.A', kind=Kind.config)
    offset_degrees = Component(EpicsSignal, 'AC_put_offset.A',
                               kind=Kind.config)

    offset = Component(Signal, value=0.0, kind=Kind.config)

    servoOn = Component(EpicsSignal, 'servo_ON.PROC', kind=Kind.omitted)
    servoOff = Component(EpicsSignal, 'servo_OFF.PROC', kind=Kind.omitted)
    servoStatus = Component(EpicsSignalRO, 'svo', kind=Kind.config)

    selectDC = FormattedComponent(EpicsSignal,
                                  '4idb:232DRIO:1:OFF_ch{self._prnum}.PROC',
                                  kind=Kind.omitted, put_complete=True)

    selectAC = FormattedComponent(EpicsSignal,
                                  '4idb:232DRIO:1:ON_ch{self._prnum}.PROC',
                                  kind=Kind.omitted, put_complete=True)

    ACstatus = FormattedComponent(EpicsSignalRO, '4idb:232DRIO:1:status',
                                  kind=Kind.config)

    conversion_factor = Component(Signal, value=0.1, kind='config')

    def __init__(self, PV, *args, **kwargs):
        self._prnum = PV.split(':')[-2]
        super().__init__(PV, *args, **kwargs)

    def update_offset_degrees(self, value):
        self.offset_degrees.put(value)

    @offset_degrees.sub_value
    def _update_offset(self, value=0, **kwargs):
        self.offset.put((value / self.conversion_factor.get()))


class PRDeviceBase(Device):

    x = FormattedComponent(EpicsMotor, '{self.prefix}:{_motorsDict[x]}',
                           labels=('motor', 'phase retarders'))

    y = FormattedComponent(EpicsMotor, '{self.prefix}:{_motorsDict[y]}',
                           labels=('motor', 'phase retarders'))

    th = FormattedComponent(ThetaMotor, '{self.prefix}:{_motorsDict[th]}',
                            labels=('motor', 'phase retarders'))

    # energy = Component(EnergySignal, value=10.0, labels=('phase retarders',))
    d_spacing = Component(Signal, value=0, kind='config')
    offset = Component(Signal, value=0, kind='config')

    def __init__(self, PV, name, motorsDict, **kwargs):
        self._motorsDict = motorsDict
        super().__init__(prefix=PV, name=name, **kwargs)
        self._th_cid = None
        # self._energy_cid = None

    def change_tracking(self, onoff):
        if onoff is True:
            # # Move to PR energy of current PR theta
            # energy = (speed_of_light*Planck*6.241509e15*1e10 /
            #           2/self.d_spacing.get() /
            #           sin(self.th.user_readback.get()*pi/180.))
            # self.energy.put(energy)

            # # Turn on theta tracking
            # self._th_cid = self.energy.subscribe(
            #     self.th.update_theta, event_type=self.energy.SUB_VALUE
            #     )

            # # Turn on energy tracking
            # self._energy_cid = mono.energy.subscribe(
            #      self.energy.update_energy,
            #      event_type=mono.energy.SUB_SETPOINT,
            #      run=False
            #      )

            # Turn on tracking
            self._th_cid = mono.energy.subscribe(
                 self.th.track_theta,
                 event_type=mono.energy.SUB_SETPOINT
                 )
        else:
            if not self._th_cid:
                mono.energy.unsubscribe(self._th_cid)
                self._th_cid = None

            # if not self._energy_cid:
            #     mono.energy.unsubscribe(self._energy_cid)
            #     self._energy_cid = None

    def set_energy(self, energy):
        # energy in keV!
        # theta in degrees
        theta = self.th.convert_energy_to_theta(energy)
        self.th.set_current_position(theta)

    def update_offset_degrees(self, value):
        # TODO: Is this function useful?
        self.offset.put(value)


class PRDevice(PRDeviceBase):

    pzt = FormattedComponent(PRPzt, '{self.prefix}:E665:{_prnum}:')
    select_pr = FormattedComponent(EpicsSignal, '{self.prefix}:PRA{_prnum}',
                                   string=True, kind='config')

    def __init__(self, prefix, name, prnum, motorsDict, **kwargs):
        self._prnum = prnum
        super().__init__(prefix, name, motorsDict, **kwargs)

    @select_pr.sub_value
    def _set_d_spacing(self, value=None, **kwargs):
        if isinstance(value, int):
            value = self.select_pr.get()

        spacing_dictionary = {'111': 2.0595, '220': 1.26118}
        plane = value.split('(')[1].split(')')[0]
        self.d_spacing.put(spacing_dictionary[plane])


class PRSetup():
    positioner = None

    def config(self):
        print('Setup of the phase retarders for dichro scans.')
        print('Note that you can only oscillate one phase retarder stack.')

        _positioner = None

        for pr, label in zip([pr1, pr2, pr3], ['PR1', 'PR2', 'PR3']):
            print(' ++ {} ++'.format(label))
            while True:
                track = input('\tTrack? (yes/no): ')
                if track.lower() == 'yes':
                    pr.tracking.put(True)
                    break
                elif track.lower() == 'no':
                    pr.tracking.put(False)
                    break
                else:
                    print("Only yes or no are acceptable answers.")

            if _positioner is None:
                while True:
                    oscillate = input('\tOscillate? (yes/no): ')
                    if oscillate.lower() == 'yes':
                        if pr == pr3:
                            method = 'motor'
                            _positioner = pr.th
                        else:
                            while True:
                                method = input('\tUse motor or PZT? \
                                    (motor/pzt): ')
                                if method.lower() == 'motor':
                                    _positioner = pr.th
                                    break
                                elif method.lower() == 'pzt':
                                    _positioner = pr.pzt.localDC
                                    break
                                else:
                                    print("Only motor or pzt are acceptable\
                                        answers.")
                            while True:
                                try:
                                    _center = float(input('\tPZT center (in\
                                        microns): '))
                                    _positioner.parent.center.put(_center)
                                    break
                                except ValueError:
                                    print('Must be a number.')
                                    pass

                        while True:
                            try:
                                _offset = float(input('\tOffset (in degrees): \
                                    '))
                                _positioner.parent.update_offset_degrees(
                                    _offset)
                                break
                            except ValueError:
                                print('Must be a number.')
                                pass
                        break
                    elif oscillate.lower() == 'no':
                        break
                    else:
                        print("Only yes or no are acceptable answers.")

            else:
                print('\tYou already selected {} to oscillate.'.format(
                    _positioner.name))

        self.positioner = _positioner


pr1 = PRDevice('4idb', 'pr1', 1, {'x': 'm10', 'y': 'm11', 'th': 'm13'})
pr1.pzt.conversion_factor.put(0.001636)
pr1._set_d_spacing('(111)')

pr2 = PRDevice('4idb', 'pr2', 2, {'x': 'm15', 'y': 'm16', 'th': 'm18'})
pr2.pzt.conversion_factor.put(0.0019324)
pr2._set_d_spacing('(111)')

pr3 = PRDeviceBase('4idb', 'pr3', {'x': 'm19', 'y': 'm20', 'th': 'm21'})
pr3.d_spacing.put(3.135)

pr_setup = PRSetup()

sd.baseline.append(pr1)
sd.baseline.append(pr2)
sd.baseline.append(pr3)
