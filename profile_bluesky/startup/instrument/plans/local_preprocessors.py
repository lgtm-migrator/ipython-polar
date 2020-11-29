"""Local decorators."""

from bluesky.utils import make_decorator, single_gen
from bluesky.preprocessors import pchain, plan_mutator, finalize_wrapper
from bluesky.plan_stubs import mv, sleep
from ..devices import scalerd, pr_setup, mag6t
from ..utils import local_rd


def stage_ami_wrapper(plan, magnet):

    def _stage():

        if mag6t.field.switch_heater.get() != 'On':

            yield from mv(mag6t.field.ramp_button, 1)

            while True:
                supply = yield from local_rd(mag6t.field.supply_current)
                target = yield from local_rd(mag6t.field.current)
                if abs(supply-target) > 0.01:
                    yield from sleep(1)
                else:
                    break

            yield from mv(mag6t.field.switch_heater, 'On')

            while True:
                _status = yield from local_rd(mag6t.field.magnet_status)

                if _status != 3:
                    yield from sleep(1)
                else:
                    break

            yield from mv(mag6t.field.ramp_button, 1)

    def _unstage():

        while True:
            voltage = yield from local_rd(mag6t.field.voltage)
            if abs(voltage) > 0.01:
                yield from sleep(1)
            else:
                break

        yield from mv(mag6t.field.switch_heater, 'Off')

        while True:
            _status = yield from local_rd(mag6t.field.magnet_status)

            if _status not in [2, 3]:
                yield from sleep(1)
            else:
                break

        yield from mv(mag6t.field.zero_button, 1)

    def _inner_plan():
        yield from _stage()
        return (yield from plan)

    if magnet:
        return (yield from finalize_wrapper(_inner_plan(), _unstage()))
    else:
        return (yield from plan)

def configure_monitor_wrapper(plan, monitor):
    """
    Preprocessor that sets all devices with a `preset_monitor` to the same \
    value. The original setting is stashed and restored at the end.

    Parameters
    ----------
    plan : iterable or iterator
        a generator, list, or similar containing `Msg` objects
    monitor : float or None
        If None, the plan passes through unchanged.
    Yields
    ------
    msg : Msg
        messages from plan, with 'set' messages inserted
    """
    devices_seen = set()
    original_times = {}

    def insert_set(msg):
        obj = msg.obj
        if obj is not None and obj not in devices_seen:
            devices_seen.add(obj)
            if hasattr(obj, 'preset_monitor'):
                original_times[obj] = obj.preset_monitor.get()
                return pchain(mv(obj.preset_monitor, monitor),
                              single_gen(msg)), None
        return None, None

    def reset():
        for obj, time in original_times.items():
            yield from mv(obj.preset_monitor, time)

    if monitor is None:
        return (yield from plan)
    else:
        return (yield from finalize_wrapper(plan_mutator(plan, insert_set),
                                            reset()))


def stage_dichro_wrapper(plan, dichro, lockin):

    _current_scaler_plot = []

    def _stage():

        if dichro and lockin:
            raise ValueError('Cannot have both dichro and lockin = True.')

        if lockin:
            for chan in scalerd.channels.component_names:
                scaler_channel = getattr(scalerd.channels, chan)
                if scaler_channel.kind.value >= 5:
                    _current_scaler_plot.append(scaler_channel.s.name)

            scalerd.select_plot_channels(['Lock DC', 'Lock AC'])

            if pr_setup.positioner is None:
                raise ValueError('Phase retarder was not selected.')

            if 'th' in pr_setup.positioner.name:
                raise TypeError('Theta motor cannot be used in lock in! \
                                Please run pr_setup.config() and choose \
                                pzt.')

            yield from mv(pr_setup.positioner.parent.selectAC, 1)

        if dichro:
            # move PZT to center.
            if 'pzt' in pr_setup.positioner.name:
                yield from mv(pr_setup.positioner,
                              pr_setup.positioner.parent.center.get())

    def _unstage():
        if lockin:
            scalerd.select_plot_channels(_current_scaler_plot)
            yield from mv(pr_setup.positioner.parent.selectDC, 1)

    def _inner_plan():
        yield from _stage()
        return (yield from plan)

    return (yield from finalize_wrapper(_inner_plan(), _unstage()))


configure_monitor_decorator = make_decorator(configure_monitor_wrapper)
stage_dichro_decorator = make_decorator(stage_dichro_wrapper)
stage_ami_decorator = make_decorator(stage_ami_wrapper)
