#####################################################################
#                                                                   #
# /NI_DAQmx/blacs_tab.py                                            #
#                                                                   #
# Copyright 2018, Monash University, JQI, Christopher Billington    #
#                                                                   #
# This file is part of the module labscript_devices, in the         #
# labscript suite (see http://labscriptsuite.org), and is           #
# licensed under the Simplified BSD License. See the license.txt    #
# file in the root of the project for the full license.             #
#                                                                   #
#####################################################################
import labscript_utils.h5_lock
from labscript_utils import dedent
import h5py
import json
import numpy as np

from blacs.device_base_class import DeviceTab
from labscript_utils.qtwidgets.InputPlotWindow import PlotWindow
from labscript_utils.qtwidgets.analoginput import AnalogInput
from labscript_utils.ls_zprocess import ZMQServer
from .utils import split_conn_AO, split_conn_AI, split_conn_DO
from qtutils import UiLoader, inmain_decorator
from . import models
import warnings

# TODO: ideas for plotting layout:
#   - all the plots in a single window, stacked on top of each other.
#   - all signals on a single plot, different colour traces
# will require changes to labscript_utils.qtwidgets.analoginput.{AnalogInput, InputPlotWindow}
class DataReceiver(ZMQServer):
    """ZMQServer that receives images on a zmq.REP socket, replies 'ok', and updates the
    image widget and fps indicator"""

    def __init__(self, buttons, logger):
        ZMQServer.__init__(self, port=None, dtype='multipart')
        self.buttons = buttons
        self.last_frame_time = None
        self.frame_rate = None
        self.update_event = None
        self.logger=logger

    @inmain_decorator(wait_for_return=True)
    def handler(self, data):
        self.send([b'ok'])

        if (data[0] == b'max_plot_points'):
            chans = json.loads(data[1].decode('utf-8'))
            data = np.frombuffer(memoryview(data[2]), dtype=int)[0]
            self.logger.debug(f"test: {data}, {chans}")
            # NOTE: Enouter error, we don't really need to implement this, try skipping this line 
            # for i, chan in enumerate(chans):
            #     self.buttons[chan].set_max_data(data)
            return self.NO_RESPONSE
        else:
            chans = json.loads(data[0].decode('utf-8'))
            num_chans = len(chans)
            data = np.frombuffer(memoryview(data[1]), dtype=np.float32)
        
            # break up the plot data to separate out each of the channels data
            split_data = [data[i::num_chans] for i in range(num_chans)]

            # the AnalogInput button uses IPC (pipes) to communicate with the plot window Process
            for i, chan in enumerate(chans):
                # NOTE: Enouter error, we don't really need to implement this, try skipping this line 
                # self.buttons[chan].set_buffer(split_data[i])
                pass
            return self.NO_RESPONSE

class NI_DAQmxTab(DeviceTab):
    def initialise_GUI(self):
        # Get capabilities from connection table properties:
        connection_table = self.settings['connection_table']
        properties = connection_table.find_by_name(self.device_name).properties

        # Raise an error on old connection tables, since we are not backward compatible
        # with them. In terms of old shot files being added to the queue once BLACS has
        # started, BLACS will reject them as being incomatible since the connection
        # table properties won't match. So we do not need to add a check for that.
        version = properties.get('__version__', None)
        if version is None:
            msg = """Connection table was compiled with the old version of the NI_DAQmx
                device class. The new BLACS tab is not backward compatible with old shot
                files (including connection tables). Either downgrade labscript_devices
                to 2.4.0 or less, or recompile the connection table with
                labscript_devices 2.5.0 or greater.
                """
            raise RuntimeError(dedent(msg))

        num_AO = properties['num_AO']
        num_AI = properties['num_AI']
        try:
            AI_chans = properties['AI_chans']
        except KeyError:
            # new code being run on older model specification file
            # assume legacy behavior, warn user to update
            AI_chans = [f'ai{i:d}' for i in range(num_AI)]
            msg = """Connection table was compiled with old model specifications for {0}.
                     Please recompile the connection table.
                  """
            warnings.warn(dedent(msg.format(properties['MAX_name'])), FutureWarning)

        ports = properties['ports']
        num_CI = properties['num_CI']

        AO_base_units = 'V'
        if num_AO > 0:
            AO_base_min, AO_base_max = properties['AO_range']
        else:
            AO_base_min, AO_base_max = None, None
        AO_base_step = 0.1
        AO_base_decimals = 3

        clock_terminal = properties['clock_terminal']
        clock_mirror_terminal = properties['clock_mirror_terminal']
        # get to avoid error on older connection tables
        connected_terminals = properties.get('connected_terminals', None)
        static_AO = properties['static_AO']
        static_DO = properties['static_DO']
        clock_limit = properties['clock_limit']
        min_semiperiod_measurement = properties['min_semiperiod_measurement']

        # And the Measurement and Automation Explorer (MAX) name we will need to
        # communicate with the device:
        self.MAX_name = properties['MAX_name']

        # Create output objects:
        AO_prop = {}
        for i in range(num_AO):
            AO_prop['ao%d' % i] = {
                'base_unit': AO_base_units,
                'min': AO_base_min,
                'max': AO_base_max,
                'step': AO_base_step,
                'decimals': AO_base_decimals,
            }

        DO_proplist = []
        DO_hardware_names = []
        for port_num in range(len(ports)):
            port_str ='port%d' % port_num
            port_props = {}
            for line in range(ports[port_str]['num_lines']):
                hardware_name = 'port%d/line%d' % (port_num, line)
                port_props[hardware_name] = {}
                DO_hardware_names.append(hardware_name)
            DO_proplist.append((port_str, port_props))

        # Create the output objects
        self.create_analog_outputs(AO_prop)

        # Create widgets for outputs defined so far (i.e. analog outputs only)
        _, AO_widgets, _ = self.auto_create_widgets()

        # now create the digital output objects one port at a time
        for _, DO_prop in DO_proplist:
            self.create_digital_outputs(DO_prop)

        # Manually create the digital output widgets so they are grouped separately
        DO_widgets_by_port = {}
        for port_str, DO_prop in DO_proplist:
            DO_widgets_by_port[port_str] = self.create_digital_widgets(DO_prop)

        # Auto place the widgets in the UI, specifying sort keys for ordering them:
        widget_list = [("Analog outputs", AO_widgets, split_conn_AO)]
        for port_num in range(len(ports)):
            port_str ='port%d' % port_num
            DO_widgets = DO_widgets_by_port[port_str]
            name = "Digital outputs: %s" % port_str
            if ports[port_str]['supports_buffered']:
                name += ' (buffered)'
            else:
                name += ' (static)'
            widget_list.append((name, DO_widgets, split_conn_DO))
        
        self.ai_buttons = {}
        for i, chan in enumerate(AI_chans):
            child_device = self.get_child_from_connection_table(self.device_name,chan)
            conn_name = child_device.name if child_device else '-'
            ai_button = AnalogInput(self.device_name, chan, conn_name)
            ai_button.set_value(0)
            self.ai_buttons[chan] = ai_button

        widget_list.append(("Analog Inputs", self.ai_buttons, split_conn_AI))

        self.auto_place_widgets(*widget_list)

        self.data_receiver = DataReceiver(self.ai_buttons, self.logger)

        # We only need a wait monitor worker if we are if fact the device with
        # the wait monitor input.
        with h5py.File(connection_table.filepath, 'r') as f:
            waits = f['waits']
            wait_acq_device = waits.attrs['wait_monitor_acquisition_device']
            wait_acq_connection = waits.attrs['wait_monitor_acquisition_connection']
            wait_timeout_device = waits.attrs['wait_monitor_timeout_device']
            wait_timeout_connection = waits.attrs['wait_monitor_timeout_connection']
            try:
                timeout_trigger_type = waits.attrs['wait_monitor_timeout_trigger_type']
            except KeyError:
                timeout_trigger_type = 'rising'

        # Create and set the primary worker
        self.create_worker(
            "main_worker",
            'labscript_devices.NI_DAQmx.blacs_workers.NI_DAQmxOutputWorker',
            {
                'MAX_name': self.MAX_name,
                'Vmin': AO_base_min,
                'Vmax': AO_base_max,
                'num_AO': num_AO,
                'ports': ports,
                'clock_limit': clock_limit,
                'clock_terminal': clock_terminal,
                'clock_mirror_terminal': clock_mirror_terminal,
                'static_AO': static_AO,
                'static_DO': static_DO,
                'DO_hardware_names': DO_hardware_names,
                'wait_timeout_device': wait_timeout_device,
                'wait_timeout_connection': wait_timeout_connection,
                'wait_timeout_rearm_value': int(timeout_trigger_type == 'falling')
            },
        )
        self.primary_worker = "main_worker"

        if wait_acq_device == self.device_name:
            if wait_timeout_device:
                wait_timeout_device = connection_table.find_by_name(wait_timeout_device)
                wait_timeout_MAX_name = wait_timeout_device.properties['MAX_name']
            else:
                wait_timeout_MAX_name = None

            if num_CI == 0:
                msg = """Device cannot be the wait monitor acquisiiton device as it has
                    no counter inputs"""
                raise RuntimeError(dedent(msg))

            self.create_worker(
                "wait_monitor_worker",
                'labscript_devices.NI_DAQmx.blacs_workers.NI_DAQmxWaitMonitorWorker',
                {
                    'MAX_name': self.MAX_name,
                    'wait_acq_connection': wait_acq_connection,
                    'wait_timeout_MAX_name': wait_timeout_MAX_name,
                    'wait_timeout_connection': wait_timeout_connection,
                    'timeout_trigger_type': timeout_trigger_type,
                    'min_semiperiod_measurement': min_semiperiod_measurement,
                },
            )
            self.add_secondary_worker("wait_monitor_worker")

        # Only need an acquisition worker if we have analog inputs. It is important that
        # the acquisition worker is created after the wait monitor worker if there is
        # one, because the creation order determines the order that transition_to_manual
        # runs, and the acquisition processing requires processing that is done in the
        # wait monitor during transition_to_manual.
        if num_AI > 0:
            self.create_worker(
                "acquisition_worker",
                'labscript_devices.NI_DAQmx.blacs_workers.NI_DAQmxAcquisitionWorker',
                {
                    'MAX_name': self.MAX_name,
                    'num_AI': num_AI,
                    'AI_chans': AI_chans,
                    'AI_term': properties['AI_term'],
                    'AI_range': properties['AI_range'],
                    'AI_start_delay': properties['AI_start_delay'],
                    'AI_start_delay_ticks': properties['AI_start_delay_ticks'],
                    'AI_timebase_terminal': properties.get('AI_timebase_terminal',None),
                    'AI_timebase_rate': properties.get('AI_timebase_rate',None),
                    'clock_terminal': clock_terminal,
                    'data_receiver_port': self.data_receiver.port,
                },
            )
            self.add_secondary_worker("acquisition_worker")

        # Set the capabilities of this device
        self.supports_remote_value_check(False)
        self.supports_smart_programming(False)