"""
Define qxscan_setup device.

This device will holds the parameters and energy list used in a qxscan plan.
"""

from ..session_logs import logger
import json
from ophyd import Signal, Device, Kind
from ophyd import Component
from ..framework import sd
from collections import OrderedDict
from numpy import sqrt, arange

__all__ = ['qxscan_params']

logger.info(__file__)

hbar = 6.582119569E-16  # eV.s
speed_of_light = 299792458e10  # A/s
electron_mass = 0.510998950E6/speed_of_light**2  # eV.s**2/A**2

global constant
constant = 2*electron_mass/hbar**2  # A^2/eV


def _preedge_channels(attr_fix, id_range):
    defn = OrderedDict()
    defn['num_regions'] = (Signal, '', {'value': 0, 'kind': Kind.config})
    for k in id_range:
        defn['{}{}_Estart'.format(attr_fix, k)] = (Signal,
                                                   '', {'value': 0,
                                                        'kind': Kind.config})
        defn['{}{}_Estep'.format(attr_fix, k)] = (Signal,
                                                  '', {'value': 0,
                                                       'kind': Kind.config})
    return defn


def _postedge_channels(attr_fix, id_range):
    defn = OrderedDict()
    defn['num_regions'] = (Signal, '', {'value': 0, 'kind': Kind.config})
    for k in id_range:
        defn['{}{}_Kend'.format(attr_fix, k)] = (Signal,
                                                 '', {'value': 0,
                                                      'kind': Kind.config})
        defn['{}{}_Kstep'.format(attr_fix, k)] = (Signal,
                                                  '', {'value': 0,
                                                       'kind': Kind.config})
    return defn


class EdgeDevice(Device):
    Estart = Component(Signal, value=0)
    Eend = Component(Signal, value=0)
    Estep = Component(Signal, value=0)


class PreEdgeRegion(Device):
    Estart = Component(Signal, value=0)
    Estep = Component(Signal, value=0)


class PreEdgeDevice(Device):
    num_regions = Component(Signal, value=0)
    region1 = Component(PreEdgeRegion)
    region2 = Component(PreEdgeRegion)
    region3 = Component(PreEdgeRegion)
    region4 = Component(PreEdgeRegion)
    region5 = Component(PreEdgeRegion)


class PostEdgeRegion(Device):
    Kend = Component(Signal, value=0)
    Kstep = Component(Signal, value=0)


class PostEdgeDevice(Device):
    num_regions = Component(Signal, value=0)
    region1 = Component(PostEdgeRegion)
    region2 = Component(PostEdgeRegion)
    region3 = Component(PostEdgeRegion)
    region4 = Component(PostEdgeRegion)
    region5 = Component(PostEdgeRegion)


class QxscanParams(Device):
    pre_edge = Component(PreEdgeDevice)
    edge = Component(EdgeDevice)
    post_edge = Component(PostEdgeDevice)
    energy_list = Component(Signal, value=0)

    def setup(self):
        print('Defining the energy range and steps for qxscan')
        print('All energies are relative to the absorption edge!')

        while True:
            value = int(input('\n Number of pre-edge regions: '))
            if 1 <= value <= 5:
                self.pre_edge.num_regions.put(value)
                break
            else:
                print('WARNING: number of pre-edge regions need to be >=1 and <= 5!')

        for i in range(self.pre_edge.num_regions.get()):
            print('\n Defining pre-edge #{}'.format(i+1))
            relative_energy = float(input('Start energy (in eV): '))
            energy_increment = float(input('Energy increment (in eV): '))

            region = getattr(self.pre_edge, 'region{}'.format(i+1))
            region.Estart.put(relative_energy)
            region.Estep.put(energy_increment)

        print('\n Defining edge region')
        relative_energy_start = float(input('Start energy (in eV): '))
        relative_energy_end = float(input('Final energy (in eV): '))
        energy_increment = float(input('Energy increment (in eV): '))

        self.edge.Estart.put(relative_energy_start)
        self.edge.Eend.put(relative_energy_end)
        self.edge.Estep.put(energy_increment)

        kend = sqrt(constant*relative_energy_end)
        print('The edge region ends at k = {:0.3f} angstroms^-1'.format(kend))

        while True:
            value = int(input('\n Number of post-edge regions: '))
            if 1 <= value <= 5:
                self.post_edge.num_regions.put(value)
                break
            else:
                print('WARNING: number of post-edge regions need to be >= 1 and <= 5!')

        for i in range(self.post_edge.num_regions.get()):
            print('\n Defining post-edge #{}'.format(i+1))
            relative_k = float(input('k end (in angstroms^-1): '))
            k_increment = float(input('k increment (in angstroms^-1): '))

            region = getattr(self.post_edge, 'region{}'.format(i+1))
            region.Kend.put(relative_k)
            region.Kstep.put(k_increment)

        self._create_energy_list()

    def _create_energy_list(self):
        elist = []

        # Pre-edge region
        for i in range(self.pre_edge.num_regions.get()):
            region = getattr(self.pre_edge, 'region{}'.format(i+1))
            start = region.Estart.get()
            step = region.Estep.get()

            if i != self.pre_edge.num_regions.get()-1:
                end = getattr(self.pre_edge,
                              'region{}'.format(i+2)).Estart.get()
            else:
                end = self.edge.Estart.get()

            elist += list(arange(start, end, step)/1000.)

        # Edge region
        start = self.edge.Estart.get()
        end = self.edge.Eend.get()
        step = self.edge.Estep.get()

        elist += list(arange(start, end, step)/1000.)

        # Post-edge region
        for i in range(self.post_edge.num_regions.get()):
            region = getattr(self.post_edge, 'region{}'.format(i+1))
            end = region.Kend.get()
            step = region.Kstep.get()

            if i == 0:
                start = sqrt(constant*self.edge.Eend.get())
            else:
                start = getattr(self.post_edge,
                                'region{}'.format(i)).Kend.get()

            elist += list(arange(start, end, step)**2/constant/1000.)

        elist += [end**2/constant/1000.]

        print('\nNumber of points: {}'.format(len(elist)))
        print('Final relative energy: {:0.3f} eV'.format(max(elist)*1000.))

        elist.reverse()

        self.energy_list.put(elist)

    def _read_params_dict(self, input):
        """
        Read an dictionary that contains the qxscan setup parameters.

        Parameters
        -----------
        input: dictionary
        Formatted as the output of self._make_params_dict. The dictionary has
        to contain every qxscan_setup parameter (including all pre_edge and
        post_edge regions!). For instance:
        - input['edge']['Estart'] is passed to self.edge.Estart
        - output['energy_list'] is passed to self.energy_list

        Returns
        -----------
        None
        """
        self.energy_list.put(input['energy_list'])

        self.edge.Estart.put(input['edge']['Estart'])
        self.edge.Eend.put(input['edge']['Eend'])
        self.edge.Estep.put(input['edge']['Estep'])

        self.pre_edge.num_regions.put(input['pre_edge']['num_regions'])
        for i in range(5):
            reg_key = 'region{}'.format(i+1)
            region = getattr(self.pre_edge, reg_key)
            region.Estart.put(input['pre_edge'][reg_key]['Estart'])
            region.Estep.put(input['pre_edge'][reg_key]['Estep'])

        self.post_edge.num_regions.put(input['post_edge']['num_regions'])
        for i in range(5):
            reg_key = 'region{}'.format(i+1)
            region = getattr(self.post_edge, reg_key)
            region.Kend.put(input['post_edge'][reg_key]['Kend'])
            region.Kstep.put(input['post_edge'][reg_key]['Kstep'])

    def _make_params_dict(self):
        """
        Create an dictionary that contains the qxscan setup parameters.

        Parameters
        -----------
        None

        Returns
        -----------
        output: dictionary
        Each device is saved in a new inner dictionary. For instance:
        - self.edge.Estart is saved at output['edge']['Estart']
        - self.energy_list is saved at output['energy_list']
        """
        output = {}

        output['energy_list'] = self.energy_list.get()

        output['edge'] = {}
        output['edge']['Estart'] = self.edge.Estart.get()
        output['edge']['Eend'] = self.edge.Eend.get()
        output['edge']['Estep'] = self.edge.Estep.get()

        output['pre_edge'] = {}
        output['pre_edge']['num_regions'] = self.pre_edge.num_regions.get()
        for i in range(5):
            reg_key = 'region{}'.format(i+1)
            region = getattr(self.pre_edge, reg_key)
            output['pre_edge'][reg_key] = {}
            output['pre_edge'][reg_key]['Estart'] = region.Estart.get()
            output['pre_edge'][reg_key]['Estep'] = region.Estep.get()

        output['post_edge'] = {}
        output['post_edge']['num_regions'] = self.post_edge.num_regions.get()
        for i in range(5):
            reg_key = 'region{}'.format(i+1)
            region = getattr(self.post_edge, reg_key)
            output['post_edge'][reg_key] = {}
            output['post_edge'][reg_key]['Kend'] = region.Kend.get()
            output['post_edge'][reg_key]['Kstep'] = region.Kstep.get()

        return output

    def save_params_json(self, fname):
        """
        Save a json file that contains a dictionary with the qxscan parameters.

        Parameters
        -----------
        fname: string
        Location and name of the file to be saved.

        Returns
        -----------
        None
        """
        output = self._make_params_dict()
        with open(fname, 'w') as f:
            f.write(json.dumps(output))

    def load_params_json(self, fname):
        """
        Load a json file that contains a dictionary with the qxscan parameters.

        This dictionary must be formatted as required by
        self._read_params_dict.

        Parameters
        -----------
        fname: string
        Location and name of the file to be loaded

        Returns
        -----------
        None
        """
        input = json.load(open(fname, 'r'))
        self._read_params_dict(input)


qxscan_params = QxscanParams(name='qxscan_setup')
sd.baseline.append(qxscan_params)

# TODO: Could not make this work using DynamicDeviceComponent. Don't know why.
