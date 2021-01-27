""" Vortex with Xspress"""

from ophyd import (EpicsSignal, EpicsSignalRO, DerivedSignal, Signal, Device,
                   Component, FormattedComponent, Kind)
from ophyd.status import AndStatus, Status
from ophyd.signal import SignalRO
from bluesky.plan_stubs import mv
from ..framework import sd

from ..session_logs import logger
logger.info(__file__)


def ev_to_bin(ev):
    '''Convert eV to bin number'''
    return int(ev / 10)


def bin_to_ev(bin_):
    '''Convert bin number to eV'''
    return int(bin_) * 10


class EvSignal(DerivedSignal):
    '''A signal that converts a bin number into electron volts'''
    def __init__(self, parent_attr, *, parent=None, **kwargs):
        bin_signal = getattr(parent, parent_attr)
        super().__init__(derived_from=bin_signal, parent=parent, **kwargs)

    def get(self, **kwargs):
        bin_ = super().get(**kwargs)
        return bin_to_ev(bin_)

    def put(self, ev_value, **kwargs):
        bin_value = ev_to_bin(ev_value)
        return super().put(bin_value, **kwargs)

    def describe(self):
        desc = super().describe()
        desc[self.name]['units'] = 'eV'
        return desc


class TotalCorrectedSignal(SignalRO):
    def get(self, **kwargs):
        value = 0
        for ch_num in range(1, self.parent._num_channels+1):
            channel = getattr(self.parent, f'Ch{ch_num}')
            _dt_factor = channel.dt_factor.get(**kwargs)
            for roi_num in self.parent._enabled_rois:
                roi = getattr(channel.rois, 'roi{:02d}'.format(roi_num))
                value += _dt_factor * roi.total_rbv.get(**kwargs)

        return value


class Xspress3ROI(Device):

    # Bin limits
    bin_low = Component(EpicsSignal, 'MinX', kind='config')
    bin_size = Component(EpicsSignal, 'SizeX', kind='config')

    # Energy limits
    ev_low = Component(EvSignal, parent_attr='bin_low', kind='config')
    ev_size = Component(EvSignal, parent_attr='bin_size', kind='config')

    # Raw total
    total_rbv = Component(EpicsSignalRO, 'Total_RBV', kind='normal')

    # Name
    roi_name = Component(EpicsSignal, 'Name', kind='config')

    # Enable
    enable_flag = Component(EpicsSignal, 'Use', kind='config',
                            put_complete=True, string=True)

    @enable_flag.sub_value
    def _change_kind(self, value=None, **kwargs):
        if value == 'Yes':
            self.kind = Kind.normal
        elif value == 'No':
            self.kind = Kind.omitted

    def enable(self):
        return self.enable_flag.set('Yes')

    def disable(self):
        return self.enable_flag.set('No')

    def clear(self):
        '''Clear and disable this ROI'''
        self.configure('', 0, 0, enable=False)

    def configure(self, name, ev_low, ev_size, enable=True):
        '''Configure the ROI with low and high eV
        Parameters
        ----------
        name : string
            ROI label.
        ev_low : float or int
            Lower edge of ROI in electron volts.
        ev_size : float or int
            Size of ROI in electron volts.
        enable : boolean, optional
            Flag to determine if this ROI should be used.
        '''

        ev_low = int(ev_low)
        ev_size = int(ev_size)

        if ev_low < 0:
            raise ValueError(f'ev_low cannot be < 0, but {ev_low} was entered')
        if ev_size < 0:
            raise ValueError(f'ev_size cannot be < 0, but {ev_size} was '
                             'entered')

        self.roi_name.put(name)
        self.ev_size.put(ev_size)
        self.ev_low.put(ev_low)

        if enable is True:
            self.enable()
        else:
            self.disable()


class ROIDevice(Device):
    # TODO: Using locals() feels like cheating...
    # Make 32 ROIs --> same number as in EPICS support.
    for i in range(1, 33):
        locals()['roi{:02d}'.format(i)] = Component(Xspress3ROI, f'{i}:')

    num_rois = Component(Signal, value=32, kind='config')


class Xspress3Channel(Device):

    rois = FormattedComponent(ROIDevice, '{prefix}MCA{_chnum}ROI:')

    # Timestamp --> it's used to tell when the ROI plugin is done.
    timestamp = FormattedComponent(EpicsSignalRO,
                                   '{prefix}MCA{_chnum}ROI:TimeStamp_RBV',
                                   kind='omitted', auto_monitor=True)

    # SCAs
    clock_ticks = FormattedComponent(EpicsSignalRO,
                                     '{prefix}C{_chnum}SCA0:Value_RBV')

    reset_ticks = FormattedComponent(EpicsSignalRO,
                                     '{prefix}C{_chnum}SCA1:Value_RBV')

    reset_counts = FormattedComponent(EpicsSignalRO,
                                      '{prefix}C{_chnum}SCA2:Value_RBV')

    all_events = FormattedComponent(EpicsSignalRO,
                                    '{prefix}C{_chnum}SCA3:Value_RBV')

    all_good = FormattedComponent(EpicsSignalRO,
                                  '{prefix}C{_chnum}SCA4:Value_RBV')

    pileup = FormattedComponent(EpicsSignalRO,
                                '{prefix}C{_chnum}SCA7:Value_RBV')

    dt_factor = FormattedComponent(EpicsSignalRO,
                                   '{prefix}C{_chnum}SCA8:Value_RBV')

    def __init__(self, *args, chnum, **kwargs):
        # TODO: I don't like how this is currently implemented, but it works.
        self._chnum = chnum
        super().__init__(*args, **kwargs)

    def _status_done(self):

        # Create status that checks when the timestamp updates.
        status = Status(self.timestamp, settle_time=0.01)

        def _set_finished(**kwargs):
            status.set_finished()
            self.timestamp.clear_sub(_set_finished)

        self.timestamp.subscribe(_set_finished, event_type='value', run=False)

        return status

    @property
    def all_rois(self):
        for roi in range(1, self.rois.num_rois.get() + 1):
            yield getattr(self.rois, 'roi{:02d}'.format(roi))

    def set_roi(self, index, ev_low, ev_size, name=None, enable=True):
        '''Set specified ROI to (ev_low, ev_size)
        Parameters
        ----------
        index : int or list of int
            ROI index. It can be passed as an integer or an iterable with
            integers.
        ev_low : int
            low eV setting.
        ev_size : int
            size eV setting.
        name : str, optional
            ROI name, if nothing is passed it will keep the current name.
        enable : boolean
            Flag to enable the ROI.
        '''
        if isinstance(index, int):
            index = [index]

        rois = list(self.all_rois)

        for ind in index:
            if ind <= 0:
                raise ValueError('ROI index starts from 1')

            roi = rois[ind - 1]

            if not name:
                name = roi.roi_name.get()

            roi.configure(name, ev_low, ev_size, enable=enable)


class Xspress3VortexBase(Device):

    # Total corrected counts
    total_corrected = Component(TotalCorrectedSignal, kind='hinted')

    # Buttons
    Acquire_button = Component(EpicsSignal, 'det1:Acquire', trigger_value=1,
                               kind='omitted')

    Erase_button = Component(EpicsSignal, 'det1:ERASE', kind='omitted')

    # State
    State = Component(EpicsSignal, 'det1:DetectorState_RBV', string=True,
                      kind='config')

    # Config
    AcquireTime = Component(EpicsSignal, 'det1:AcquireTime', kind='config')
    NumImages = Component(EpicsSignal, 'det1:NumImages', kind='config')
    TriggerMode = Component(EpicsSignal, 'det1:TriggerMode', kind='config')

    # TriggerMode, 1:internal, 3: TTL veto only
    # AcquireMode = 'step'  #step: trigger once and read roi pvs only, frame:

    def __init__(self, prefix, *, configuration_attrs=None,
                 read_attrs=None, **kwargs):

        super().__init__(prefix, configuration_attrs=None, read_attrs=None,
                         **kwargs)

        self._enabled_rois = []
        # initialize hdf5 folers
        # set 4 or 1 xsp channels,  Xspress3Channel
        # xspCh1 = Xspress3Channel(channel_num=1)
        # xspCh2 = Xspress3Channel(channel_num=2)...
        # define number of roi
        # roi1 = Xspress3ROI(1)
        # MCA1ROI:1:Total_RBV  # channel-1, roi-1
        # MCA1ROI:2:Total_RBV  # channel-1, roi-2

    def stage(self, *args, **kwargs):  # need to separate, hdf5 saving or none.
        pass
        # if frame mode: hdf5:
        #   S4QX4:HDF1:Capture # 0/1: done/capture, this needs to be 1 before
        # acquiring to save hdf files
        #   put default det1:NumImages, det1:AcquireTime
        # else:
        #   det1:NumImages=1, det1:AcquireTime

    def unstage(self, *args, **kwargs):
        pass

    def set_roi(self, index, ev_low, ev_size, name=None, channels=None):
        """
        Set up the same ROI configuration for selected channels

        Parameters
        ----------
        index : int or list of int
            ROI index. It can be passed as an integer or an iterable with
            integers.
        ev_low : int
            low eV setting.
        ev_size : int
            size eV setting.
        name : str, optional
            ROI name, if nothing is passed it will keep the current name.
        channels : iterable
            List with channel numbers to be changed.
        """

        # make a function Edge2Emission(AbsEdge) --> returns primary emission
        # energy
        # 1st argument for roi1, 2nd for roi2...
        # 'S4QX4:MCA1ROI:1:Total_RBV'  # roi1 of channel 1
        # 'S4QX4:MCA1ROI:2:Total_RBV'  # roi1 of channel 2

        if not channels:
            channels = range(1, self._num_channels+1)

        for ch in channels:
            getattr(self, f'Ch{ch}').set_roi(index, ev_low, ev_size, name=name)

    def _toggle_roi(self, index, channels=None, enable=True):
        if not channels:
            channels = range(1, self._num_channels+1)

        if isinstance(index, (int, float)):
            index = (int(index), )

        action = 'enable' if enable else 'disable'

        for ch in channels:
            channel = getattr(self, f'Ch{ch}')

            for ind in index:
                try:
                    getattr(channel.rois, 'roi{:02d}.{}'.format(ind, action))()

                    if enable and ind not in self._enabled_rois:
                        self._enabled_rois.append(ind)

                    if not enable and ind in self._enabled_rois:
                        self._enabled_rois.remove(ind)
                except AttributeError:
                    break

    def enable_roi(self, index, channels=None):
        self._toggle_roi(index, channels=channels, enable=True)

    def disable_roi(self, index, channels=None):
        self._toggle_roi(index, channels=channels, enable=False)

    def trigger(self):

        # Monitor timestamps
        state_status = None
        for i in range(1, self._num_channels+1):
            _status = getattr(self, f'Ch{i}')._status_done()
            if state_status:
                state_status = AndStatus(state_status, _status)
            else:
                state_status = _status

        # Click the Acquire_button
        button_status = super().trigger()

        return AndStatus(state_status, button_status)

    def SetCountTimePlan(self, value, **kwargs):
        yield from mv(self.AcquireTime, value, **kwargs)

    def unload(self):
        """
        Remove detector from baseline and run .destroy()
        """
        sd.baseline.remove(self)
        self.destroy()

    def select_plot_channels(self, value=True):
        if value:
            self.total_corrected.kind = Kind.hinted
        else:
            self.total.corrected.kind = Kind.normal


class Xspress3Vortex4Ch(Xspress3VortexBase):

    # Channels
    Ch1 = Component(Xspress3Channel, '', chnum=1)
    Ch2 = Component(Xspress3Channel, '', chnum=2)
    Ch3 = Component(Xspress3Channel, '', chnum=3)
    Ch4 = Component(Xspress3Channel, '', chnum=4)

    _num_channels = 4


class Xspress3Vortex1Ch(Xspress3VortexBase):

    # Channels
    Ch1 = Component(Xspress3Channel, '', chnum=1)

    _num_channels = 1
