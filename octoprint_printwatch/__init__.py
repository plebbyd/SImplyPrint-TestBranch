from __future__ import absolute_import, unicode_literals
import octoprint.plugin
from octoprint.events import Events
from .videostreamer import VideoStreamer
from .comm import CommManager
from .inferencer import Inferencer
from .printer import PrinterControl

from enum import Enum
from threading import Thread
from time import time, sleep

class States(Enum):
    OPEN_SERIAL = 0
    DETECT_SERIAL = 1
    DETECT_BAUDRATE = 2
    CONNECTING = 3
    OPERATIONAL = 4
    PRINTING = 5
    PAUSED = 6
    CLOSED = 7
    ERROR = 8
    CLOSED_WITH_ERROR = 9
    TRANSFERING_FILE = 10
    OFFLINE = 11
    UNKNOWN = 12
    NONE = 13

class BadRowException(Exception):
    def __init__(self, e):
        self.message = f"{e}"

class AnomalyFeatures():
    def __init__(self):
        self.rows_of_data = [] #N=22 features at the moment

    def append_row(self, row : list):
        if isinstance(row, list):
            self.rows_of_data.append(row)
        else:
            raise BadRowException('row must be of type <list> and size=26')

    def retrieve_row(self, idx : int = -1) -> list:
        return self.rows_of_data[idx]

    def retrieve_all_data(self) -> list:
        return self.rows_of_data


class PrintWatchPlugin(octoprint.plugin.StartupPlugin,
                           octoprint.plugin.ShutdownPlugin,
                           octoprint.plugin.TemplatePlugin,
                           octoprint.plugin.SettingsPlugin,
                           octoprint.plugin.AssetPlugin,
                           octoprint.plugin.EventHandlerPlugin,
                           octoprint.plugin.SimpleApiPlugin
                           ):


    def on_after_startup(self):
        self._logger.info("Loading PrintWatch...")
        self.comm_manager = CommManager(self)
        self.streamer = VideoStreamer(self)
        self.inferencer = Inferencer(self)
        self.controller = PrinterControl(self)
        self.samples = AnomalyFeatures()
        self.plugin_start = time()
        self.last_time = 0.0
        self.tool_change_time = 0.0
        self.filament_change_time = 0.0
        self.current_feedrate_percent = 1.0
        self.current_feedrate = 1.0
        self.acquire_samples()
        self.start_thread()

    def acquire_samples(self):
        current_data = self._printer.get_current_data()
        current_temps = self._printer.get_current_temperatures()
        self._logger.info('TEMPS" {}'.format(current_temps))
        files = self._file_manager.list_files()
        current_file_name = current_data['job']['file']['name']
        lanks = self.get_lankyness_XYZ(current_file_name)

        assembled_row = [
            States[self._printer.get_state_id()].value,
            int(current_data['state']['flags']['sdReady']),
            int(self.check_last_same_job_success(current_file_name)) if current_file_name and current_file_name is not '' else 0,
            current_data['progress']['printTime'] if current_data['progress']['printTime'] else 0.0,
            current_data['currentZ'] if current_data['currentZ'] else 0.0,
            lanks[0],
            lanks[1],
            lanks[2],
            current_data['resends']['ratio'],
            int(time() - self.filament_change_time < 300.0),
            int(time() - self.tool_change_time < 300.0),
            self.current_feedrate,
            self.current_feedrate_percent,
            current_temps['bed']['actual'] if current_temps.get('bed') and current_temps.get('bed') is not None else 0.0,
            current_temps['bed']['target'] if  current_temps.get('bed') and current_temps.get('bed') is not None else 0.0,
            current_temps['bed']['offset'] if  current_temps.get('bed') and current_temps.get('bed') is not None else 0.0,
            current_temps['chamber']['actual'] if current_temps.get('chamber') and current_temps.get('chamber').get('actual') else 0.0,
            current_temps['chamber']['target'] if current_temps.get('chamber') and current_temps.get('chamber').get('target') is not None else 0.0,
            current_temps['chamber']['offset'] if current_temps.get('chamber') and current_temps.get('chamber').get('offset') else 0.0
            ]
        _num_extruders = self._printer_profile_manager.get_current().get('extruder').get('count', 1)
        for tool_num in range(_num_extruders):
            assembled_row.append(current_temps['tool{}'.format(tool_num)]['actual'] if current_temps.get('tool{}'.format(tool_num)) else 0.0)
            assembled_row.append(current_temps['tool{}'.format(tool_num)]['target'] if current_temps.get('tool{}'.format(tool_num)) else 0.0)
            assembled_row.append(current_temps['tool{}'.format(tool_num)]['offset'] if current_temps.get('tool{}'.format(tool_num)) else 0.0)
        self._logger.info('New add"n: {}'.format(assembled_row))
        self.samples.append_row(assembled_row)

    def get_lankyness_XYZ(self, filename):
        if filename and filename is not '':
            file_info = self._file_manager.list_files()['local'][filename]['analysis']['dimensions']
            XY = file_info['width'] / file_info['depth']
            YZ = file_info['depth'] / file_info['height']
            XZ = file_info['width'] / file_info['height']
        else:
            XY = 0.0
            YZ = 0.0
            XZ = 0.0
        return [XY, YZ, XZ]

    def check_last_same_job_success(self, filename):
        files = self._file_manager.list_files()
        file_info = files['local'][filename]
        last_job_info = file_info['history'][-1]
        return last_job_info['success']

    def get_api_commands(self):
        return dict(
            sendFeedback=[]
        )

    def on_api_command(self, command, data):
        if command == 'sendFeedback':
            self.comm_manager.send_feedback(data.get("class"))
            self._logger.info(
                "Defect report sending to server for type: {}".format(data.get("class"))
            )
            return
        return

    def get_update_information(self):
        return dict(
            printwatch=dict(
                name=self._plugin_name,
                version=self._plugin_version,

                type="github_release",
                current=self._plugin_version,
                user="printpal-io",
                repo="OctoPrint-PrintWatch",

                pip="https://github.com/printpal-io/OctoPrint-PrintWatch/archive/{target}.zip"

            )
        )

    def on_settings_save(self, data):
        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
        if self.inferencer.warning_notification:
            self.inferencer.begin_cooldown()
        self._settings.save()
        self._plugin_manager.send_plugin_message(self._identifier, dict(type="onSave"))


    def get_settings_defaults(self):
        return dict(
            stream_url = 'http://127.0.0.1/webcam/?action=snapshot',
            enable_detector = True,
            enable_email_notification = False,
            email_addr = '',
            enable_shutoff = False,
            enable_stop = False,
            enable_extruder_shutoff = False,
            notification_threshold = 40,
            action_threshold = 60,
            confidence = 60,
            buffer_length = 16,
            buffer_percent = 80,
            enable_feedback_images = True,
            api_key = ''
            )

    def get_template_configs(self):
        return [
            dict(type="settings", custom_bindings=False)
        ]


    def get_assets(self):
        return dict(
            js=["js/printwatch.js"],
            css=["css/printwatch.css"]
        )

    def start_thread(self):
        self.run_thread = True
        self.anomaly_loop = Thread(target=self._sampling)
        self.anomaly_loop.daemon = True
        self.anomaly_loop.start()

    def _sampling(self):
        while True:
            if time() - self.last_time > 2.0 and time() - self.plugin_start > 20.0:
                self.acquire_samples()
                self.last_time = time()
                self._logger.info('SIZE: {}'.format(len(self.samples.rows_of_data)))
                if len(self.samples.rows_of_data) > 5:
                    self._logger.info(self.samples.rows_of_data)
                    with open('/output_file.txt', 'w+') as f:
                        for line in self.samples.rows_of_data:
                            f.write("%s\n" % str(line).replace('[', '').replace(']', ''))

            sleep(0.1)
    def on_event(self, event, payload):
        if event == Events.PRINT_STARTED:
            self.inferencer.start_service()
            self.comm_manager.kill_service()
            self.comm_manager.new_ticket()
            self._plugin_manager.send_plugin_message(
                self._identifier,
                dict(type="resetPlot")
            )
        elif event == Events.PRINT_RESUMED:
            if self.inferencer.triggered:
                self.controller.restart()
            self.inferencer.start_service()
            self.comm_manager.kill_service()
        elif event in (
            Events.PRINT_PAUSED,
            Events.PRINT_CANCELLED,
            Events.PRINT_DONE,
            Events.PRINT_FAILED
            ):
            if self.inferencer.triggered:
                self.inferencer.shutoff_event()
            self.inferencer.kill_service()

            if event == Events.PRINT_PAUSED:
                self.comm_manager.start_service()
            else:
                self.comm_manager.kill_service()
                self._plugin_manager.send_plugin_message(
                    self._identifier,
                    dict(type="resetPlot")
                )
        elif event == Events.FILAMENT_CHANGE:
            self.filament_change_time = time()
        elif event == Events.TOOL_CHANGE:
            self.tool_change_time = time()



    def on_shutdown(self):
        self.inferencer.run_thread = False

    def check_fr(self, comm_instance, phase, cmd, cmd_type, gcode, *args, **kwargs):
        if gcode and gcode in ['G0', 'G1', 'G2', 'G3']:
            idx = cmd.find('F')
            if idx != -1:
                idx_end = cmd.find(' ', idx)
                number = float(cmd[idx+1:idx_end])
                self.current_feedrate = number
        if gcode and gcode == 'M220':
            idx = cmd.find('S')
            idx_end = cmd.find(' ', idx)
            number = float(cmd[idx+1:idx_end])
            self.current_feedrate_percent = number




__plugin_name__ = "PrintWatch"
__plugin_version__ = "1.1.1"
__plugin_description__ = "PrintWatch watches your prints for defects and optimizes your 3D printers using Artificial Intelligence."
__plugin_pythoncompat__ = ">=2.7,<4"
__plugin_implementation__ = PrintWatchPlugin()


def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = PrintWatchPlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
        "octoprint.comm.protocol.gcode.sent": __plugin_implementation__.check_fr
    }
