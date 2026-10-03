import sys
import os
import atexit
import pickle
import argparse
import enum
import ctypes
import collections
import concurrent.futures
import logging
import shlex
import json
import socketserver
import http.server
import threading
import time
from pathlib import Path
import platform
import re
import enum
import socket
import errno
import webbrowser
import pathlib
import shutil
import urllib.error
import subprocess
import functools
import tempfile
import contextlib

from devkit_client import is_running_under_wsl

# must match in steamos-get-status
class SteamStatus(enum.Enum):
    NOT_RUNNING = 0
    ERROR = 1
    OS = 2
    OS_DEV = 3
    SIDELOADED = 4

    @classmethod
    def from_string(cls, status_str):
        if not status_str:
            return cls.ERROR
        try:
            if '.' in status_str:
                name = status_str.split('.')[-1]
            else:
                name = status_str
            return cls[name]
        except KeyError:
            return cls.ERROR

    @property
    def description(self):
        DESCRIPTIONS = {
            SteamStatus.NOT_RUNNING: 'not running',
            SteamStatus.OS: 'OS client',
            SteamStatus.OS_DEV: 'OS client dev mode',
            SteamStatus.SIDELOADED: 'sideloaded client',
            SteamStatus.ERROR: 'error',
        }
        return DESCRIPTIONS[self]


if platform.system() == 'Windows':
    import winreg

import signalslot
# silences some warnings about numpy..
logging.getLogger('OpenGL.plugins').setLevel(logging.ERROR)
import OpenGL.GL as gl
import sdl2
import imgui
import imgui.integrations.sdl2

import devkit_client
import devkit_client.proxy
from devkit_client import RuntimeOptions, SteamPlayDebug
import paramiko
import zeroconf

from devkit_client.icon import ICON_FILENAME

from devkit_client.gui2.file_dialogs import browse_directory, browse_file, open_folder

CHARACTER_WIDTH = 8
CHARACTER_HEIGHT = 14 # e.g. a line of text

GAMEID_ALLOWED_PATTERN = '^[A-Za-z_][A-Za-z0-9_.]+$'


TOGGLE_DEV_MODE = 'Make sure developer mode is enabled on the device. Could also be a network config or firewall issue.'

logger = logging.getLogger(__name__)


def str2bool(v):
    if isinstance(v, bool):
        return v
    if v.lower() in ('yes', 'on', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'off', 'false', 'f', 'n', '0'):
        return False
    else:
        raise Exception('Boolean value expected.')


def imgui_calc_text_size(text):
    lines = text.split('\n')
    max_char = max([len(l) for l in lines])
    return (max_char*CHARACTER_WIDTH, len(lines)*CHARACTER_HEIGHT)


@contextlib.contextmanager
def imgui_window(title, closable=True, flags=0):
    expanded, opened = imgui.begin(title, closable, flags)
    try:
        yield (expanded, opened)
    finally:
        imgui.end()


class DevkitCommands:
    '''Wrap an async API around devkit command execution via the cli modules.
    This is very crufty because reasons. Could be massively simplified now.
    '''

    def __init__(self, conf, shutdown_signal):
        self.conf = conf
        self.executor = None
        self.signal_steamos_status = signalslot.Signal(args = ['devkit'])
        # we have some background threads that should early out when shutting down
        self.shutting_down = False
        shutdown_signal.connect(self.on_shutdown_signal)

    def setup(self):
        self.executor = concurrent.futures.ThreadPoolExecutor()

    def on_shutdown_signal(self, **kwargs):
        self.shutting_down = True

    def _identify(self, devkit):
        machine = self._check_connectivity(devkit)
        assert devkit.limited_connectivity is not None

        # If the service cannot be reached, ssh connectivity is irrelevant, we cannot do anything with the kit
        # Also catches no connectivity situations (wrong IP, fully firewalled, etc.)
        if not devkit.http_connectivity:
            logger.info(f'No connectivity with kit: {machine.address}')
            raise DevkitNoConnectivity

        if not devkit.ssh_connectivity:
            # assume we are seeing an unregistered devkit that does not have sshd running yet
            logger.info(f'sshd may not be running yet - kit needs registration: {machine.address}')
            raise DevkitNotRegistered

        try:
            # check if the kit is registered - by opening a ssh to it with our devkit key
            devkit_client.open_ssh_for_args_all(devkit.machine_command_args[0], devkit.machine_command_args[1], machine)
        except paramiko.AuthenticationException as e:
            logger.info(f'ssh connection check failed: {e}')
            raise DevkitNotRegistered
        except paramiko.ssh_exception.SSHException as e:
            # my system got into a state throwing 'key cannot be used for signing',
            # that I could not reproduce after reboot.
            # would love to know what causes this and have a reproduction.
            logger.info(f'Unexpected paramiko exception! {e} - treating as devkit not registered.')
            raise DevkitNotRegistered

        # looking good, deploy/refresh the utility scripts
        class SyncUtilsArgs:
            def __init__(self, devkit):
                self.machine, self.machine_name_type = devkit.machine_command_args
                self.http_port = devkit.http_port
                self.login = None
        # NOTE: there may be a situation where paramiko thinks we are registered (right above), but this step fails as if we were not
        # (suggesting that maybe paramiko manages to open a connection with something else than only the devkit key?)
        devkit_client.sync_utils(SyncUtilsArgs(devkit), machine)
        # get general status info
        class GetStatusArgs:
            def __init__(self, devkit):
                self.machine, self.machine_name_type = devkit.machine_command_args
                self.http_port = devkit.http_port
                self.login = None
        steamos_status = devkit_client.steamos_get_status(GetStatusArgs(devkit))
        if steamos_status is None:
            steamos_status = {}
        return (machine, steamos_status)

    def identify(self, *args):
        return self.executor.submit(self._identify, *args)

    def _steamos_get_status(self, devkit):
        class GetStatusArgs:
            def __init__(self, devkit):
                self.machine, self.machine_name_type = devkit.machine_command_args
                self.http_port = devkit.http_port
                self.login = None
        # on the UI side, we default steamos_status to empty dict
        try:
            devkit.steamos_status = devkit_client.steamos_get_status(GetStatusArgs(devkit))
        except Exception as e:
            devkit.steamos_status = {}
            raise e
        if devkit.steamos_status is None:
            devkit.steamos_status = {}
            raise Exception('SteamOS get status failed, check status window')
        self.signal_steamos_status.emit(devkit=devkit)
        return devkit.steamos_status

    def steamos_get_status(self, *args):
        return self.executor.submit(self._steamos_get_status, *args)

    def _steamos_get_status_after_delay(self, devkit, delay):
        time.sleep(delay)
        self._steamos_get_status(devkit)

    def steamos_get_status_after_delay(self, devkit, delay):
        return self.executor.submit(self._steamos_get_status_after_delay, devkit, delay)

    def _list_games(self, devkit):
        class ListGamesArgs:
            def __init__(self, devkit):
                self.machine, self.machine_name_type = devkit.machine_command_args
                self.http_port = devkit.http_port
                self.login = None
        return devkit_client.list_games(ListGamesArgs(devkit))

    def list_games(self, *args):
        return self.executor.submit(self._list_games, *args)

    def _register(self, devkit):
        class RegisterArgs:
            def __init__(self, devkit):
                self.machine, self.machine_name_type = devkit.machine_command_args
                self.http_port = devkit.http_port
        return devkit_client.register(RegisterArgs(devkit))

    def register(self, *args):
        return self.executor.submit(self._register, *args)

    def _update_game(self, devkit, restart_steam, use_mask_unmask, prevent_auto_repair, gdbserver, select_runtime, steam_play_debug, steam_play_debug_version, *args):

        class NewGameArgs:
            def __init__(
                self,
                devkit,
                restart_steam,
                use_mask_unmask,
                prevent_auto_repair,
                title_name,
                local_folder,
                delete_extraneous,
                skip_newer_files,
                verify_checksums,
                args_or_cmdline,
                filter_args,
                dependencies,
                cancel_signal,
                force_appid,
                env_vars,
                lepton_args=''
            ):
                self.machine, self.machine_name_type = devkit.machine_command_args
                self.restart_steam = restart_steam      # Valve only
                self.use_mask_unmask = use_mask_unmask  # Valve only
                self.prevent_auto_repair = prevent_auto_repair  # Valve only
                self.http_port = devkit.http_port
                self.name = title_name
                self.directory = local_folder
                assert type(args_or_cmdline) is list
                self.argv = args_or_cmdline
                self.login = None
                self.delete_extraneous = delete_extraneous
                self.skip_newer_files = skip_newer_files
                self.verify_checksums = verify_checksums
                self.filter_args = filter_args
                self.steam_play_debug = SteamPlayDebug.Disabled
                self.deps = dependencies
                self.cancel_signal = cancel_signal
                self.force_appid = force_appid
                self.lepton_args = lepton_args
                # An array of name=value entries that will go into the settings file
                self.set_keyval = []
                self.env_vars = env_vars

        new_game_args = NewGameArgs(devkit, restart_steam, use_mask_unmask, prevent_auto_repair, *args)
        if select_runtime in (devkit_client.RuntimeOptions.SteamPlay, devkit_client.RuntimeOptions.Proton_Experimental):
            # access via getattr in the low level
            new_game_args.set_keyval = [
                'steam_play=1',
                f'steam_play_debug={int(steam_play_debug)}',
                f'steam_play_debug_version={steam_play_debug_version}'
            ]
            new_game_args.steam_play_debug = steam_play_debug
        else:
            new_game_args.set_keyval = ['steam_play=0']
        compat_tool_alias = devkit_client.RUNTIME_ALIASES.get(select_runtime, '')
        new_game_args.set_keyval.append(f'compat_tool={compat_tool_alias}')
        if gdbserver:
            new_game_args.set_keyval.append('gdbserver=1')
        if restart_steam and devkit.is_deckard:
            devkit.client_is_masked = use_mask_unmask
            devkit.use_mask_unmask = use_mask_unmask
        result = devkit_client.new_or_ensure_game(new_game_args)
        if not result:
            raise Exception("new_or_ensure_game command failed, check console")
        return True

    def update_game(self, *args):
        return self.executor.submit(self._update_game, *args)

    def _set_steam_client(self, devkit, title_name, set_config, cmdline_args, wait, gdbserver):
        class SetSteamClientArgs:
            def __init__(self, devkit, title_name, set_config, cmdline_args, gdbserver):
                self.machine, self.machine_name_type = devkit.machine_command_args
                self.login = None
                self.http_port = devkit.http_port
                self.name = title_name
                self.set_config = set_config
                self.args = cmdline_args
                self.gdbserver = gdbserver

        set_steam_client_args = SetSteamClientArgs(devkit, title_name, set_config, cmdline_args, gdbserver)
        devkit_client.set_steam_client(set_steam_client_args)
        self._restart_session(devkit)
        if wait:
            class GetStatusArgs:
                def __init__(self, devkit):
                    self.machine, self.machine_name_type = devkit.machine_command_args
                    self.http_port = devkit.http_port
                    self.login = None
            get_status_args = GetStatusArgs(devkit)
            count = 0
            while count < 10:
                count += 1
                time.sleep(1)
                if self.shutting_down:
                    return True
                try:
                    steamos_status = devkit_client.steamos_get_status(get_status_args)
                except Exception as e:
                    devkit_client.log_exception(e)
                    logger.error('SteamOS get status failed during set steam client, wait and retry')
                    continue
                if steamos_status is None:
                    continue # is also error condition on the status
                devkit.steamos_status = steamos_status
                self.signal_steamos_status.emit(devkit=devkit)
                if devkit.steam_client_status != 'SteamStatus.NOT_RUNNING':
                    return True # reached the other side
        return True

    def set_steam_client(self, *args):
        return self.executor.submit(self._set_steam_client, *args)

    def _sync_logs(self, devkit, logs_folder):
        class SyncLogsArgs:
            def __init__(self, devkit, logs_folder):
                self.machine, self.machine_name_type = devkit.machine_command_args
                self.http_port = devkit.http_port
                self.local_folder = logs_folder
                self.device_name = devkit.name
                self.steamvr_logpath = devkit.steamvr_logpath

        sync_logs_args = SyncLogsArgs(devkit, logs_folder)
        devkit_client.sync_logs(sync_logs_args)

        return True

    def sync_logs(self, devkit, logs_folder):
        return self.executor.submit(self._sync_logs, devkit, logs_folder)

    def _open_remote_shell(self, devkit):
        remote_shell_args = devkit_client.ResolveMachineArgs(devkit)
        p = devkit_client.remote_shell(remote_shell_args)
        return p

    def open_remote_shell(self, devkit):
        return self.executor.submit(self._open_remote_shell, devkit)

    def _open_cef_console(self, devkit):

        class CEFConsoleArgs:
            def __init__(self, devkit):
                self.machine, self.machine_name_type = devkit.machine_command_args
                self.http_port = devkit.http_port
                self.login = None
        cef_console_args = CEFConsoleArgs(devkit)
        devkit_client.cef_console(cef_console_args)
        return True

    def open_cef_console(self, devkit):
        return self.executor.submit(self._open_cef_console, devkit)

    def _gpu_trace(self, *args):
        class GPUTraceArgs:
            def __init__(self, devkit, local_filename, launch, gpuvis_path):
                self.machine, self.machine_name_type = devkit.machine_command_args
                self.http_port = devkit.http_port
                self.login = None
                self.local_filename = local_filename
                self.launch = launch
                self.gpuvis_path = gpuvis_path
        gpu_trace_args = GPUTraceArgs(*args)
        devkit_client.gpu_trace(gpu_trace_args)

    def gpu_trace(self, *args):
        return self.executor.submit(self._gpu_trace, *args)

    def _rgp_capture(self, *args):
        class RGPCaptureArgs:
            def __init__(self, devkit, local_folder, launch, rgp_path):
                self.machine, self.machine_name_type = devkit.machine_command_args
                self.http_port = devkit.http_port
                self.login = None
                self.local_folder = local_folder
                self.launch = launch
                self.rgp_path = rgp_path
        rgp_capture_args = RGPCaptureArgs(*args)
        devkit_client.rgp_capture(rgp_capture_args)

    def rgp_capture(self, *args):
        return self.executor.submit(self._rgp_capture, *args)

    def _restart_session(self, devkit):
        class RestartSessionArgs:
            def __init__(self, devkit):
                self.machine, self.machine_name_type = devkit.machine_command_args
                self.http_port = devkit.http_port
                self.login = None
                self.is_deckard = devkit.is_deckard
                self.session_select = devkit.steamos_status['session_select']
        session_restart_args = RestartSessionArgs(devkit)
        devkit_client.restart_session(session_restart_args)
        devkit.client_is_masked = False

    def restart_session(self, devkit):
        return self.executor.submit(self._restart_session, devkit)


    def _screenshot(self, *args):

        class ScreenshotArgs:
            def __init__(self, devkit, folder, filename, do_timestamp, xprop):
                self.machine, self.machine_name_type = devkit.machine_command_args
                self.is_deckard = devkit.is_deckard
                self.http_port = devkit.http_port
                self.login = None
                self.folder = folder
                self.filename = filename
                self.do_timestamp = do_timestamp
                self.xprop = xprop
        screenshot_args = ScreenshotArgs(*args)
        devkit_client.screenshot(screenshot_args)

    def screenshot(self, *args):
        return self.executor.submit(self._screenshot, *args)

    def _check_port(self, host, port):
        logger.debug(f'Checking if {host}:{port} is open.')
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(int(self.conf.check_port_timeout))
        start = time.time()
        try:
            ret = s.connect_ex((host, port))
        except Exception as e:
            devkit_client.log_exception(e)
            logger.warning(f'Port {port} on host {host} is unreachable.')
            return False
        if ret != 0:
            # NOTE: despite what the python documentation suggests, I am not observing a TimeoutError exception but instead getting EAGAIN here in case of timeout
            logger.error(f'socket.connect_ex errno: {ret} {errno.errorcode[ret]} {os.strerror(ret)}')
            logger.warning(f'Port {port} on host {host} is unreachable.')
            return False
        replied = time.time()
        latency_ms = int( ( replied - start ) * 1000 )
        logger.info(f'Port {port} on host {host} is open - latency {latency_ms} ms')
        return True

    def _check_connectivity(self, devkit):
        machine = devkit_client.resolve_machine(
            devkit.machine_command_args[0],
            name_type=devkit.machine_command_args[1],
            http_port=devkit.http_port
        )

        # NOTE: http_port may already be a non standard port through the mDNS properties
        devkit.http_connectivity = self._check_port(machine.address, devkit.http_port)

        if devkit.http_connectivity:
            # Pull the properties from the service
            request = urllib.request.Request(f'http://{machine.address}:{devkit.http_port}/properties.json')
            try:
                result = urllib.request.urlopen(request)
            except Exception as e:
                devkit_client.log_exception(e)
                # Doesn't look like a devkit service, or some other problem
                devkit.http_connectivity = False
            else:
                properties_payload = result.read().decode('utf-8', 'replace')
                logger.debug(f'properties payload: {properties_payload!r}')
                # we are seeing a situation where strict parsing fails, but not much details on what's going on
                decoder = json.JSONDecoder(strict=False)
                devkit.service_properties = decoder.decode(properties_payload)
                # unwrap some more
                devkit.service_properties['settings'] = decoder.decode(devkit.service_properties['settings'])

        devkit.ssh_connectivity = self._check_port(machine.address, 22)
        return machine

    def _set_session(self, devkit, *args):
        class SetSessionArgs:
            def __init__(self, devkit, session, wait):
                self.machine, self.machine_name_type = devkit.machine_command_args
                self.http_port = devkit.http_port
                self.login = None
                self.session = session
                # will force a wait and return of a steamos_status
                self.wait = wait
                self.session_select = devkit.steamos_status['session_select']
        devkit.steamos_status = devkit_client.set_session(SetSessionArgs(devkit, *args))
        if devkit.steamos_status is None:
            devkit.steamos_status = {}

    def set_session(self, *args):
        return self.executor.submit(self._set_session, *args)

    def _dump_controller_config(self, *args):
        class DumpControllerConfigArgs:
            def __init__(self, devkit, appid, gameid, folder):
                self.machine, self.machine_name_type = devkit.machine_command_args
                self.http_port = devkit.http_port
                self.login = None
                self.appid = appid if ( appid is not None and len(appid) > 0 ) else None
                self.gameid = gameid if ( gameid is not None and len(gameid) > 0 ) else None
                self.folder = folder
                assert self.appid or self.gameid # at least one of these is required
        return devkit_client.dump_controller_config(DumpControllerConfigArgs(*args))

    def dump_controller_config(self, *args):
        return self.executor.submit(self._dump_controller_config, *args)

    def _delete_title(self, *args):
        class DeleteTitleArgs:
            def __init__(self, devkit, gameid, delete_all, reset_steam_client):
                self.machine, self.machine_name_type = devkit.machine_command_args
                self.http_port = devkit.http_port
                self.login = None
                self.gameid = gameid if ( gameid is not None and len(gameid) > 0 ) else None
                self.delete_all = delete_all
                self.reset_steam_client = reset_steam_client
        return devkit_client.delete_title(DeleteTitleArgs(*args))

    def delete_title(self, *args):
        return self.executor.submit(self._delete_title, *args)

    def _simple_command(self, *args):
        return devkit_client.simple_command(*args)

    def simple_command(self, *args):
        return self.executor.submit(self._simple_command, *args)

    def _sync_pattern(self, *args):
        return devkit_client.sync_pattern(*args)

    def sync_pattern(self, *args):
        return self.executor.submit(self._sync_pattern, *args)

    def _browse_files(self, devkit):
        filezilla = None
        if platform.system() == 'Windows':
            filezilla = self._windows_find_filezilla()
        if filezilla is None:
            filezilla = shutil.which('filezilla')
        if filezilla is None or not os.path.exists(filezilla):
            raise Exception('FileZilla not found. Please install in order to use this feature.')
        cmd = [filezilla, '-l', 'ask', f'sftp://{devkit.machine.login}@{devkit.machine.address}']
        devkit_client.spawn_detached(cmd)

    def _windows_find_filezilla(self):
        def try_key(path, access=winreg.KEY_READ):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, access) as key:
                    return winreg.QueryValue(key, None)
            except OSError:
                return None

        candidates = []

        app_path = try_key(r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\filezilla.exe',
                           winreg.KEY_READ | winreg.KEY_WOW64_32KEY)
        if app_path:
            candidates.append(app_path)

        app_path = try_key(r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\filezilla.exe')
        if app_path:
            candidates.append(app_path)

        install_dir = try_key(r'SOFTWARE\FileZilla Client', winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
        if install_dir:
            candidates.append(os.path.join(install_dir, 'filezilla.exe'))

        install_dir = try_key(r'SOFTWARE\FileZilla Client')
        if install_dir:
            candidates.append(os.path.join(install_dir, 'filezilla.exe'))

        install_dir = try_key(r'SOFTWARE\Wow6432Node\FileZilla Client',
                              winreg.KEY_READ | winreg.KEY_WOW64_32KEY)
        if install_dir:
            candidates.append(os.path.join(install_dir, 'filezilla.exe'))

        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                logger.info(f'Found FileZilla at {candidate}')
                return candidate

        logger.info('FileZilla not found in registry')
        return None

    def browse_files(self, *args):
        return self.executor.submit(self._browse_files, *args)

    def _set_password(self, devkit):
        remote_shell_args = devkit_client.ResolveMachineArgs(devkit)
        p = devkit_client.set_password(remote_shell_args)
        # wait under the modal so the UI can trigger a refresh afterwards
        p.communicate()
        logger.info(f'set_password child process exited with code {p.returncode}')

    def set_password(self, *args):
        return self.executor.submit(self._set_password, *args)

    def _config_steam_wrapper_flags(self, devkit, enable=None, disable=None):
        return devkit_client.config_steam_wrapper_flags(devkit, enable, disable)

    def config_steam_wrapper_flags(self, *args, **kwargs):
        return self.executor.submit(self._config_steam_wrapper_flags, *args, **kwargs)

    def _set_renderdoc_replay(self, *args):
        return devkit_client.set_renderdoc_replay(*args)

    def set_renderdoc_replay(self, *args):
        return self.executor.submit(self._set_renderdoc_replay, *args)

    def _enable_cef_debugging(self, devkit):
        devkit_client.enable_cef_debugging(devkit)
        self._restart_session(devkit)
        # we put a short wait so the status can pick up the right state
        time.sleep(5)
        return self._steamos_get_status(devkit)

    def enable_cef_debugging(self, *args):
        return self.executor.submit(self._enable_cef_debugging, *args)

    def _run_game(self, *args):
        return devkit_client.run_game(*args)

    def run_game(self, *args):
        return self.executor.submit(self._run_game, *args)

class DevkitState(enum.Enum):
    devkit_init = enum.auto()
    devkit_registering = enum.auto()
    devkit_init_failed = enum.auto()
    devkit_release = enum.auto()
    devkit_not_registered = enum.auto()
    devkit_online = enum.auto()

class DevkitNotRegistered(Exception):
    pass

class DevkitNoConnectivity(Exception):
    pass

class DevkitReleased(Exception):
    pass

class Devkit:
    ADDED_BY_IP_KEY = 'Devkit.AddedByIP'

    def __init__(self, devkit_commands, settings, zc_listener=None, service_name=None, address=None, port=devkit_client.DEFAULT_DEVKIT_SERVICE_HTTP):
        self.devkit_commands = devkit_commands
        self.settings = settings
        # both set if added as a service (None otherwise)
        self.zc_listener = zc_listener
        self.service_name = service_name
        # set if added by address (None otherwise)
        self.address = address
        assert self.service_name is not None or self.address is not None
        assert ( self.service_name is None ) == ( self.zc_listener is None )
        self.state = DevkitState.devkit_init
        # set once state reaches devkit_online (None otherwise)
        self.machine = None
        self.init_future = None
        self.register_future = None
        self.register_done_future = None
        # connectivity checks - tri-state
        self.ssh_connectivity = None
        self.http_connectivity = None
        self.service_properties = None # filled with the devkit service properties.json after a successful connectivity check
        # dictionary representing the steamos device status obtained via the devkit-utils/steamos-get-status command
        self.steamos_status = {}
        if self.zc_listener:
            self._http_port = self.zc_listener.port_for_service(self.service_name)
        else:
            self._http_port = port
        # tracking of a masked state for the steam client service on device,
        # so we can avoid situations where an error leaves the client in a disabled state as much as possible
        self.client_is_masked = False
        self.use_mask_unmask = False

    # returns a tri-state as well
    @property
    def limited_connectivity(self):
        if self.ssh_connectivity is None or self.http_connectivity is None:
            return None
        return (not self.ssh_connectivity) or (not self.http_connectivity)

    @property
    def added_by_ip(self):
        return self.address is not None

    @property
    def name(self):
        # Human friendly name, either the service or the address
        if self.service_name is not None:
            return self.service_name
        assert self.address is not None
        return self.address

    @property
    def full_name(self):
        # Even more verbose and human friendly name
        if self.service_name is not None:
            return '{} ({})'.format(self.service_name, self.zc_listener.address_for_service(self.service_name))
        _hostname = self.hostname if self.hostname else 'pending'
        return '{} ({})'.format(_hostname, self.address)

    @property
    def machine_command_args(self):
        if self.service_name is not None:
            return (self.service_name, devkit_client.MachineNameType.SERVICE_NAME)
        return (self.address, devkit_client.MachineNameType.ADDRESS)

    @property
    def is_deckard(self):
        return self.steamos_status.get('is_deckard', False)

    @property
    def steamvr_logpath(self):
        return self.steamos_status.get('steamvr_logpath', None)

    @property
    def http_port(self):
        return self._http_port

    @http_port.setter
    def http_port(self, value):
        self._http_port = value

    @property
    def steam_client_status(self):
        '''Status of the Steam client on the device'''
        return self.steamos_status.get('steam_status', 'SteamStatus.ERROR')

    @property
    def steam_configuration(self):
        '''Intended configuration of the Steam client on the device'''
        return self.steamos_status.get('steam_configuration', 'SteamStatus.ERROR')

    @property
    def cef_debugging_enabled(self):
        return self.steamos_status.get('cef_debugging_enabled', False)

    @property
    def osclient_steam_version(self):
        return self.steamos_status.get('steam_osclient_version', None)

    @property
    def hostname(self):
        return self.steamos_status.get('hostname', None)

    @property
    def os_name(self):
        return self.steamos_status.get('os_name', None)

    @property
    def os_version(self):
        return self.steamos_status.get('os_version', None)

    @property
    def user_password_is_set(self):
        return self.steamos_status.get('user_password_is_set', False)

    @property
    def is_renderdoc_capture_enabled(self):
        return self.steamos_status.get('steam_launch_flags', {}).get('ENABLE_VULKAN_RENDERDOC_CAPTURE', False)

    @is_renderdoc_capture_enabled.setter
    def is_renderdoc_capture_enabled(self, enabled):
        status_flags = self.steamos_status.get('steam_launch_flags', {})
        if enabled:
            status_flags['ENABLE_VULKAN_RENDERDOC_CAPTURE'] = '1'
        elif 'ENABLE_VULKAN_RENDERDOC_CAPTURE' in status_flags:
            del status_flags['ENABLE_VULKAN_RENDERDOC_CAPTURE']

    @property
    def is_proton_log_enabled(self):
        return self.steamos_status.get('steam_launch_flags', {}).get('PROTON_LOG', False)

    @is_proton_log_enabled.setter
    def is_proton_log_enabled(self, enabled):
        status_flags = self.steamos_status.get('steam_launch_flags', {})
        if enabled:
            status_flags['PROTON_LOG'] = '1'
            if self.settings[ProtonLogs.WINEDEBUG_KEY] != '':
                status_flags['PROTON_LOG'] = self.settings[ProtonLogs.WINEDEBUG_KEY]
        elif 'PROTON_LOG' in status_flags:
            del status_flags['PROTON_LOG']

    def has_mdns_service(self):
        return self.service_name is not None

    def get_device_setting(self, setting_name, default=None):
        key = f'Device.{self.name}.{setting_name}'
        return self.settings.get(key, default)

    def set_device_setting(self, setting_name, value):
        key = f'Device.{self.name}.{setting_name}'
        self.settings[key] = value
        self.settings.save_settings()

    def setup(self):
        assert self.state == DevkitState.devkit_init
        self.init_future = self.devkit_commands.identify(self)
        self.init_future.add_done_callback(self.on_init_done)
        if self.added_by_ip:
            ip_set = self.settings.get(self.ADDED_BY_IP_KEY, set())
            if self.address in ip_set:
                ip_set.remove(self.address)
            ip_set.add((self.address, self.http_port))
            self.settings[self.ADDED_BY_IP_KEY] = ip_set

    def forget_added_by_ip(self):
        assert self.added_by_ip
        ip_set = self.settings.get(self.ADDED_BY_IP_KEY, set())
        ip_set.remove((self.address, self.http_port))
        self.settings[self.ADDED_BY_IP_KEY] = ip_set
        self.settings.save_settings()

    def register(self):
        assert self.state == DevkitState.devkit_not_registered
        self.state = DevkitState.devkit_registering
        self.register_future = self.devkit_commands.register(self)
        self.register_future.add_done_callback(self.on_register_done)
        self.register_done_future = concurrent.futures.Future()
        self.register_done_future.set_running_or_notify_cancel()
        return self.register_done_future

    def on_init_done(self, f):
        assert f is self.init_future
        try:
            (machine, steamos_status) = f.result()
        except DevkitReleased:
            # this devkit instance has been abandonned
            return
        except DevkitNotRegistered as e:
            self.state = DevkitState.devkit_not_registered
        except DevkitNoConnectivity as e:
            self.state = DevkitState.devkit_init_failed
        except Exception as e:
            devkit_client.log_exception(e)
            logger.error('%r: identify command failed', self.name)
            self.state = DevkitState.devkit_init_failed
        else:
            self.machine = machine
            self.steamos_status = steamos_status
            self.state = DevkitState.devkit_online
            # Emit the status signal now that the device is online
            self.devkit_commands.signal_steamos_status.emit(devkit=self)

    def on_register_done(self, f):
        # We process register_future and fire register_done_future for the UI
        assert f is self.register_future
        assert f.done()
        e = f.exception()
        if e is not None:
            logger.error('%r: register command failed', self.name)
            if type(e) is urllib.error.HTTPError and e.code == 403:
                # Pull more useful information from the error
                error_report = e.fp.read().decode('utf-8')
                # We get a very loosely structured text response, but with newer devkit service releases we can hope to get the json error payload from ssh-approve-key
                found_error = False
                for line in error_report.split('\n'):
                    try:
                        ret = json.loads(line)
                    except:
                        # write out the text lines
                        logger.error(line)
                    else:
                        # raise a propagated error from ssh-approve-key as a modal error
                        self.register_done_future.set_exception(Exception(ret['error']))
                        found_error = True
                        break
                # If no error json was obtained, raise a generic error
                if not found_error:
                    self.register_done_future.set_exception(Exception('Registration failed, see console'))
            else:
                # Push the exception as is, it's not a type that we know how to process
                self.register_done_future.set_exception(e)
            self.state = DevkitState.devkit_not_registered
            return
        self.state = DevkitState.devkit_init
        self.register_done_future.set_result(True)
        self.setup()


class Toolbar:
    '''Command toolbar, toggling tool windows and executing commands.'''

    def __init__(self, viewport):
        self.viewport = viewport
        self.height = 35
        self.signal_pressed = signalslot.Signal(args = ['name'])
        self.selected_devkit = None
        self.tool_window_names = set()
        self.modal_dialog = None

    @property
    def is_devkit_selected(self):
        return self.selected_devkit is not None

    def setup(self):
        self.viewport.signal_draw.connect(self.on_draw)

    def on_draw(self, **kwargs):
        pressed_buttons = []
        imgui.set_next_window_position(0, 0, imgui.ALWAYS)
        imgui.set_next_window_size(self.viewport.width, self.height, imgui.ALWAYS)
        imgui.begin('Toolbar', False, imgui.WINDOW_NO_MOVE | imgui.WINDOW_NO_COLLAPSE | imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_RESIZE)
        for button_name in (
            DevkitsWindow.BUTTON_NAME,
            ConsoleWindow.BUTTON_NAME,
        ):
            if imgui.button(button_name):
                pressed_buttons.append(button_name)
            imgui.same_line()
        if self.is_devkit_selected:
            active_buttons = [
                UpdateTitle.BUTTON_NAME,
                DeviceLogs.BUTTON_NAME,
            ]
            for button_name in active_buttons:
                if imgui.button(button_name):
                    pressed_buttons.append(button_name)
                imgui.same_line()
        imgui.end()
        for button_name in pressed_buttons:
            # Signal needs to be fired outside of imgui begin/end blocks so draws can be done in the handlers
            self.signal_pressed.emit(name=button_name, selected_devkit=self.selected_devkit)
        if self.modal_dialog is not None:
            if not self.modal_dialog.draw():
                self.modal_dialog = None

    def focus_console(self):
        self.signal_pressed.emit(name=ConsoleWindow.BUTTON_NAME, selected_devkit=self.selected_devkit)


class ToolWindow:
    '''Manage layout and visibility for tool windows.'''

    def __init__(self, name, viewport, toolbar):
        self.name = name
        self.viewport = viewport
        self.toolbar = toolbar
        self.visible = False
        self.focus_trigger = True
        # By default a ToolWindow is only ticked when it's visible
        self.always_tick = False
        # By default a ToolWindow does not tick if there is no devkit selected
        self.tick_without_devkit = False

    def setup(self):
        self.viewport.signal_draw.connect(self.on_draw)
        self.toolbar.signal_pressed.connect(self.on_pressed)
        self.toolbar.tool_window_names.add(self.name)

    def on_pressed(self, name, **kwargs):
        if name != self.name:
            if name in self.toolbar.tool_window_names:
                #logger.debug(f'Hiding tool window {self.name} because {name} was pressed')
                self.visible = False
            return
        #logger.debug(f'Showing tool window {self.name} because {self.name} was pressed')
        self.visible = True
        self.focus_trigger = True

    def on_draw(self, **kwargs):
        if not self.visible:
            if self.always_tick:
                self.tick(visible=False)
            return
        if not self.toolbar.is_devkit_selected and not self.tick_without_devkit:
            return
        # Size up the window to fill the viewport on the first draw
        imgui.set_next_window_position(0, self.toolbar.height, imgui.ALWAYS)
        imgui.set_next_window_size(self.viewport.width, self.viewport.height - self.toolbar.height, imgui.ALWAYS)
        if self.focus_trigger:
            imgui.set_next_window_focus()
            self.focus_trigger = False
        # NOTE: draw is only called if the window is visible!
        self.tick(visible=True)

    def tick(self, visible):
        '''Customize in child classes'''
        pass

    def show_error_modal(self, error_message, title='Error'):
        '''Show a modal error dialog to the user'''
        failed_future = concurrent.futures.Future()
        failed_future.set_exception(Exception(error_message))
        self.toolbar.modal_dialog = ModalWait(
            self.viewport,
            self.toolbar,
            title,
            failed_future
        )


class ModalWait:
    '''A modal dialog to wrap slow devkit operations'''
    def __init__(
        self, viewport, toolbar, title, task_future,
        exit_on_success=False,
        cancel_signal=False,
        ):
        self.viewport = viewport
        self.toolbar = toolbar
        self.title = title
        self.task_future = task_future
        self.exit_on_success = exit_on_success

        self.output_text = ''
        self.dialog_width = 0
        self.dialog_height = 0
        self.user_resized = False   # If the user manipulates the dialog size, stop our auto size updates

        self._result = None
        self._error = None
        # emitted when the async task completes
        self.signal_task_done = signalslot.Signal()
        # emitted when the dialog is dismissed
        self.signal_task_dismiss = signalslot.Signal()
        # Replace the output text:
        # - replaces 'Please Wait...' while waiting
        # - replaces the final message after completion
        self._override_output_text = None
        self.cancel_signal = signalslot.Signal() if cancel_signal else None

    @property
    def result(self):
        return self._result

    @property
    def error(self):
        return self._error

    @property
    def override_output_text(self):
        return self._override_output_text

    @override_output_text.setter
    def override_output_text(self, value):
        self._override_output_text = value

    def draw(self):
        # This would be a lot more simple if I had found a way to have imgui auto resize the layout based on content
        # But either I'm too dumb to figure it out, or it's not possible in 1.77
        output_text = self._override_output_text if self._override_output_text is not None else 'Please wait..'
        in_progress = True      # Abort/OK button
        trigger_resize = False  # Force a dialog resize to fit additional text
        if self.task_future.done():
            in_progress = False
            if self._result is None and self._error is None:
                # Reset output text override, so we can override the wait and the final message independently
                self._override_output_text = None
                # Runs once: collecting either a result, or an error
                try:
                    self._result = self.task_future.result()
                    if self.exit_on_success:
                        if len(self.signal_task_done.slots):
                            # This is spammy, we setup a signal_task_done signal to receive error notifications
                            #logger.warning('WARNING: ModalWait: signal_task_done has active slots, but does not fire when exit_on_success is set')
                            pass
                        self.signal_task_dismiss.emit()
                        return False
                except Exception as e:
                    self._error = e
                    devkit_client.log_exception(e)
                    # FIXME: is this appropriate? jumping to the console any time we process an exception? I suspect not
                    self.toolbar.focus_console()
                self.signal_task_done.emit()
            if not self._override_output_text is None:
                # Output text was set externally
                output_text = self._override_output_text
            else:
                # Setup the result message to display according to some default rules
                if not self._error is None:
                    output_text = str(self._error)
                    if not output_text.startswith('ERROR:'):
                        output_text = f'ERROR: {output_text}'
                else:
                    output_text = str(self._result)
        if output_text != self.output_text:
            trigger_resize = True
            self.output_text = output_text

        button_offset = 58 # account for button vertical space when going from text size to dialog size

        if trigger_resize and not self.user_resized:
            (text_width, text_height) = imgui_calc_text_size(self.output_text)
            # give a bit more room vertically between the multiline box and the button
            text_height += 8
            # minimum dimensions, only increase dimensions on auto-resize, never exceed viewport size
            self.dialog_width = min(self.viewport.width, max(15*CHARACTER_WIDTH, len(self.title)*CHARACTER_WIDTH, text_width, self.dialog_width))
            # account for the button vertical space at the bottom
            self.dialog_height = min(self.viewport.height, max(3*CHARACTER_HEIGHT+button_offset, text_height+button_offset, self.dialog_height))
            #logger.info('set dialog size to %dx%d', self.dialog_width, self.dialog_height)
            imgui.set_next_window_size(self.dialog_width, self.dialog_height)
            x = ( self.viewport.width - self.dialog_width ) / 2
            y = ( self.viewport.height - self.dialog_height ) / 2
            imgui.set_next_window_position(x, y)

        imgui.open_popup(self.title)
        if imgui.begin_popup_modal(self.title):
            imgui.begin_child('message', imgui.get_window_width(), imgui.get_window_height()-button_offset)
            imgui.input_text_multiline('', self.output_text, -1, imgui.get_window_width(), imgui.get_window_height(), imgui.INPUT_TEXT_READ_ONLY)
            imgui.end_child()

            if in_progress:
                if self.cancel_signal:
                    if imgui.button('Cancel'):
                        self.cancel_signal.emit()
            else:
                dismiss = False
                if self._error is None:
                    dismiss = imgui.button('OK')
                else:
                    imgui.push_style_color(imgui.COLOR_BUTTON, 1, 0, 0)
                    dismiss = imgui.button('DISMISS')
                    imgui.pop_style_color()

                # Press OK button, or hit escape/enter to dismiss once the task is complete
                keyboard_state = sdl2.SDL_GetKeyboardState(None)
                dismiss |= keyboard_state[sdl2.SDL_SCANCODE_ESCAPE] or keyboard_state[sdl2.SDL_SCANCODE_RETURN] or keyboard_state[sdl2.SDL_SCANCODE_KP_ENTER]

                # Enables a late programmatic dismiss, allowing for a signal_task_done
                dismiss |= ( self.exit_on_success and self._error is None )

                if dismiss:
                    imgui.close_current_popup()
                    imgui.end_popup()
                    self.signal_task_dismiss.emit()
                    return False

            if not self.user_resized:
                s = imgui.get_window_size()
                if s.x != self.dialog_width or s.y != self.dialog_height:
                    logger.info('user resized the modal dialog - disabling further size auto updates')
                    self.user_resized = True

            imgui.end_popup()
        return True


class DevkitsWindow(ToolWindow):
    '''List online devkits, support registration against a kit and selection for operations.'''

    BUTTON_NAME = 'Devkits'

    def __init__(self,
                conf,
                devkit_commands,
                settings,
                screenshot,
                perf_overlay,
                gpu_trace,
                rgp_capture,
                renderdoc_capture,
                proton_logs,
                controller_configs,
                delete_title,
                shutdown_signal,
                *args):
        super(DevkitsWindow, self).__init__(self.BUTTON_NAME, *args)
        self.conf = conf
        self.devkit_commands = devkit_commands
        self.settings = settings
        self.screenshot = screenshot
        self.perf_overlay = perf_overlay
        self.gpu_trace = gpu_trace
        self.rgp_capture = rgp_capture
        self.renderdoc_capture = renderdoc_capture
        self.proton_logs = proton_logs
        self.controller_configs = controller_configs
        self.delete_title = delete_title
        self.shutdown_signal = shutdown_signal
        # Visible by default
        self.visible = True
        # Tick every frame regardless of visibility for zeroconf browser
        self.always_tick = True
        # Draw even when no kit is active
        self.tick_without_devkit = True
        self.zc = None
        self.zc_listener = None
        self.zc_browser = None
        self.devkits = collections.OrderedDict()
        self._selected_devkit_name = None
        # Keep the same devkit selected across application restarts
        self.preferred_devkit_name = None
        self.signal_selected_devkit = signalslot.Signal(args=['devkit'])
        self.add_by_ip_text = ''
        self.add_by_ip_port = '{}'.format(devkit_client.DEFAULT_DEVKIT_SERVICE_HTTP)
        self.steam_client_args = None
        self.frame_osclient_extra_args = None # only Steam Frame OS client
        self.first_draw = True
        # Hook into status updates to refresh the command line arguments
        self.devkit_commands.signal_steamos_status.connect(self.on_steamos_status)
        # Indicates whether Valve internal services are available
        self.valve_mode = False

    def setup(self):
        super(DevkitsWindow, self).setup()
        self.zc = zeroconf.Zeroconf()
        self.zc_listener = devkit_client.ServiceListener(self.zc)
        self.zc_browser = zeroconf.ServiceBrowser(
            self.zc,
            devkit_client.STEAM_DEVKIT_TYPE,
            self.zc_listener
        )
        self.preferred_devkit_name = self.settings.get('DevkitsWindow.preferred_devkit_name', None)
        devkits_by_ip = self.settings.get(Devkit.ADDED_BY_IP_KEY, set())
        for address in devkits_by_ip:
            addr = address
            port = devkit_client.DEFAULT_DEVKIT_SERVICE_HTTP
            if (isinstance(address, tuple)):
                addr, port = address
            logger.info(f'Attempt to initialize a devkit previously added by IP: {addr} with port {port}')
            devkit = Devkit(self.devkit_commands, self.settings, address=addr, port=port)
            devkit.setup()
            self.devkits[devkit.name] = devkit
        # Save in case any changes were made by above loop
        self.settings.save_settings()

    def __del__(self):
        if self.zc is not None:
            self.zc.close()
            self.zc = None

    # TODO: support multi select
    @property
    def selected_devkit(self):
        if self._selected_devkit_name is None:
            return None
        if not self._selected_devkit_name in self.devkits:
            logger.warning('Selected devkit is no longer available: %r', self._selected_devkit_name)
            self._selected_devkit_name = None
            self.signal_selected_devkit.emit(kit=None)
            return None
        devkit = self.devkits[self._selected_devkit_name]
        if devkit.state != DevkitState.devkit_online:
            logger.warning('Selected devkit is not in online state: %r', devkit.state)
            self._selected_devkit_name = None
            self.signal_selected_devkit.emit(kit=None)
            return None
        return devkit

    # the public release of the devkit tool does not have support for Steam client sideload
    # but still uses this function to enable command line argument overrides
    def _set_steam_client(self, target_steam_client, arguments):
        set_steam_client_future = self.devkit_commands.set_steam_client(
            self.selected_devkit,
            'steam',
            target_steam_client,
            arguments,
            True,                   # wait
            False,                  # we never set gdbserver debug from the devkits window
        )
        self.toolbar.modal_dialog = ModalWait(
            self.viewport,
            self.toolbar,
            f'Changing the Steam client config on {self.selected_devkit.name!r}',
            set_steam_client_future,
            exit_on_success=True,
        )

    def _clear_cached(self):
        self.steam_client_args = None
        self.frame_osclient_extra_args = None

    def on_steamos_status(self, devkit, **kwargs):
        self._clear_cached()

    def on_selected_devkit(self, kit, **kwargs):
        # propagate to the toolbar
        self.toolbar.selected_devkit = kit
        self._clear_cached()

    def _terminate_terminal_process(self, p):
        if p.poll() is not None:
            return # already exited
        if platform.system() == 'Windows':
            # terminate would only kill powershell.exe and effectively leave the console up..
            # https://stackoverflow.com/questions/1230669/subprocess-deleting-child-processes-in-windows
            subprocess.call(['taskkill', '/F', '/T', '/PID', str(p.pid)])
        else:
            p.terminate()
        p.wait()


    def _on_shutdown_signal(self, **kwargs):
        pass

    def register_kit(self, kit):
        register_future = kit.register()
        self.toolbar.modal_dialog = ModalWait(
            self.viewport,
            self.toolbar,
            'Registering with devkit {!r}'.format(kit.name),
            register_future,
            exit_on_success=True
        )
        self.toolbar.modal_dialog.override_output_text = 'Please approve pairing on the device...'

    def tick(self, visible):
        # === logic tick ===============================================================
        while not self.zc_listener.devkit_events.empty():
            op, service_name = self.zc_listener.devkit_events.get()
            if op == 'add':
                devkit = Devkit(self.devkit_commands, self.settings, zc_listener=self.zc_listener, service_name=service_name)
                devkit.setup()
                self.devkits[devkit.name] = devkit
            elif op == 'update':
                # not doing anything or trying to run setup again
                # probably an IP change, which is already reflected in the zc_listener
                pass
            else:
                assert op == 'del'
                del self.devkits[service_name]

        online_kits = [k for k in self.devkits.values() if k.state == DevkitState.devkit_online]

        # Maintain selected devkit
        self.selected_devkit # Makes sure the selected devkit remains valid internally
        emit = None
        for kit in online_kits:
            # Trying to always maintain a kit selected
            if self._selected_devkit_name is None:
                self._selected_devkit_name = kit.name
                emit = kit
            # Restore the preferred kit if we see it
            if self._selected_devkit_name != kit.name and kit.name == self.preferred_devkit_name:
                self._selected_devkit_name = kit.name
                emit = kit
        if emit is not None:
            self.signal_selected_devkit.emit(kit=emit)

        if not visible:
            return

        # === draw =========================================================================
        if self.first_draw:
            try:
                devkit_client.locate_cygwin_tools()
            except Exception as e:
                failed_future = concurrent.futures.Future()
                failed_future.set_exception(e)
                self.toolbar.modal_dialog = ModalWait(
                    self.viewport,
                    self.toolbar,
                    'ERROR',
                    failed_future
                )
            self.first_draw = False

        with imgui_window(self.BUTTON_NAME, False, imgui.WINDOW_NO_COLLAPSE | imgui.WINDOW_NO_MOVE | imgui.WINDOW_NO_RESIZE) as (_, opened):

            imgui.text('Connect to Steam Deck by IP:')
            imgui.same_line()
            imgui.set_cursor_pos_x(30*CHARACTER_WIDTH)
            imgui.push_item_width(20*CHARACTER_WIDTH)
            changed, s = imgui.input_text('##add_by_ip', self.add_by_ip_text, 128)
            imgui.pop_item_width()
            if changed:
                self.add_by_ip_text = s
            imgui.same_line()
            imgui.text('Port:')
            imgui.same_line()
            imgui.push_item_width(6*CHARACTER_WIDTH)
            changed, p = imgui.input_text('##add_by_ip_port', self.add_by_ip_port, 6)
            imgui.pop_item_width()
            if changed:
                self.add_by_ip_port = p
            imgui.same_line()
            if imgui.button('Connect##byip'):
                if len(self.add_by_ip_text) > 0:
                    self.add_by_ip_text = s
                    if len(self.add_by_ip_port) > 0:
                        logger.info(f'Connecting to Deck by IP {self.add_by_ip_text} and port {self.add_by_ip_port}')
                    else:
                        self.add_by_ip_port = devkit_client.DEFAULT_DEVKIT_SERVICE_HTTP
                        logger.info(f'Connecting to Deck by IP {self.add_by_ip_text} and default port {devkit_client.DEFAULT_DEVKIT_SERVICE_HTTP}')
                    devkit = Devkit(self.devkit_commands, self.settings, address=self.add_by_ip_text, port=int(self.add_by_ip_port))
                    devkit.setup()
                    self.devkits[devkit.name] = devkit

            # list non registered devkits (discovered, registering, failed etc.)
            other_kits = [k for k in self.devkits.values() if k not in online_kits]
            if len(other_kits) > 0:
                imgui.text('Add a devkit:')
                buttons_index = 0
                for kit in other_kits:
                    imgui.text(kit.full_name)
                    imgui.same_line()
                    if kit.state == DevkitState.devkit_init:
                        imgui.text('Initializing...')
                        # give an opportunity to quickly delete IP kits during the slow init and retry
                        if kit.added_by_ip:
                            imgui.same_line()
                            if imgui.button(f'Forget IP kit##init_{buttons_index}'):
                                if kit.init_future is not None:
                                    # likely won't do anything since the executor thread is already running
                                    # no way to cancel the thread or the on_init_done callback
                                    # so that still finishes in the background but so far isn't causing problems
                                    kit.init_future.cancel()
                                kit.forget_added_by_ip()
                                del self.devkits[kit.name]
                    elif kit.state == DevkitState.devkit_registering:
                        imgui.text('Registering...')
                    elif kit.state == DevkitState.devkit_not_registered:
                        if imgui.button(f'Register##{buttons_index}'):
                            self.register_kit(kit)
                        limited_connectivity = kit.limited_connectivity
                        # we check for this first thing in _identify, shouldn't be possible to come here without it anymore
                        assert limited_connectivity is not None
                        if limited_connectivity:
                            if True:
                                running_sshd = True
                                if kit.http_connectivity:
                                    # only obtained if http connectivity was confirmed
                                    settings = kit.service_properties['settings']
                                    # assume all devices will either not report a sshd flag, or report a live/up to date one
                                    # also for historical reasons this flag reports as a string
                                    running_sshd = ( settings.get('sshd', '0') == '1' )
                                # a device that was never registered as a devkit will not have sshd running yet,
                                # in that case we do not say anything about limited connectivity to avoid confusion
                                if running_sshd:
                                    imgui.same_line()
                                    ssh_status = 'open' if kit.ssh_connectivity else 'closed'
                                    http_status = 'open' if kit.http_connectivity else 'closed'
                                    if not kit.http_connectivity:
                                        # sshd is running but we don't see the devkit service, could be that dev mode that turned back off
                                        # so make that our first message
                                        imgui.text(TOGGLE_DEV_MODE)
                                        # line up the port details warning below
                                        imgui.set_cursor_pos_x(50*CHARACTER_WIDTH)
                                    imgui.text(f'WARNING: The device is visible over mDNS, but some network ports are unreachable (22 {ssh_status}, {kit.http_port} {http_status}): cannot use this kit')
                    else:
                        assert kit.state == DevkitState.devkit_init_failed
                        imgui.text('Init failed')
                        imgui.same_line()
                        if imgui.button(f'Retry##{buttons_index}'):
                            kit.state = DevkitState.devkit_init
                            kit.setup()
                        if kit.added_by_ip:
                            imgui.same_line()
                            if imgui.button(f'Forget IP kit##failed_{buttons_index}'):
                                kit.forget_added_by_ip()
                                del self.devkits[kit.name]

                        limited_connectivity = kit.limited_connectivity
                        # the connectivity checks may not have completed
                        if kit.limited_connectivity is None:
                            imgui.same_line()
                            imgui.text(f'WARNING: connectivity checks did not complete - ssh: {kit.ssh_connectivity!r} http: {kit.http_connectivity!r}')
                        elif limited_connectivity:
                            if True:
                                imgui.same_line()
                                ssh_status = 'open' if kit.ssh_connectivity else 'closed'
                                http_status = 'open' if kit.http_connectivity else 'closed'
                                if kit.added_by_ip:
                                    if not kit.ssh_connectivity and not kit.http_connectivity:
                                        imgui.text(f'WARNING: device added by IP, did not respond.')
                                    else:
                                        if not kit.http_connectivity:
                                            imgui.text(TOGGLE_DEV_MODE)
                                            imgui.set_cursor_pos_x(50*CHARACTER_WIDTH)
                                        imgui.text(f'WARNING: device added by IP, some network ports are unreachable (22 {ssh_status}, {kit.http_port} {http_status}): cannot use this kit')
                                else:
                                    if not kit.http_connectivity:
                                        imgui.text(TOGGLE_DEV_MODE)
                                        imgui.set_cursor_pos_x(50*CHARACTER_WIDTH)
                                    imgui.text(f'WARNING: device discovered over mDNS, but some network ports are unreachable (22 {ssh_status}, {kit.http_port} {http_status}): cannot use this kit')
                    buttons_index += 1

            if len(online_kits) == 0 and len(other_kits) == 0:
                imgui.text('No devkit discovered on the network (mDNS).')
                imgui.text('Make sure the device is in developer mode (Settings -> System -> Enable Developer Mode).')
                imgui.text('You may need to add the device by IP.')
                imgui.separator()

            if len(online_kits) == 0:
                imgui.text('No registered devkits online! Add a devkit to start.')
            else:
                imgui.separator()
                imgui.text('Select target devkit:')
                counter = 0
                for kit in online_kits:
                    description = kit.full_name
                    os_label = 'FrameOS' if kit.is_deckard else 'SteamOS'
                    description += f' {os_label}: {kit.os_version}'
                    if not kit.user_password_is_set:
                        description += f' - user password is not set'

                    clicked, _ = imgui.checkbox(f'{description}##{kit.name}', kit.name == self._selected_devkit_name)
                    if clicked:
                        self._selected_devkit_name = kit.name
                        self.signal_selected_devkit.emit(kit=kit)
                        # Mark as the new preferred devkit
                        self.preferred_devkit_name = self._selected_devkit_name
                        self.settings['DevkitsWindow.preferred_devkit_name'] = self.preferred_devkit_name

                    if kit.added_by_ip:
                        imgui.same_line()
                        if imgui.button(f'Forget IP kit##online_{counter}'):
                            kit.forget_added_by_ip()
                            del self.devkits[kit.name]
                            # end the draw frame early in case we invalidated the active devkit
                            return
                    counter += 1

                active_buttons = [
                    RefreshStatus.BUTTON_NAME,
                    ListTitles.BUTTON_NAME,
                    ChangePassword.BUTTON_NAME,
                    RemoteShell.BUTTON_NAME,
                    RestartSession.BUTTON_NAME,
                    BrowseFiles.BUTTON_NAME,
                    CEFConsole.BUTTON_NAME,
                ]
                same_line = False
                for button_name in active_buttons:
                    if same_line:
                        imgui.same_line()
                    if imgui.button(button_name):
                        self.toolbar.signal_pressed.emit(name=button_name, selected_devkit=self.selected_devkit)
                    same_line = True
                if self.selected_devkit is None:
                    return
                steamos_status = self.selected_devkit.steamos_status
                if not ( isinstance(steamos_status, dict) and steamos_status ):
                    return
                # === gamescope / plasma session select ========================================
                ljust=24
                if False:
                    # does not work on Steam Frame, is a bit broken on Steam Deck atm.
                    # I don't think this is much useful, disabling for now, maybe just remove?
                    imgui.text(f'{"Set session":<{ljust}}:')
                    imgui.same_line()
                    imgui.push_item_width(25*CHARACTER_WIDTH)
                    combo_options = steamos_status['session_options'].copy()
                    session_status = steamos_status['session_status']
                    try:
                        session_status_index = steamos_status['session_options'].index(steamos_status['session_status'])
                    except Exception:
                        combo_options.append(session_status)
                        session_status_index = len(combo_options)-1
                    clicked, selected_out = imgui.combo(
                        '##Session',
                        session_status_index,
                        combo_options,
                    )
                    imgui.pop_item_width()
                    if clicked:
                        # apply immediately
                        if selected_out < len(steamos_status['session_options']):
                            apply_session = steamos_status['session_options'][selected_out]
                            logger.info(f'apply {apply_session}')
                            set_session_future = self.devkit_commands.set_session(
                                self.selected_devkit,
                                apply_session,
                                True # wait
                            )
                            self.toolbar.modal_dialog = ModalWait(
                                self.viewport,
                                self.toolbar,
                                f'Changing session on {self.selected_devkit.name!r}',
                                set_session_future,
                                exit_on_success=True,
                            )
                self.steam_client_draw(steamos_status, ljust)

                subtool_list = [
                    self.screenshot,
                    self.perf_overlay,
                    self.gpu_trace,
                    self.rgp_capture,
                    self.renderdoc_capture,
                    self.proton_logs,
                    self.controller_configs,
                    self.delete_title,
                ]
                # sub tools do their own drawing in the devkits window and have their own trigger buttons
                for subtool in subtool_list:
                    if self.selected_devkit.is_deckard and subtool == self.rgp_capture:
                        # not supported on Steam Frame
                        continue
                    subtool.devkits_window_draw(self.selected_devkit)

    def steam_client_draw(self, steamos_status, ljust):
        imgui.text(f'{"Steam client":<{ljust}}:')
        imgui.same_line()
        imgui.push_item_width(30*CHARACTER_WIDTH)
        imgui.text(steamos_status['steam_status_description'])
        imgui.pop_item_width()
        status_lookup = steamos_status.get('steam_status')
        if SteamStatus.from_string(status_lookup).value <= SteamStatus.ERROR.value:
            # Don't render arguments if there's a problem with the steam client
            return
        if self.selected_devkit.is_deckard:
            if self.steam_client_args is None:
                if 'steam_current_args' in steamos_status:
                    self.steam_client_args = ' '.join(steamos_status['steam_current_args'])
                else:
                    logger.warning('Current command line arguments for the Steam client not available, falling back to default arguments.')
                    self.steam_client_args = ' '.join(steamos_status['steam_default_args'])
            if self.frame_osclient_extra_args is None:
                self.frame_osclient_extra_args = steamos_status['frame_osclient_extra_args'] or ''
            imgui.text(f'{"Arguments":<{ljust}}:')
            imgui.same_line()
            # Check if extra args are at the end of client args
            # steam_client_args may carry the extra arguments at the end, strip if necessary
            committed_extra = steamos_status['frame_osclient_extra_args'] or ''
            assert isinstance(self.steam_client_args, str)
            if committed_extra and self.steam_client_args.endswith(committed_extra):
                base_args = self.steam_client_args[:-(len(committed_extra)+1)]
                imgui.text(base_args)
                imgui.same_line(spacing=0)
                imgui.push_style_color(imgui.COLOR_TEXT, 1.0, 1.0, 0.0)
                imgui.text(' ' + committed_extra)
                imgui.pop_style_color()
            else:
                imgui.text(self.steam_client_args)
            imgui.text(f'{"Extra arguments":<{ljust}}:')
            imgui.same_line()
            imgui.push_item_width(60*CHARACTER_WIDTH)
            changed, s = imgui.input_text('##ExtraArgs', self.frame_osclient_extra_args, 1000)
            imgui.pop_item_width()
            if changed:
                self.frame_osclient_extra_args = s
            imgui.same_line()
            if imgui.button('Apply'):
                self._set_steam_client('SteamStatus.OS', self.frame_osclient_extra_args)
        else:
            if self.steam_client_args is None:
                if 'steam_current_args' in steamos_status:
                    self.steam_client_args = ' '.join(steamos_status['steam_current_args'])
                else:
                    logger.warning('Current command line arguments for the Steam client not available, falling back to default arguments.')
                    self.steam_client_args = ' '.join(steamos_status['steam_default_args'])

            imgui.text(f'{"Arguments":<{ljust}}:')
            imgui.same_line()

            imgui.push_item_width(16*CHARACTER_WIDTH)
            status_lookup = steamos_status['steam_status']
            steam_args_mode = 0 if status_lookup == 'SteamStatus.OS' else 1
            changed, v = imgui.combo(
                '##CustomArgs',
                steam_args_mode,
                ['Default', 'Custom'],
                )
            if changed and v != steam_args_mode:
                # Switch between normal client and dev mode immediately
                if v == 0:
                    self._set_steam_client('SteamStatus.OS', '')
                else:
                    self._set_steam_client('SteamStatus.OS_DEV', self.steam_client_args)
                imgui.pop_item_width()
                return

            imgui.pop_item_width()

            if steam_args_mode == 1:
                imgui.same_line()
                if imgui.button('Reset'):
                    # Reset to the default arguments out of gamescope-session
                    self.steam_client_args = ' '.join(steamos_status['steam_default_args'])
                imgui.set_cursor_pos_x(ljust*CHARACTER_WIDTH)
                imgui.push_item_width(80*CHARACTER_WIDTH)
                changed, s = imgui.input_text('##CommandLine', self.steam_client_args, 1000)
                imgui.pop_item_width()
                if changed:
                    self.steam_client_args = s
                current_args = ' '.join(steamos_status['steam_current_args'])
                dirty = self.steam_client_args != current_args
                if dirty:
                    imgui.same_line()
                    if imgui.button('Apply'):
                        self._set_steam_client('SteamStatus.OS_DEV', self.steam_client_args)


class ConsoleHandler(logging.Handler):
    MAX_LINES = 500

    def __init__(self, logger, formatter, *args):
        super(ConsoleHandler, self).__init__()
        self.logger = logger
        self.formatter = formatter
        self.log_lines = collections.deque(maxlen=ConsoleHandler.MAX_LINES)
        self.dirty = True
        self._text = None
        self._text_len = None

    def setup(self):
        self.logger.addHandler(self)

    @property
    def text_and_len(self):
        if self.dirty:
            self._text = '\n'.join(self.log_lines) + '\n'
            self._text_len = len(self._text)
            self.dirty = False
        return (self._text, self._text_len)

    def emit(self, record):
        self.add_line(self.formatter.format(record))

    def add_line(self, line):
        self.log_lines.extend(line.split('\n'))
        self.dirty = True


class FileToConsoleHandlerAdapter:
    '''Adapt a file object API to push logging records to a ConsoleHandler'''

    def __init__(self, handler):
        self.handler = handler

    def write(self, buf):
        # Do we get partial line writes? Assuming no..
        for line in buf.splitlines(False):
            self.handler.add_line(line.rstrip('\n'))

    def flush(self):
        pass


class ConsoleWindow(ToolWindow):
    '''All purpose logging window.'''

    BUTTON_NAME = 'Status'
    SETTINGS_NAME = 'ConsoleWindow.autoscroll'

    def __init__(self, conf, handler, settings, *args):
        super(ConsoleWindow, self).__init__(self.BUTTON_NAME, *args)
        self.conf = conf
        self.handler = handler
        self.settings = settings
        # Draw even when no kit is active
        self.tick_without_devkit = True
        self.autoscroll = self.settings.get(ConsoleWindow.SETTINGS_NAME, True)

    def tick(self, visible):
        imgui.begin(self.BUTTON_NAME, False, imgui.WINDOW_NO_COLLAPSE | imgui.WINDOW_NO_MOVE | imgui.WINDOW_NO_RESIZE)
        clicked, v = imgui.checkbox('Auto-scroll on output', self.autoscroll)
        if clicked:
            self.autoscroll = v
            self.settings[ConsoleWindow.SETTINGS_NAME] = v
        imgui.begin_child('console')
        dirty = self.handler.dirty
        text, text_len = self.handler.text_and_len
        line_count = text.count('\n') + 1
        line_height = imgui.get_text_line_height()
        content_height = (line_count + 1) * line_height + imgui.get_style().frame_padding.y * 2
        widget_height = max(content_height, imgui.get_window_height())
        imgui.input_text_multiline('', text, -1, imgui.get_window_width(), widget_height, imgui.INPUT_TEXT_READ_ONLY)
        if self.autoscroll and dirty:
            imgui.set_scroll_y(imgui.get_scroll_max_y())
        imgui.end_child()
        imgui.end()


class SubTool:
    def __init__(self, devkit_commands, viewport, toolbar, settings):
        self.devkit_commands = devkit_commands
        self.viewport = viewport
        self.toolbar = toolbar
        self.settings = settings

    def setup(self):
        self.viewport.signal_draw.connect(self.on_draw)
        self.toolbar.signal_pressed.connect(self.on_pressed)

    def on_draw(self, **kwargs):
        pass

    def on_pressed(self, **kwargs):
        pass


class ListTitles(SubTool):
    BUTTON_NAME = 'List Devkit Titles'

    def on_pressed(self, name, selected_devkit, **kwargs):
        if name != self.BUTTON_NAME:
            return
        self.list_games_future = self.devkit_commands.list_games(selected_devkit)
        self.modal_wait = ModalWait(
            self.viewport,
            self.toolbar,
            'Titles deployed on {!r}:'.format(selected_devkit.name),
            self.list_games_future
            )
        self.toolbar.modal_dialog = self.modal_wait
        self.modal_wait.signal_task_done.connect(self.on_list_done)

    def on_list_done(self, **kwargs):
        if self.modal_wait.result is None:
            # failed, let the exception be displayed using ModalWait's defaults
            return
        # parse the json response for presentation
        output = '\n'.join(game['gameid'] for game in self.modal_wait.result)
        self.modal_wait.override_output_text = output


class UpdateTitle(ToolWindow):
    BUTTON_NAME = 'Title Upload'
    SELECTED_CONFIG_LIST = 'UpdateTitleConfigs'
    _SELECTED_CONFIG_KEY = 'UpdateTitleSelectedConfig'

    POSSIBLE_DEPS = [{"name":"DirectX", "items": [{"id": "directx", "name": "June 2010"}]},
                     {"name": "Visual C++ Redist", "items": [{"id": "vs2019", "name": "2019 (also includes 2017 & 2015)"},
                                                             {"id": "vs2017", "name": "2017 (deprecated)"},
                                                             {"id": "vs2015", "name": "2015 (deprecated)"},
                                                             {"id": "vs2013", "name": "2013"},
                                                             {"id": "vs2012", "name": "2012"},
                                                             {"id": "vs2010", "name": "2010"},
                                                             {"id": "vs2008", "name": "2008"},
                                                             {"id": "vs2004", "name": "2005"}]},
                     {"name": "OpenAL", "items": [{"id": "openal", "name": "2.0.7.0"}]},
                     {"name": ".NET", "items": [{"id": "dotnet48", "name": "4.8"},
                                                {"id": "dotnet47", "name": "4.7.2"},
                                                {"id": "dotnet46", "name": "4.6.2"},
                                                {"id": "dotnet45", "name": "4.5.2"},
                                                {"id": "dotnet40client", "name": "4.0 Client Profile"},
                                                {"id": "dotnet40", "name": "4.0"},
                                                {"id": "dotnet35client", "name": "3.5 Client Profile"},
                                                {"id": "dotnet35", "name": "3.5"}]},
                     {"name": "XNA", "items": [{"id": "xna40", "name": "4.0"},
                                               {"id": "xna31", "name": "3.1"},
                                               {"id": "xna30", "name": "3.0"}]},
                     {"name": "PhysX", "items": [{"id": "physx8", "name": "8.09.04"},
                                                 {"id": "physx912", "name": "9.12.1031"},
                                                 {"id": "physx913", "name": "9.13.1220"},
                                                 {"id": "physx914", "name": "9.14.0702"}]}]

    @property
    def selected_config_key(self):
        if self.is_sideload:
            return f'ValveSideLoad.{self._SELECTED_CONFIG_KEY}'
        return self._SELECTED_CONFIG_KEY

    @property
    def is_deckard(self):
        return self.devkits_window.selected_devkit.is_deckard if self.devkits_window and self.devkits_window.selected_devkit else False

    def __init__(self, devkit_commands, devkits_window, settings, is_sideload, client_api, *args):
        super(UpdateTitle, self).__init__(self.BUTTON_NAME, *args)
        self.devkit_commands = devkit_commands
        self.devkits_window = devkits_window
        self.settings = settings
        self.is_sideload = is_sideload
        self.is_steamvr_config = False
        self.client_api = client_api
        self.client_api.signal_title_settings.connect(self.on_title_settings)
        self.client_api.signal_build_success.connect(self.on_build_success)
        self.apply_default_settings()
        self.available_configs = self.settings.get(UpdateTitle.SELECTED_CONFIG_LIST, [])
        # do not set directly outside of init, use _select_title
        self.selected_config = self.settings.get(self.selected_config_key, '')
        self.restore_settings(self.selected_config)
        self.update_future = None
        self.modal_wait = None
        self.pending_upload_names = set()
        self.deps = {}
        # cancel signal emitted to the low level execution if we want to cancel the rsync transfer
        self.cancel_signal = signalslot.Signal()

    def save_settings(self, gameid, dict):
        if len(gameid) > 0:
            if self.is_sideload:
                prefix = f'ValveSideLoad.{gameid}.'
            else:
                prefix = f'UpdateTitle.{gameid}.'
        else:
            # return the current settings with no decorations (APIHandler)
            prefix = ''
        dict[f'{prefix}title_name'] = self.title_name
        dict[f'{prefix}local_folder'] = self.local_folder
        dict[f'{prefix}filter_mode'] = self.filter_mode
        dict[f'{prefix}filter_patterns'] = self.filter_patterns
        dict[f'{prefix}delete_remote_files'] = self.delete_remote_files
        dict[f'{prefix}skip_newer_files'] = self.skip_newer_files
        dict[f'{prefix}verify_checksums'] = self.verify_checksums
        # devkit titles only
        dict[f'{prefix}start_command'] = self.start_command
        dict[f'{prefix}force_appid'] = self.force_appid
        # valve sideload
        dict[f'{prefix}cmdline_args'] = self.cmdline_args
        dict[f'{prefix}prevent_auto_repair'] = self.prevent_auto_repair
        dict[f'{prefix}restart_steam'] = self.restart_steam
        dict[f'{prefix}use_mask_unmask'] = self.use_mask_unmask
        dict[f'{prefix}steam_play_debug'] = self.steam_play_debug
        dict[f'{prefix}steam_play_debug_wait'] = self.steam_play_debug_wait
        dict[f'{prefix}steam_play_debug_version'] = self.steam_play_debug_version
        dict[f'{prefix}auto_upload'] = self.auto_upload
        dict[f'{prefix}auto_start'] = self.auto_start
        dict[f'{prefix}gdbserver'] = self.gdbserver
        dict[f'{prefix}dependencies'] = self.deps
        dict[f'{prefix}sideload_cmdline_args_mode'] = self.sideload_cmdline_args_mode
        dict[f'{prefix}sideload_filter_mode'] = self.sideload_filter_mode
        dict[f'{prefix}selected_runtime'] = self.selected_runtime

    def restore_settings(self, gameid):
        if gameid is None or len(gameid) == 0:
            return
        if self.is_sideload:
            prefix = f'ValveSideLoad.{gameid}.'
        else:
            prefix = f'UpdateTitle.{gameid}.'
        try:
            # make the defaults match apply_default_settings
            self.title_name = self.settings.get(f'{prefix}title_name', '')
            self.local_folder = self.settings.get(f'{prefix}local_folder', '')
            self.filter_mode = self.settings.get(f'{prefix}filter_mode', 0)
            # this is a bit nasty, we have to copy the list when retrieving from the Settings object, otherwise it's the same pattern for all title configurations
            self.filter_patterns = self.settings.get(f'{prefix}filter_patterns', ['', '', '']).copy()
            self.delete_remote_files = self.settings.get(f'{prefix}delete_remote_files', False)
            self.skip_newer_files = self.settings.get(f'{prefix}skip_newer_files', False)
            self.verify_checksums = self.settings.get(f'{prefix}verify_checksums', False)
            self.start_command = self.settings.get(f'{prefix}start_command', '')
            self.force_appid = self.settings.get(f'{prefix}force_appid', '')
            self.cmdline_args = self.settings.get(f'{prefix}cmdline_args', '')
            self.prevent_auto_repair = self.settings.get(f'{prefix}prevent_auto_repair', False)
            self.sideload_cmdline_args_mode = self.settings.get(f'{prefix}sideload_cmdline_args_mode', 0)
            self.sideload_filter_mode = self.settings.get(f'{prefix}sideload_filter_mode', 0)
            # Shall only be True for sideload instances of UpdateTitle
            self.restart_steam = self.settings.get(f'{prefix}restart_steam', True) if self.is_sideload else False
            self.use_mask_unmask = self.settings.get(f'{prefix}use_mask_unmask', False)
            self.steam_play_debug = self.settings.get(f'{prefix}steam_play_debug', False)
            self.steam_play_debug_wait = self.settings.get(f'{prefix}steam_play_debug_wait', False)
            self.steam_play_debug_version = self.settings.get(f'{prefix}steam_play_debug_version', '2019')
            self.auto_upload = self.settings.get(f'{prefix}auto_upload', False)
            self.auto_start = self.settings.get(f'{prefix}auto_start', False)
            self.gdbserver = self.settings.get(f'{prefix}gdbserver', False)
            self.deps = self.settings.get(f'{prefix}dependencies', {})
            self.selected_runtime = self.settings.get(f'{prefix}selected_runtime', int(devkit_client.RuntimeOptions.Unspecified))
        except Exception as e:
            # used to be a sort of valid code path, shouldn't happen anymore
            devkit_client.log_exception(e)

    def apply_default_settings(self):
        self.title_name = ''
        self.local_folder = ''
        # If true, filter with an exclude pattern (default). Otherwise use an include pattern.
        self.filter_mode = 0
        # track the patterns for all three filter modes, only one applies at upload time though
        self.filter_patterns = ['', '', '']
        self.delete_remote_files = False
        self.skip_newer_files = False
        self.verify_checksums = False
        self.start_command = ''
        self.force_appid = ''
        self.cmdline_args = ''
        self.prevent_auto_repair = False
        # This option only affects Steam sideloaded client uploads, which is a Valve only feature
        self.sideload_cmdline_args_mode = 0
        self.sideload_filter_mode = 0
        # Shall only be True for sideload instances of UpdateTitle
        self.restart_steam = self.is_sideload
        self.use_mask_unmask = False
        self.steam_play_debug = False
        self.steam_play_debug_wait = False
        self.steam_play_debug_version = '2019'
        self.auto_upload = False
        self.auto_start = False
        self.gdbserver = False
        self.deps = {}
        self.selected_runtime = int(devkit_client.RuntimeOptions.Unspecified)


    def _select_title(self, gameid):
        if gameid is None:
            self.apply_default_settings()
            self.selected_config = ''
            return True
        if self.selected_config == gameid:
            # no change, not restoring settings
            return False
        self.selected_config = gameid
        self.settings[self.selected_config_key] = gameid
        self.restore_settings(gameid)
        return True

    def draw_title_select(self):
        assert not self.is_sideload
        imgui.text('Load config:')
        imgui.next_column()
        selected_index = 0
        if self.selected_config in self.available_configs:
            selected_index = self.available_configs.index(self.selected_config) + 1
        clicked, selected_out = imgui.combo(
            "##Restore", selected_index, ['default'] + self.available_configs
        )
        if clicked:
            if selected_out == 0:
                self._select_title(None)
            else:
                self._select_title(self.available_configs[selected_out-1])
        imgui.next_column()
        imgui.next_column()
        save_config = imgui.button('Save config')
        imgui.same_line()
        if imgui.button('Delete config'):
            if self.selected_config in self.available_configs:
                logger.info(f'Delete config {self.selected_config!r}')
                self.available_configs.remove(self.selected_config)
            else:
                logger.warning(f'Cannot delete config {self.selected_config!r}: not found')
        imgui.next_column()
        imgui.separator()

        imgui.text('Name:')
        imgui.next_column()
        imgui.push_item_width(-1)
        changed, s = imgui.input_text('##Name', self.title_name, 1000)
        imgui.pop_item_width()
        if changed:
            self.title_name = s
        imgui.next_column()
        return save_config

    def draw_title_filtering(self):
        imgui.text('Upload filtering:')
        imgui.next_column()

        imgui.push_item_width(16*CHARACTER_WIDTH)
        changed, v = imgui.combo(
            '##FilterPatternSelect',
            self.filter_mode,
            ['Exclude only', 'Include only', 'Rsync args'],
            )
        if changed:
            self.filter_mode = v
        imgui.pop_item_width()
        imgui.same_line()
        imgui.push_item_width(-1)
        changed, s = imgui.input_text('##FilterPattern', self.filter_patterns[self.filter_mode], 1000)
        imgui.pop_item_width()
        if changed:
            self.filter_patterns[self.filter_mode] = s
        imgui.next_column()

    def draw_title_runtime(self):
        imgui.text('Runtime:')
        imgui.next_column()

        if not self.is_deckard:
            runtime_options = [v for (k,v) in devkit_client.RUNTIME_DESCRIPTIONS.items() if k not in (devkit_client.RuntimeOptions.Android, devkit_client.RuntimeOptions.SLR4_arm64)]
        else:
            runtime_options = list(devkit_client.RUNTIME_DESCRIPTIONS.values())

        try:
            runtime_index = runtime_options.index(devkit_client.RUNTIME_DESCRIPTIONS[self.selected_runtime])
        except Exception:
            # observed happening when selected_devkit changes from under the user's feet
            runtime_index = 0
        clicked, selected_index = imgui.combo(
            '##Runtime',
            runtime_index,
            runtime_options
        )
        imgui.next_column()
        if clicked:
            self.selected_runtime = None
            for (k,v) in devkit_client.RUNTIME_DESCRIPTIONS.items():
                if v == runtime_options[selected_index]:
                    self.selected_runtime = k
                    break
            assert self.selected_runtime is not None

        if self.selected_runtime in (devkit_client.RuntimeOptions.SteamPlay, devkit_client.RuntimeOptions.Proton_Experimental) and not self.is_deckard:
            imgui.next_column()

# runtime dependencies for the title: off until the Steam side is ready for support
#            if imgui.button('Set dependencies'):
#                imgui.open_popup('Set dependencies')
#
#            if imgui.begin_popup_modal('Set dependencies')[0]:
#                imgui.columns(2)
#                imgui.set_column_width(0,170)
#                imgui.text('Common redistributables')
#                imgui.next_column()
#                for dep in UpdateTitle.POSSIBLE_DEPS:
#                    imgui.next_column()
#                    imgui.text(dep["name"])
#                    for depitem in dep["items"]:
#                        depclicked, depchecked = imgui.checkbox(depitem["name"], depitem["id"] in self.deps)
#
#                        if depclicked:
#                            if depchecked:
#                                self.deps[depitem["id"]] = True
#                            else:
#                                del self.deps[depitem["id"]]
#
#                dismiss = imgui.button('OK')
#
#                # Press OK button, or hit escape/enter to dismiss once the task is complete
#                keyboard_state = sdl2.SDL_GetKeyboardState(None)
#                dismiss |= keyboard_state[sdl2.SDL_SCANCODE_ESCAPE] or keyboard_state[sdl2.SDL_SCANCODE_RETURN] or keyboard_state[sdl2.SDL_SCANCODE_KP_ENTER]
#                if dismiss:
#                    imgui.close_current_popup()
#                imgui.end_popup()

            imgui.next_column()
            imgui.text('Steam Play debug:')
            imgui.next_column()

            if platform.system() != 'Windows':
                imgui.text('Remote debugging is supported on Windows systems only.')
                imgui.next_column()
            else:
                clicked, v = imgui.checkbox('Start Visual Studio C++ debugger service on launch', self.steam_play_debug != SteamPlayDebug.Disabled)
                imgui.next_column()
                if clicked:
                    self.steam_play_debug = v
                if self.steam_play_debug:
                    remote_debuggers = devkit_client.get_remote_debuggers()
                    if len(remote_debuggers) == 0:
                        imgui.next_column()
                        imgui.text('ERROR: Please install the Visual Studio Remote Tools on your Windows system first.')
                        imgui.same_line()
                        if imgui.button('Help'):
                            webbrowser.open('https://partner.steamgames.com/doc/steamdeck/devkits/debugging')
                        imgui.next_column()
                    else:
                        imgui.text('Wait for attach:')
                        imgui.next_column()
                        clicked, v = imgui.checkbox('Wait for a debug client to attach', self.steam_play_debug_wait)
                        imgui.next_column()
                        if clicked:
                            self.steam_play_debug_wait = v
                        imgui.text('Remote debugger:')
                        imgui.next_column()
                        version_options = [ str(dbg.year) for dbg in remote_debuggers ]
                        try:
                            version_index = version_options.index(self.steam_play_debug_version)
                        except Exception:
                            logger.warning(f'Invalid remote debug tool version {self.steam_play_debug_version}, resetting')
                            version_index = 0
                            self.steam_play_debug_version = version_options[0]
                        imgui.push_item_width(8*CHARACTER_WIDTH)
                        clicked, selected_index = imgui.combo(
                            '##MSVSMonVersion', version_index, version_options
                        )
                        imgui.pop_item_width()
                        if clicked:
                            self.steam_play_debug_version = version_options[selected_index]
                        imgui.next_column()

    def draw_title_start_command(self):
        assert not self.is_sideload
        if self.selected_runtime == devkit_client.RuntimeOptions.Android:
            imgui.text('APK:')
        else:
            imgui.text('Start Command:')
        imgui.next_column()
        if imgui.button('...##BrowseStartCommand'):
            if not self.local_folder:
                self.show_error_modal('Set the local folder first')
            else:
                # Construct a file path within local_folder to make browse_file open in that directory
                # browse_file treats current_path as a file and opens in its parent, so we need to pass a file path
                if self.start_command:
                    browse_path = os.path.join(self.local_folder, self.start_command)
                else:
                    # Pass a dummy file path within local_folder so browse_file opens in local_folder
                    browse_path = os.path.join(self.local_folder, 'dummy')
                result = browse_file('Select Startup Command', browse_path, [('All files', '*')])
                if result:
                    abs_result = os.path.abspath(result)
                    abs_local_folder = os.path.abspath(self.local_folder)
                    
                    try:
                        rel_path = os.path.relpath(abs_result, abs_local_folder)
                        if rel_path.startswith('..'):
                            self.show_error_modal('Selected file must be within the local folder')
                        else:
                            self.start_command = rel_path
                    except ValueError as e:
                        self.show_error_modal(f'Selected file must be within the local folder: {e}')
        imgui.same_line()
        imgui.push_item_width(-1)
        changed, s = imgui.input_text('##StartCommand', self.start_command, 1000)
        imgui.next_column()
        imgui.pop_item_width()
        if changed:
            self.start_command = s

    def draw_title_force_appid(self):
        assert not self.is_sideload
        imgui.text('Force AppID:')
        imgui.next_column()
        imgui.push_item_width(-1)
        changed, s = imgui.input_text('##ForceAppID', self.force_appid, 100)
        imgui.next_column()
        imgui.pop_item_width()
        if changed:
            self.force_appid = s.strip()

    def draw_title_cmdline_args(self):
        assert not self.is_sideload
        imgui.text('Lepton UE arguments:')
        imgui.next_column()
        imgui.push_item_width(-1)
        changed, s = imgui.input_text('##TitleCmdlineArgs', self.cmdline_args, 1000)
        imgui.next_column()
        imgui.pop_item_width()
        if changed:
            self.cmdline_args = s

    def tick(self, visible):
        imgui.begin(self.BUTTON_NAME, False, imgui.WINDOW_NO_COLLAPSE | imgui.WINDOW_NO_MOVE | imgui.WINDOW_NO_RESIZE)

        imgui.columns(2)
        imgui.set_column_width(0, 170)

        if self.is_sideload:
            save_config = self.draw_sideload_select()
        else:
            save_config = self.draw_title_select()

        imgui.text('Local Folder:')
        imgui.next_column()
        if imgui.button('...##BrowseLocalFolder'):
            result = browse_directory('Select Local Folder', self.local_folder)
            if result:
                self.local_folder = result
        imgui.same_line()
        imgui.push_item_width(-1)
        changed, s = imgui.input_text('##LocalFolder', self.local_folder, 1000)
        imgui.pop_item_width()
        if changed:
            self.local_folder = s
        imgui.next_column()


        if self.is_sideload:
            if self.is_steamvr_config:
                self.draw_steamvr_settings()
            else:
                self.draw_steam_settings()
        else:
            self.draw_title_filtering()

        imgui.text('Clean upload:')
        imgui.next_column()
        clicked, v = imgui.checkbox('Delete extraneous remote files', self.delete_remote_files)
        if clicked:
            self.delete_remote_files = v
        imgui.same_line()
        clicked, v = imgui.checkbox('Allow newer remote files', self.skip_newer_files)
        if clicked:
            self.skip_newer_files = v
            if self.verify_checksums:
                self.verify_checksums = False
        imgui.same_line()
        clicked, v = imgui.checkbox('Verify checksums', self.verify_checksums)
        if clicked:
            self.verify_checksums = v
        if self.verify_checksums and self.skip_newer_files:
            # do not allow both options at the same time, it would still skip newer files and that's confusing
            self.skip_newer_files = False
        imgui.next_column()
        if self.is_sideload:
            if not self.is_steamvr_config:
                self.draw_sideload_cmdline_args()
        else:
            self.draw_title_start_command()
            if self.selected_runtime == devkit_client.RuntimeOptions.Android:
                self.draw_title_cmdline_args()
            self.draw_title_force_appid()
            self.draw_title_runtime()
        if self.is_sideload and not self.is_steamvr_config:
            self.draw_sideload_gdb_settings()
        imgui.text('Auto upload:')
        imgui.next_column()
        clicked, v = imgui.checkbox('Auto upload upon build success notification', self.auto_upload)
        imgui.next_column()
        if clicked:
            self.auto_upload = v
            save_config = True
        if self.is_sideload:
            if self.is_steamvr_config:
                self.draw_steamvr_upload_settings()
            else:
                self.draw_sideload_settings()
        else:
            imgui.text('Auto start:')
            imgui.next_column()
            clicked, v = imgui.checkbox('Auto start upon successful upload', self.auto_start)
            imgui.next_column()
            if clicked:
                self.auto_start = v
                save_config = True

        imgui.columns(1)

        do_upload = imgui.button('Upload')
        do_start = False
        if not self.is_sideload:
            imgui.same_line()
            do_start = imgui.button('Start')

        if save_config or do_upload:
            if re.fullmatch(GAMEID_ALLOWED_PATTERN, self.title_name) is None:
                failed_future = concurrent.futures.Future()
                failed_future.set_exception(Exception(f'Title name {self.title_name!r} must match pattern {GAMEID_ALLOWED_PATTERN}'))
                self.toolbar.modal_dialog = ModalWait(
                    self.viewport,
                    self.toolbar,
                    'ERROR',
                    failed_future
                )
                save_config = False
                do_upload = False
            else:
                logger.info(f'Saving config for {self.title_name!r}')
                self.save_settings(self.title_name, self.settings)
                skip = False
                if not self.is_sideload:
                    if self.title_name.lower() in ValveSideLoad.SIDELOAD_GAMEIDS:
                        # Reproduction and fix for this has been elusive but I run into it on the regular
                        # Write a late-catch fix attempt for now
                        logger.error(f'Unexpected: non sideload UpdateTitle trying to save a config for {self.title_name}')
                        skip = True
                if not skip and self.title_name not in self.available_configs:
                    self.available_configs.append(self.title_name)
                    self.available_configs = sorted(self.available_configs)
                    self.settings[UpdateTitle.SELECTED_CONFIG_LIST] = self.available_configs
                    self.settings[self.selected_config_key] = self.title_name
                # This is an important enough operation, force a flush to disk
                self.settings.save_settings()

        imgui.end()

        if do_upload:
            self.do_upload()

        if do_start:
            self.do_start()

    def on_ui_cancel_upload(self, **kwargs):
        # signal emitted by the UI to request transfer cancel, emit back to the low level
        logger.info('Received upload cancel request')
        self.cancel_signal.emit()
        if self.pending_upload_names:
            logger.info(f'Clearing pending upload queue: {self.pending_upload_names}')
            self.pending_upload_names.clear()
        if self.auto_upload:
            logger.info('Disabling auto upload due to user cancel')
            self.auto_upload = False
            self.save_settings(self.title_name, self.settings)
            self.settings.save_settings()

    def on_upload_done(self, **kwargs):
        devkit = self.devkits_window.selected_devkit
        if devkit and devkit.client_is_masked:
            logger.warning(f'The Steam client may have been left masked and disabled on {devkit.name}. Forcing a session reload.')
            self.devkit_commands.restart_session(devkit)

        e = self.modal_wait.error
        if e is not None and str(e).find('Please install app id 480') >= 0:
            # user is trying to deploy the Steamworks SDK sample app,
            # that requires having 480 installed to the account which isn't super obvious to do
            # as it does not show in the store
            logger.info('AppID 480 is needed, installing')
            install_480_future = self.devkit_commands.simple_command(
                self.devkits_window.selected_devkit,
                ['steam', 'steam://install/480']
            )
            self.modal_wait = ModalWait(
                self.viewport,
                self.toolbar,
                'Installing Steamworks SDK example AppID 480 (Spacewars)',
                install_480_future,
            )
            self.toolbar.modal_dialog = self.modal_wait
            def set_480_message(**kwargs):
                self.modal_wait.override_output_text = 'Please follow instructions on your device to install the test app and try again.'
            set_480_message()
            self.modal_wait.signal_task_done.connect(set_480_message)

        # if there is no error, proceed to auto start, which will spawn a new modal wait (that one auto-closes)
        if self.auto_start and self.modal_wait.error is None:
            self.do_start()
            return

        # process any pending build success notifications before closing the modal
        if self.pending_upload_names:
            if self.modal_wait.error is not None:
                logger.info(f'Upload failed, clearing pending upload queue: {self.pending_upload_names}')
                self.pending_upload_names.clear()
            else:
                pending_name = self.pending_upload_names.pop()
                logger.info(f'Processing pending build success notification for {pending_name!r}')
                try:
                    self.on_build_success(pending_name)
                except Exception as e:
                    logger.error(f'Failed to process pending build success for {pending_name!r}: {e!r}')
                    self.pending_upload_names.clear()
                return

        # setting this late triggers the modal to close still
        self.modal_wait.exit_on_success = True

    def do_upload(self):
        if not os.path.isdir(self.local_folder):
            failed_future = concurrent.futures.Future()
            failed_future.set_exception(Exception(f'"{self.local_folder}" is not a valid folder!\n\nMake sure "Local Folder" is set in the "Title Upload" tab.'))
            self.toolbar.modal_dialog = ModalWait(
                self.viewport,
                self.toolbar,
                'Local folder for upload is misconfigured',
                failed_future,
            )
            return
        # build the rsync command line args for filtering upload content
        filter_args = []
        filter_tokens = '' # silence lexer
        if not self.is_sideload or self.sideload_filter_mode != 0:
            # title upload, or sideload with custom filter
            filter_tokens = shlex.split(self.filter_patterns[self.filter_mode])
        else:
            # sideload with default filter
            assert self.filter_mode == 0
            if self.selected_config == ValveSideLoad.SIDELOAD_GAMEIDS[0]:
                filter_tokens = shlex.split(ValveSideLoad.STEAM_DEFAULT_EXCLUDE_PATTERNS)
            elif self.selected_config == ValveSideLoad.SIDELOAD_GAMEIDS[1]:
                filter_tokens = shlex.split(ValveSideLoad.STEAMDECKARD_DEFAULT_EXCLUDE_PATTERNS)
        if self.filter_mode == 0:
            # a set of exclude patterns, this was the only implementation originally
            for token in filter_tokens:
                if token.startswith('+_'):
                    # this was a legacy hack, we keep it in
                    filter_args.append(f'--include={token[2:]}')
                else:
                    filter_args.append(f'--exclude={token}')
        elif self.filter_mode == 1:
            filter_args += [ f'--include={token}' for token in filter_tokens ]
            # visit all directories, skip all files
            # see https://unix.stackexchange.com/questions/2161/rsync-filter-copying-one-pattern-only
            filter_args += ['--include=*/', '--exclude=*', '--prune-empty-dirs']
        else:
            # just take the tokens directly as rsync args
            # this allows for more custom options, such as --copy-links etc.
            filter_args += filter_tokens
        steam_play_debug_enum = SteamPlayDebug.Disabled
        if self.selected_runtime in (devkit_client.RuntimeOptions.SteamPlay, devkit_client.RuntimeOptions.Proton_Experimental) and self.steam_play_debug:
            steam_play_debug_enum = SteamPlayDebug.Wait if self.steam_play_debug_wait else SteamPlayDebug.Start
        args_or_cmdline = None
        env_vars = {}
        lepton_args = ''
        if self.is_sideload:
            # sideload uses cmdline_args
            if self.sideload_cmdline_args_mode == 0:
                # sideload with default arguments
                if self.selected_config == ValveSideLoad.SIDELOAD_GAMEIDS[0]:
                    args_or_cmdline = [ValveSideLoad.STEAM_DEFAULT_CMDLINE_ARGS]
                elif self.selected_config == ValveSideLoad.SIDELOAD_GAMEIDS[1]:
                    args_or_cmdline = [ValveSideLoad.STEAMDECKARD_DEFAULT_CMDLINE_ARGS]
            else:
                args_or_cmdline = [self.cmdline_args]
        elif self.selected_runtime == devkit_client.RuntimeOptions.Android:
            # anything after the APK path may be passed to the lepton compat tool launch command,
            # but at this time it is completely ignored (Frajo, 8/5/26)
            args_or_cmdline = [self.start_command]
            # grab environment settings and command line arguments from a separate line in the UI
            # we also write those to UECommandLine.txt to facilitate passing command line arguments to UE APKs
            # and we support the Steam client's %command% placeholder (we just skip it)
            env_vars, lepton_args = devkit_client.parse_env_from_command(self.cmdline_args)
            if env_vars:
                logger.info(f'Parsed environment variables from cmdline arguments: {env_vars}')
            lepton_args = ' '.join(lepton_args.replace('%command%', '').split())
        else:
            # devkit title uploads use start_command
            # parse leading KEY=VALUE environment variable assignments out of the command string
            env_vars, true_command = devkit_client.parse_env_from_command(self.start_command)
            if env_vars:
                logger.info(f'Parsed environment variables from start command: {env_vars}')
            args_or_cmdline = [true_command]
        self.update_future = self.devkit_commands.update_game(
            self.devkits_window.selected_devkit,
            self.restart_steam,
            self.use_mask_unmask,
            self.prevent_auto_repair,
            self.gdbserver,
            self.selected_runtime,
            steam_play_debug_enum,
            self.steam_play_debug_version,
            self.title_name,
            self.local_folder,
            self.delete_remote_files,
            self.skip_newer_files,
            self.verify_checksums,
            args_or_cmdline,
            filter_args,
            self.deps,
            self.cancel_signal,
            self.force_appid,
            env_vars,
            lepton_args
            )
        self.result_message = None
        self.modal_wait = ModalWait(
            self.viewport,
            self.toolbar,
            'Updating {!r} on {!r}'.format(
                self.title_name,
                self.devkits_window.selected_devkit.name
            ),
            self.update_future,
            # we want on_upload_done to run, even for success!
            exit_on_success=False,
            cancel_signal=True,
            )
        self.modal_wait.cancel_signal.connect(self.on_ui_cancel_upload)
        self.modal_wait.signal_task_done.connect(self.on_upload_done)
        def on_upload_dismiss(**kwargs):
            if self.modal_wait is not None and self.modal_wait.error is None:
                self.toolbar.signal_pressed.emit(name=self.name, selected_devkit=self.toolbar.selected_devkit)
        self.modal_wait.signal_task_dismiss.connect(on_upload_dismiss)
        self.toolbar.focus_console()
        self.toolbar.modal_dialog = self.modal_wait

    def do_start(self):
        selected_devkit = self.devkits_window.selected_devkit
        task_future = self.devkit_commands.run_game(
            selected_devkit,
            self.title_name,
        )
        self.toolbar.modal_dialog = ModalWait(
            self.viewport,
            self.toolbar,
            f'Starting {self.title_name} on {selected_devkit.name}',
            task_future,
            exit_on_success=True,
        )

    def on_title_settings(self, **kwargs):
        d = {}
        self.save_settings('', d)
        return d

    def on_build_success(self, name, **kwargs):
        settings_prefix = 'UpdateTitle'
        if self.update_future is not None and not self.update_future.done():
            logger.info(f'Received a build success notification for {name!r}, queuing for upload after current transfer completes.')
            self.pending_upload_names.add(name)
            return
        auto_upload_pref = f'{settings_prefix}.{name}.auto_upload'
        if auto_upload_pref not in self.settings:
            # Exception message is a little misleading, could just be we have no saved setting
            raise Exception(f'No such title: {name}')
        if self.devkits_window.selected_devkit is None:
            raise Exception('No devkit selected')
        if not self.settings.get(f'{settings_prefix}.{name}.auto_upload', False):
            # title is not configured to do uploads
            logger.info(f'Received a build success notification for {name!r}, but auto upload is not enabled, stopping.')
            return # signal handled, but no upload
        # bring to the foreground if needed, in case some other title was selected
        self._select_title(name)
        # we save title settings before doing a normal manual upload, follow the same pattern here
        self.save_settings(self.title_name, self.settings)
        self.do_upload()
        return True # signal handled, upload done

# stub - not supported in this version, but we want a SIDELOAD_GAMEIDS to keep the patching out simple
class ValveSideLoad:
    SIDELOAD_GAMEIDS = devkit_client.SIDELOAD_GAMEIDS

class RefreshStatus:
    BUTTON_NAME = 'Refresh Status'

    def __init__(self, devkit_commands, devkits_window, viewport, toolbar):
        self.devkit_commands = devkit_commands
        self.devkits_window = devkits_window
        self.viewport = viewport
        self.toolbar = toolbar

    def setup(self):
        self.toolbar.signal_pressed.connect(self.on_pressed)

    def on_pressed(self, name , **kwargs):
        if name != self.BUTTON_NAME:
            return
        # Refresh a devkit passed in the signal, or the default selected
        kwargs.get('selected_devkit', self.devkits_window.selected_devkit)
        devkit = self.devkits_window.selected_devkit
        status_future = self.devkit_commands.steamos_get_status(devkit)
        self.toolbar.modal_dialog = ModalWait(
            self.viewport,
            self.toolbar,
            f'Refresh SteamOS status on {devkit.name!r}',
            status_future,
            exit_on_success=True
        )

class DeviceLogs(ToolWindow):
    BUTTON_NAME = 'Device Logs'
    LOGS_FOLDER_KEY = 'DeviceLogs.logs_folder.v2'

    def __init__(self, devkit_commands, devkits_window, settings, *args):
        super(DeviceLogs, self).__init__(self.BUTTON_NAME, *args)
        self.devkit_commands = devkit_commands
        self.devkits_window = devkits_window
        self.settings = settings
        self.logs_folder = None
        self.sync_future = None
        self.modal_wait = None
        self.steam_log = ''
        self.scroll_down = False

    def setup(self):
        super(DeviceLogs, self).setup()
        if self.LOGS_FOLDER_KEY in self.settings:
            self.logs_folder = self.settings[self.LOGS_FOLDER_KEY]
        else:
            self.logs_folder = str(pathlib.Path(os.path.expanduser('~/.devkit-client-gui')))

    def tick(self, visible):
        imgui.begin(self.BUTTON_NAME, False, imgui.WINDOW_NO_COLLAPSE | imgui.WINDOW_NO_MOVE | imgui.WINDOW_NO_RESIZE)
        imgui.columns(2)
        imgui.set_column_width(0, 170)
        imgui.text('Download logs to:')
        imgui.next_column()
        if imgui.button('...##BrowseDownloadLogsFolder'):
            result = browse_directory('Select Download Logs Folder', self.logs_folder)
            if result:
                self.logs_folder = result
        imgui.same_line()
        imgui.push_item_width(-1)
        changed, s = imgui.input_text(' ', self.logs_folder, 1000)
        if changed:
            self.logs_folder = s
        imgui.pop_item_width()
        imgui.columns(1)
        if imgui.button('Refresh'):
            self.settings[self.LOGS_FOLDER_KEY] = self.logs_folder
            self.sync_future = self.devkit_commands.sync_logs(
                self.devkits_window.selected_devkit,
                self.logs_folder
            )
            self.modal_wait = ModalWait(
                self.viewport,
                self.toolbar,
                'Retrieving logs from {!r}'.format(self.devkits_window.selected_devkit.name),
                self.sync_future,
                exit_on_success=True,
            )
            self.modal_wait.signal_task_dismiss.connect(lambda **kwargs: self.reload_logs())
            self.toolbar.modal_dialog = self.modal_wait
        imgui.same_line()
        if imgui.button('Open Folder'):
            devkit = self.devkits_window.selected_devkit
            if devkit is not None:
                open_folder(os.path.join(self.logs_folder, devkit.name))
        imgui.begin_child('logs')
        line_count = self.steam_log.count('\n') + 1
        line_height = imgui.get_text_line_height()
        content_height = (line_count + 1) * line_height + imgui.get_style().frame_padding.y * 2
        widget_height = max(content_height, imgui.get_window_height())
        imgui.input_text_multiline('', self.steam_log, -1, imgui.get_window_width(), widget_height, imgui.INPUT_TEXT_READ_ONLY)
        if self.scroll_down:
            imgui.set_scroll_y(imgui.get_scroll_max_y())
            self.scroll_down = False
        imgui.end_child()
        imgui.end()

    def reload_logs(self):
        devkit = self.devkits_window.selected_devkit
        if devkit is None:
            logger.warning('No device selected for loading logs')
            return

        # Per-device folder structure: {logs_folder}/{device_name}/logs/
        device_logs_folder = os.path.join(self.logs_folder, devkit.name, 'logs')

        # Steam Frame/Deckard uses steam_output.log, others use console-linux.txt
        if devkit.is_deckard:
            log_filename = 'steam_output.log'
        else:
            log_filename = 'console-linux.txt'

        steam_log_path = os.path.join(device_logs_folder, log_filename)
        if not os.path.exists(steam_log_path):
            logger.warning('Devkit log does not exist: %r', steam_log_path)
            return
        self.steam_log = open(steam_log_path, 'rt', errors='replace').read()
        self.scroll_down = True


class RemoteShell:
    BUTTON_NAME = 'Remote Shell'

    def __init__(self, devkit_commands, devkits_window, toolbar):
        self.devkit_commands = devkit_commands
        self.devkits_window = devkits_window
        self.toolbar = toolbar

    def setup(self):
        self.toolbar.signal_pressed.connect(self.on_pressed)

    def on_pressed(self, name , **kwargs):
        if name != self.BUTTON_NAME:
            return
        f = self.devkit_commands.open_remote_shell(self.devkits_window.selected_devkit)
        f.add_done_callback(self.on_open_remote_shell_done)

    def on_open_remote_shell_done(self, f):
        try:
            p = f.result()
            logger.info(f'Remote shell started, pid {p.pid}')
        except Exception as e:
            devkit_client.log_exception(e)


class CEFConsole(SubTool):
    BUTTON_NAME = 'CEF console'

    def on_pressed(self, name, selected_devkit, **kwargs):
        if name != self.BUTTON_NAME:
            return

        # forcing a refresh so have accurate status is better than risking an out of date steam client restart
        status_future = self.devkit_commands.steamos_get_status(selected_devkit)
        self.toolbar.modal_dialog = ModalWait(
            self.viewport,
            self.toolbar,
            f'Refresh device status {selected_devkit.name!r}',
            status_future,
            exit_on_success=True
        )

        def on_status_refreshed(self, f):
            try:
                f.result()
            except Exception as e:
                devkit_client.log_exception(e)

            def on_open_cef_console_done(self, f):
                try:
                    f.result()
                except Exception as e:
                    devkit_client.log_exception(e)

            if not selected_devkit.cef_debugging_enabled:
                enable_cef_debugging_future = self.devkit_commands.enable_cef_debugging(selected_devkit)
                self.toolbar.modal_dialog = ModalWait(
                    self.viewport,
                    self.toolbar,
                    f'Enable CEF console on {selected_devkit.name!r}',
                    enable_cef_debugging_future,
                    exit_on_success=True
                )
                self.toolbar.modal_dialog.override_output_text = 'Enabling CEF console - the Steam client will restart'
                # delay opening chrome a bit
                def open_cef_console(_):
                    f = self.devkit_commands.open_cef_console(selected_devkit)
                    f.add_done_callback(functools.partial(on_open_cef_console_done, self))
                enable_cef_debugging_future.add_done_callback(open_cef_console)
            else:
                f = self.devkit_commands.open_cef_console(selected_devkit)
                f.add_done_callback(functools.partial(on_open_cef_console_done, self))

        status_future.add_done_callback(functools.partial(on_status_refreshed, self))


class Screenshot(SubTool):
    BUTTON_NAME = 'Take Screenshot'
    FOLDER_KEY = 'Screenshot.folder'
    FILENAME_KEY = 'Screenshot.filename'
    TIMESTAMP_KEY = 'Screenshot.timestamp'
    MODE_KEY = 'Screenshot.mode'

    def setup(self):
        if self.FOLDER_KEY not in self.settings:
            self.settings[self.FOLDER_KEY] = str(pathlib.Path(os.path.expanduser('~/Pictures')))
        if self.FILENAME_KEY not in self.settings:
            self.settings[self.FILENAME_KEY] = ''
        if self.TIMESTAMP_KEY not in self.settings:
            self.settings[self.TIMESTAMP_KEY] = True
        if self.MODE_KEY not in self.settings:
            self.settings[self.MODE_KEY] = 1
        super(Screenshot, self).setup()

    def devkits_window_draw(self, selected_devkit):
        xprop = None # passes down the type of screenshot

        imgui.text('Folder:')
        imgui.same_line()
        if imgui.button('...##BrowseScreenshotFolder'):
            result = browse_directory('Select Screenshot Folder', self.settings[self.FOLDER_KEY])
            if result:
                self.settings[self.FOLDER_KEY] = result
        imgui.same_line()
        imgui.set_next_item_width(40*CHARACTER_WIDTH)
        changed, s = imgui.input_text('##screenshot_folder', self.settings[self.FOLDER_KEY], 260)
        if changed:
            self.settings[self.FOLDER_KEY] = s

        imgui.same_line()
        imgui.text('Filename (optional):')
        imgui.same_line()
        imgui.set_next_item_width(18*CHARACTER_WIDTH)
        changed, s = imgui.input_text('##screenshot_filename', self.settings[self.FILENAME_KEY], 128)
        if changed:
            self.settings[self.FILENAME_KEY] = s

        imgui.same_line()
        clicked, v = imgui.checkbox('timestamp', self.settings[self.TIMESTAMP_KEY])
        if clicked:
            self.settings[self.TIMESTAMP_KEY] = v

        if not selected_devkit.is_deckard:
            imgui.same_line()
            mode_choices = [
                'baseplane only',
                'all real layers',
                'full composition',
                'screen buffer'
                ]
            imgui.push_item_width(16*CHARACTER_WIDTH)
            clicked, selected_index = imgui.combo(
                '##ScreenshotMode', self.settings[self.MODE_KEY] - 1, mode_choices
            )
            imgui.pop_item_width()
            if clicked:
                self.settings[self.MODE_KEY] = selected_index + 1
            xprop = self.settings[self.MODE_KEY]

        imgui.same_line()
        # gross - plz halp with layout
        imgui.set_cursor_pos_x(1100)
        if imgui.button(Screenshot.BUTTON_NAME):
            task_future = self.devkit_commands.screenshot(
                selected_devkit,
                self.settings[self.FOLDER_KEY],
                self.settings[self.FILENAME_KEY],
                self.settings[self.TIMESTAMP_KEY],
                xprop
                )
            self.toolbar.modal_dialog = ModalWait(
                self.viewport,
                self.toolbar,
                f'Capturing Screenshot from {selected_devkit.name}',
                task_future,
                exit_on_success=True,
            )


class PerfOverlay(SubTool):
    FOLDER_KEY = 'PerfOverlay.folder.2'

    def setup(self):
        super(PerfOverlay, self).setup()
        if self.FOLDER_KEY not in self.settings:
            self.settings[self.FOLDER_KEY] = str(pathlib.Path(os.path.expanduser('~/Downloads/Frametime')))
        # tri-states
        self.draw_perf_overlay = None
        self.log_perf_data = None

    def on_selected_devkit(self, kit, **kwargs):
        # When switching kits, the state of the overlay buttons goes back to undefined
        self.draw_perf_overlay = None
        self.log_perf_data = None

    def devkits_window_draw(self, selected_devkit):
        imgui.text('Folder:')
        imgui.same_line()
        if imgui.button('...##BrowsePerfDataFolder'):
            result = browse_directory('Select Perf Data Folder', self.settings[self.FOLDER_KEY])
            if result:
                self.settings[self.FOLDER_KEY] = result
        imgui.same_line()
        imgui.set_next_item_width(40*CHARACTER_WIDTH)
        changed, s = imgui.input_text('##PerfDataFolder', self.settings[self.FOLDER_KEY], 260)
        if changed:
            self.settings[self.FOLDER_KEY] = s

        imgui.same_line()
        if self.draw_perf_overlay is None:
            imgui.internal.push_item_flag(imgui.internal.ITEM_MIXED_VALUE, True)
            clicked, v = imgui.checkbox('Draw performance overlay', False)
            imgui.internal.push_item_flag(imgui.internal.ITEM_MIXED_VALUE, False)
        else:
            clicked, v = imgui.checkbox('Draw performance overlay', self.draw_perf_overlay)
        if clicked:
            self.draw_perf_overlay = v
            cmd_future = self.devkit_commands.simple_command(selected_devkit, ['mangohudctl', 'set', 'no_display', 'false' if self.draw_perf_overlay else 'true'])
            self.toolbar.modal_dialog = ModalWait(
                self.viewport,
                self.toolbar,
                'Change performance overlay drawing',
                cmd_future,
                exit_on_success=True,
            )

        imgui.same_line()
        imgui.set_cursor_pos_x(1100)
        perf_log_button = 'Stop Capture' if self.log_perf_data else 'Start Frametime Capture'
        if imgui.button(perf_log_button):
            if self.log_perf_data:
                stop_log_future = self.devkit_commands.simple_command(selected_devkit, ['mangohudctl', 'set', 'log_session', 'false'])
                def download_logs(f):
                    self.log_perf_data = False
                    download_logs_future = self.devkit_commands.sync_pattern( selected_devkit, self.settings[self.FOLDER_KEY], ['--include=mangoapp_*.csv', '--exclude=*'])
                    self.modal_wait = ModalWait(
                        self.viewport,
                        self.toolbar,
                        'Downloading performance data',
                        download_logs_future,
                        exit_on_success=True,
                    )
                    self.toolbar.modal_dialog = self.modal_wait
                stop_log_future.add_done_callback(download_logs)
                self.modal_wait = ModalWait(
                    self.viewport,
                    self.toolbar,
                    'Turn off perf logging',
                    stop_log_future,
                    exit_on_success=True,
                )
                self.toolbar.modal_dialog = self.modal_wait
            else:
                self.devkit_commands.simple_command(selected_devkit, ['mangohudctl', 'set', 'log_session', 'true'])
                self.log_perf_data = True


class GPUTrace(SubTool):
    BUTTON_NAME = 'GPUVis System Trace'
    FILEPATH_KEY = 'GPUTrace.filepath.3'
    LAUNCH_KEY = 'GPUTrace.launch'
    GPUVIS_KEY = 'GPUTrace.gpuvis_path.3'

    def setup(self):
        if self.FILEPATH_KEY not in self.settings:
            self.settings[self.FILEPATH_KEY] = str(pathlib.Path(os.path.expanduser('~/Downloads/GPUVis/trace.zip')))
        if self.LAUNCH_KEY not in self.settings:
            self.settings[self.LAUNCH_KEY] = True
        self.refresh_gpuvis_path()
        super(GPUTrace, self).setup()

    def refresh_gpuvis_path(self):
        if ( self.GPUVIS_KEY in self.settings ) and os.path.exists( self.settings[self.GPUVIS_KEY] ):
            # gpuvis may be tethered to an OS installed version
            return

        gpuvis_bin = 'gpuvis.exe' if platform.system() == 'Windows' else 'gpuvis'

        # search in PATH first
        gpuvis_path = shutil.which(gpuvis_bin)
        if gpuvis_path is not None:
            self.settings[self.GPUVIS_KEY] = gpuvis_path
            return

        if platform.system() != 'Windows':
            # we only bundle gpuvis in the Windows build, so if we didn't find it .. we're done
            self.settings[self.GPUVIS_KEY] = 'NOT SET'
            self.settings[self.LAUNCH_KEY] = False
            return

        # check for a bundled gpuvis
        gpuvis_path = os.path.join( devkit_client.ROOT_DIR, r'gpuvis\gpuvis.exe' )
        if os.path.exists( gpuvis_path ):
            logger.info(f'Found bundled gpuvis: {gpuvis_path}')
            self.settings[self.GPUVIS_KEY] = gpuvis_path
            return

        # not found
        self.settings[self.GPUVIS_KEY] = 'NOT SET'
        self.settings[self.LAUNCH_KEY] = False

    def devkits_window_draw(self, selected_devkit):
        imgui.text('  File:')
        imgui.same_line()
        if imgui.button('...##BrowseGpuTraceFile'):
            result = browse_file('Select GPU Trace File', self.settings[self.FILEPATH_KEY])
            if result:
                self.settings[self.FILEPATH_KEY] = result
        imgui.same_line()
        imgui.set_next_item_width(40*CHARACTER_WIDTH)
        changed, s = imgui.input_text('##gpu_trace_filepath', self.settings[self.FILEPATH_KEY], 260)
        if changed:
            self.settings[self.FILEPATH_KEY] = s
        imgui.same_line()
        clicked, v = imgui.checkbox('Launch GPUVis:', self.settings[self.LAUNCH_KEY])
        if clicked:
            self.settings[self.LAUNCH_KEY] = v
        imgui.same_line()
        imgui.set_cursor_pos_x(74*CHARACTER_WIDTH)
        imgui.text('GPUVis:')
        imgui.same_line()
        if imgui.button('...##BrowseGpuvisPath'):
            result = browse_file('Select GPUVis Executable', self.settings[self.GPUVIS_KEY])
            if result:
                self.settings[self.GPUVIS_KEY] = result
        imgui.same_line()
        imgui.set_next_item_width(40*CHARACTER_WIDTH)
        changed, s = imgui.input_text('##gpu_trace_gpuvis_path', self.settings[self.GPUVIS_KEY], 260)
        if changed:
            self.settings[self.GPUVIS_KEY] = s
        imgui.same_line()
        imgui.set_cursor_pos_x(1100)
        if imgui.button(GPUTrace.BUTTON_NAME):
            task_future = self.devkit_commands.gpu_trace(
                selected_devkit,
                self.settings[self.FILEPATH_KEY],
                self.settings[self.LAUNCH_KEY],
                self.settings[self.GPUVIS_KEY]
                )
            self.toolbar.modal_dialog = ModalWait(
                self.viewport,
                self.toolbar,
                f'Capturing system trace from {selected_devkit.name}',
                task_future,
                exit_on_success=True,
            )


class RGPCapture(SubTool):
    BUTTON_NAME = 'Radeon GPU Profiler'
    FOLDER_KEY = 'RGPCapture.folder'
    LAUNCH_KEY = 'RGPCapture.launch'
    RGP_KEY = 'RGPCapture.RGP_path'

    def setup(self):
        if self.FOLDER_KEY not in self.settings:
            self.settings[self.FOLDER_KEY] = str(pathlib.Path(os.path.expanduser('~/Downloads/RGP')))
        if self.LAUNCH_KEY not in self.settings:
            self.settings[self.LAUNCH_KEY] = True
        if self.RGP_KEY not in self.settings:
            rgp_bin = 'RadeonGPUProfiler.exe' if platform.system() == 'Windows' else 'RadeonGPUProfiler'
            rgp_path = shutil.which(rgp_bin)
            if rgp_path is None:
                rgp_path = 'NOT SET'
            self.settings[self.RGP_KEY] = rgp_path
        devkit_client.g_signal_status.connect(self._status_update)
        super(RGPCapture, self).setup()

    def _status_update(self, status, **kwargs):
        if not self.modal_wait:
            return
        self.modal_wait.override_output_text = status

    def devkits_window_draw(self, selected_devkit):
        imgui.text('Folder:')
        imgui.same_line()
        if imgui.button('...##BrowseRgpCaptureFolder'):
            result = browse_directory('Select RGP Capture Folder', self.settings[self.FOLDER_KEY])
            if result:
                self.settings[self.FOLDER_KEY] = result
        imgui.same_line()
        imgui.set_next_item_width(40*CHARACTER_WIDTH)
        changed, s = imgui.input_text('##rgp_capture_folder', self.settings[self.FOLDER_KEY], 260)
        if changed:
            self.settings[self.FOLDER_KEY] = s
        imgui.same_line()
        clicked, v = imgui.checkbox('Launch RGP:', self.settings[self.LAUNCH_KEY])
        if clicked:
            self.settings[self.LAUNCH_KEY] = v
        imgui.same_line()
        imgui.set_cursor_pos_x(74*CHARACTER_WIDTH)
        imgui.text('RGP:')
        imgui.same_line()
        if imgui.button('...##BrowseRgpPath'):
            # Determine appropriate file filter based on platform
            import platform
            if platform.system() == 'Windows':
                filetypes = [('Executable files', '*.exe')]
            else:
                filetypes = [('All files', '*')]
            result = browse_file('Select RGP Executable', self.settings[self.RGP_KEY], filetypes)
            if result:
                self.settings[self.RGP_KEY] = result
        imgui.same_line()
        imgui.set_next_item_width(40*CHARACTER_WIDTH)
        changed, s = imgui.input_text('##rgp_path', self.settings[self.RGP_KEY], 260)
        if changed:
            self.settings[self.RGP_KEY] = s
        imgui.same_line()
        imgui.set_cursor_pos_x(1100)
        if imgui.button(RGPCapture.BUTTON_NAME):
            task_future = self.devkit_commands.rgp_capture(selected_devkit, self.settings[self.FOLDER_KEY], self.settings[self.LAUNCH_KEY], self.settings[self.RGP_KEY])
            self.modal_wait = ModalWait(
                self.viewport,
                self.toolbar,
                f'Capturing RGP frame from {selected_devkit.name}',
                task_future,
                exit_on_success=True,
            )
            self.toolbar.modal_dialog = self.modal_wait


class RenderDocCapture(SubTool):
    BUTTON_NAME = 'Start RenderDoc'
    RDOC_KEY = 'RenderDocCapture.RenderDoc_path'

    def __init__(self, devkit_commands, viewport, toolbar, settings):
        super(RenderDocCapture, self).__init__(devkit_commands, viewport, toolbar, settings)
        self.devkit_commands.signal_steamos_status.connect(self.on_device_status_update)

    # We used to have this as an editable setting, but it's not very useful - hardcode a Windows and PATH check
    def _locate_renderdoc(self):
        if os.path.exists(self.settings.get(self.RDOC_KEY, 'NOT SET')):
            return True
        rdoc_bin = 'C:\\Program Files\\RenderDoc\\qrenderdoc.exe' if platform.system() == 'Windows' else 'qrenderdoc'
        rdoc_path = shutil.which(rdoc_bin)
        if rdoc_path is None:
            rdoc_path = 'NOT SET'
        self.settings[self.RDOC_KEY] = rdoc_path
        return os.path.exists(self.settings.get(self.RDOC_KEY, 'NOT SET'))

    def setup(self):
        self._locate_renderdoc()
        super(RenderDocCapture, self).setup()

    def on_device_status_update(self, devkit, **kwargs):
        """Sync replay server state with per-device setting."""
        desired_state = devkit.get_device_setting('renderdoc_replay_server_enabled', False)
        current_state = devkit.steamos_status.get('renderdoc_replay_server_running', False)
        if desired_state == current_state:
            return

        logger.info(f'{"Starting" if desired_state else "Stopping"} RenderDoc replay server on {devkit.name} (auto-sync)')
        toggle_future = self.devkit_commands.set_renderdoc_replay(devkit, desired_state)

        def on_auto_sync_done(f):
            try:
                f.result()
                devkit.steamos_status['renderdoc_replay_server_running'] = desired_state
                logger.info(f'RenderDoc replay server auto-sync completed on {devkit.name}')
            except Exception as e:
                devkit_client.log_exception(e)
                logger.error(f'Failed to auto-sync RenderDoc replay server on {devkit.name}')

        toggle_future.add_done_callback(on_auto_sync_done)

    def on_enable_renderdoc_done(self, selected_devkit, enabled, f):
        selected_devkit.is_renderdoc_capture_enabled = enabled

    def on_toggle_replay_server_done(self, selected_devkit, enable, f):
        # Update the cached status
        selected_devkit.steamos_status['renderdoc_replay_server_running'] = enable
        # Persist the desired state
        selected_devkit.set_device_setting('renderdoc_replay_server_enabled', enable)

    def devkits_window_draw(self, selected_devkit):
        imgui.text('RenderDoc:')
        imgui.same_line()
        imgui.set_cursor_pos_x(102)
        changed, v = imgui.checkbox('Enable capture layer', selected_devkit.is_renderdoc_capture_enabled)
        if changed:
            if v:
                switch_future = self.devkit_commands.config_steam_wrapper_flags(
                    selected_devkit,
                    enable = { 'ENABLE_VULKAN_RENDERDOC_CAPTURE': '1' }
                )
            else:
                switch_future = self.devkit_commands.config_steam_wrapper_flags(
                    selected_devkit,
                    disable = [ 'ENABLE_VULKAN_RENDERDOC_CAPTURE' ]
                )
            self.toolbar.modal_dialog = ModalWait(
                self.viewport,
                self.toolbar,
                ( 'Enable' if v else 'Disable' ) + f' RenderDoc Vulkan capture layer on {selected_devkit.name}',
                switch_future,
                exit_on_success = True
            )
            switch_future.add_done_callback(functools.partial(self.on_enable_renderdoc_done, selected_devkit, v))

        # Get replay server status from devkit state
        replay_server_running = selected_devkit.steamos_status.get('renderdoc_replay_server_running', False)
        imgui.same_line()
        changed, v = imgui.checkbox('Run the replay server', replay_server_running)
        if changed:
            enable = not replay_server_running
            toggle_future = self.devkit_commands.set_renderdoc_replay(selected_devkit, enable)
            self.toolbar.modal_dialog = ModalWait(
                self.viewport,
                self.toolbar,
                f'{"Starting" if enable else "Stopping"} RenderDoc replay server on {selected_devkit.name}',
                toggle_future,
                exit_on_success=True,
            )
            toggle_future.add_done_callback(functools.partial(self.on_toggle_replay_server_done, selected_devkit, enable))

        imgui.same_line()
        imgui.set_cursor_pos_x(1100)
        if imgui.button(RenderDocCapture.BUTTON_NAME):
            if not self._locate_renderdoc():
                failed_future = concurrent.futures.Future()
                failed_future.set_exception(
                    Exception('Please install qrenderdoc - make sure it is in PATH on Linux.')
                )
                self.toolbar.modal_dialog = ModalWait(
                    self.viewport,
                    self.toolbar, 'Error',
                    failed_future
                )
                return
            # TODO: The replayhost thing in RenderDoc is useless right now, as it complains you need to add it to the GUI first :v
            #       and remoteaccess just doesn't work.
            #machine = devkit_client.resolve_machine(
            #    selected_devkit.machine_command_args[0],
            #    name_type=selected_devkit.machine_command_args[1],
            #    http_port=selected_devkit.http_port
            #)
            rdoc_cmd = [self.settings[self.RDOC_KEY]] #, "--remoteaccess", machine.address, "--replayhost", machine.address]
            logger.info(' '.join(rdoc_cmd))
            devkit_client.spawn_detached(rdoc_cmd)

class ProtonLogs(SubTool):
    BUTTON_NAME = 'Sync Proton Logs'
    FOLDER_KEY = 'ProtonLogs.folder'
    WINEDEBUG_KEY = 'ProtonLogs.WINEDEBUG'

    def setup(self):
        if self.FOLDER_KEY not in self.settings:
            self.settings[self.FOLDER_KEY] = str(pathlib.Path(os.path.expanduser('~/Downloads/ProtonLogs')))
        if self.WINEDEBUG_KEY not in self.settings:
            self.settings[self.WINEDEBUG_KEY] = ''
        super(ProtonLogs, self).setup()
        # TODO: initialize this better?
        self.show_apply = False

    def on_apply_done(self, selected_devkit, enabled, f):
        selected_devkit.is_proton_log_enabled = enabled
        self.show_apply = False

    def _config(self, selected_devkit, enable):
        enable_dict = None
        disable_list = None
        if enable:
            enable_dict = { 'PROTON_LOG': '1' }
            if self.settings[self.WINEDEBUG_KEY] != '':
                enable_dict['PROTON_LOG'] = self.settings[self.WINEDEBUG_KEY]
            # Force this off from previous releases - we can stop doing this eventually
            disable_list = ['WINEDEBUG',]
        else:
            disable_list = ['PROTON_LOG', 'WINEDEBUG']
        switch_future = self.devkit_commands.config_steam_wrapper_flags(
                selected_devkit,
                enable = enable_dict,
                disable = disable_list
            )
        self.toolbar.modal_dialog = ModalWait(
            self.viewport,
            self.toolbar,
            f'Apply Proton log settings on {selected_devkit.name}',
            switch_future,
            exit_on_success = True,
        )
        switch_future.add_done_callback(functools.partial(self.on_apply_done, selected_devkit, enable))

    def devkits_window_draw(self, selected_devkit):
        imgui.text('Folder:')
        imgui.same_line()
        if imgui.button('...##BrowseProtonLogsFolder'):
            result = browse_directory('Select Proton Logs Folder', self.settings[self.FOLDER_KEY])
            if result:
                self.settings[self.FOLDER_KEY] = result
        imgui.same_line()
        imgui.set_next_item_width(40*CHARACTER_WIDTH)
        changed, s = imgui.input_text('##proton_logs_folder', self.settings[self.FOLDER_KEY], 260)
        if changed:
            self.settings[self.FOLDER_KEY] = s

        imgui.same_line()
        changed, v = imgui.checkbox('Proton logging enabled', selected_devkit.is_proton_log_enabled)
        if changed:
            self._config(selected_devkit, v)

        imgui.same_line()
        imgui.set_cursor_pos_x(86*CHARACTER_WIDTH)
        imgui.text('PROTON_LOG:')
        imgui.same_line()
        imgui.set_next_item_width(26*CHARACTER_WIDTH)
        changed, s = imgui.input_text('##proton_log_winedebug', self.settings[self.WINEDEBUG_KEY], 128)
        if changed:
            self.show_apply = True
            self.settings[self.WINEDEBUG_KEY] = s
        imgui.same_line()
        if self.show_apply and imgui.button('Apply##ProtonLogs'):
            # Always enabled logging, but we may delete the WINEDEBUG customization
            self._config(selected_devkit, True)

        imgui.same_line()
        imgui.set_cursor_pos_x(1100)
        if imgui.button(self.BUTTON_NAME):
            sync_future = self.devkit_commands.sync_pattern(
                selected_devkit,
                self.settings[self.FOLDER_KEY],
                ['--include=steam-*.log', '--exclude=*']
            )
            self.toolbar.modal_dialog = ModalWait(
                self.viewport,
                self.toolbar,
                f'Download Proton logs from {selected_devkit.name}',
                sync_future,
                exit_on_success=True
            )


class ControllerConfigs(SubTool):
    BUTTON_NAME = 'Get Controller Config'
    FOLDER_KEY = 'ControllerConfigs.folder'
    APPID_KEY = 'ControllerConfigs.appid'
    GAMEID_KEY = 'ControllerConfigs.gameid'

    def setup(self):
        super(ControllerConfigs, self).setup()
        if self.FOLDER_KEY not in self.settings:
            self.settings[self.FOLDER_KEY] = str(pathlib.Path(os.path.expanduser('~/SteamDeck_ControllerConfigs')))
        if self.APPID_KEY not in self.settings:
            self.settings[self.APPID_KEY] = ''
        if self.GAMEID_KEY not in self.settings:
            self.settings[self.GAMEID_KEY] = ''

    def devkits_window_draw(self, selected_devkit):
        imgui.text('Folder:')
        imgui.same_line()
        if imgui.button('...##BrowseControllerConfigFolder'):
            result = browse_directory('Select Controller Config Folder', self.settings[self.FOLDER_KEY])
            if result:
                self.settings[self.FOLDER_KEY] = result
        imgui.same_line()
        imgui.set_next_item_width(40*CHARACTER_WIDTH)
        changed, s = imgui.input_text(
            '##controller_config_folder',
            self.settings[self.FOLDER_KEY],
            260
        )
        if changed:
            self.settings[self.FOLDER_KEY] = s

        imgui.same_line()
        imgui.text('AppID:')
        imgui.same_line()
        imgui.set_next_item_width(16*CHARACTER_WIDTH)
        changed, s = imgui.input_text(
            '##controller_config_appid',
            self.settings[self.APPID_KEY],
            64
        )
        if changed:
            self.settings[self.APPID_KEY] = s
        imgui.same_line()
        imgui.text('(or) name:')
        imgui.same_line()
        imgui.set_next_item_width(16*CHARACTER_WIDTH)
        changed, s = imgui.input_text(
            '##controller_config_gameid',
            self.settings[self.GAMEID_KEY],
            64
        )
        if changed:
            self.settings[self.GAMEID_KEY] = s

        imgui.same_line()
        imgui.set_cursor_pos_x(1100)
        if imgui.button(self.BUTTON_NAME):
            task_future = self.devkit_commands.dump_controller_config(
                selected_devkit,
                self.settings[self.APPID_KEY],
                self.settings[self.GAMEID_KEY],
                self.settings[self.FOLDER_KEY],
            )
            self.toolbar.modal_dialog = ModalWait(
                self.viewport,
                self.toolbar,
                'Retrieving controller configuration from {}'.format(selected_devkit.name),
                task_future,
                exit_on_success=False,
            )


class DeleteTitle(SubTool):
    BUTTON_NAME = 'Delete Title(s)'
    GAMEID_KEY = 'DeleteTitle.gameid'
    DELETE_ALL_KEY = 'DeleteTitle.delete_all'
    RESET_STEAM_KEY = 'DeleteTitle.reset_steam_client'

    def setup(self):
        super(DeleteTitle, self).setup()
        if self.GAMEID_KEY not in self.settings:
            self.settings[self.GAMEID_KEY] = ''
        if self.DELETE_ALL_KEY not in self.settings:
            self.settings[self.DELETE_ALL_KEY] = False
        if self.RESET_STEAM_KEY not in self.settings:
            self.settings[self.RESET_STEAM_KEY] = False

    def devkits_window_draw(self, selected_devkit):
        imgui.text(' Title:')
        imgui.same_line()
        imgui.set_next_item_width(48*CHARACTER_WIDTH)
        changed, s = imgui.input_text(
            '##delete_title_gameid',
            self.settings[self.GAMEID_KEY],
            128
        )
        if changed:
            self.settings[self.GAMEID_KEY] = s
        imgui.same_line()
        changed, v = imgui.checkbox('Delete all devkit titles', self.settings[self.DELETE_ALL_KEY])
        if changed:
            self.settings[self.DELETE_ALL_KEY] = v
        imgui.same_line()
        changed, v = imgui.checkbox('Delete local Steam content + reset client', self.settings[self.RESET_STEAM_KEY])
        if changed:
            self.settings[self.RESET_STEAM_KEY] = v
        imgui.same_line()
        imgui.set_cursor_pos_x(1100)
        if imgui.button(self.BUTTON_NAME):
            if len(self.settings[self.GAMEID_KEY]) > 0:
                if re.fullmatch(GAMEID_ALLOWED_PATTERN, s) is None:
                    # bit of an odd pattern for showing an error, could be factored into a utility
                    failed_future = concurrent.futures.Future()
                    failed_future.set_exception(Exception(f'Title name {s!r} must match {GAMEID_ALLOWED_PATTERN}'))
                    self.toolbar.modal_dialog = ModalWait(
                        self.viewport,
                        self.toolbar,
                        'ERROR',
                        failed_future
                    )
                    return
            task_future = self.devkit_commands.delete_title(
                selected_devkit,
                self.settings[self.GAMEID_KEY],
                self.settings[self.DELETE_ALL_KEY],
                self.settings[self.RESET_STEAM_KEY],
            )
            self.toolbar.modal_dialog = ModalWait(
                self.viewport,
                self.toolbar,
                f'Deleting uploaded titles from {selected_devkit.name}',
                task_future,
                exit_on_success=True,
            )

class RestartSession(SubTool):
    '''Restart the session on the selected device.'''
    BUTTON_NAME = 'Reload Session'

    def on_pressed(self, name, selected_devkit, **kwargs):
        if name != self.BUTTON_NAME:
            return
        task_future = self.devkit_commands.restart_session(selected_devkit)
        self.toolbar.modal_dialog = ModalWait(
            self.viewport,
            self.toolbar,
            f'Restarting session on {selected_devkit.name}',
            task_future,
            exit_on_success=True,
        )


class BrowseFiles(SubTool):
    BUTTON_NAME = 'Browse Device Files'

    def on_pressed(self, name, selected_devkit, **kwargs):
        if name != self.BUTTON_NAME:
            return
        spawn_future = self.devkit_commands.browse_files(selected_devkit)
        self.toolbar.modal_dialog = ModalWait(
            self.viewport,
            self.toolbar,
            'Starting FileZilla',
            spawn_future,
            exit_on_success=True,
        )


class ChangePassword(SubTool):
    BUTTON_NAME = 'Set or Change Password'

    def on_pressed(self, name, selected_devkit, **kwars):
        if name != self.BUTTON_NAME:
            return
        f = self.devkit_commands.set_password(selected_devkit)
        # fires once the operation completes
        f.add_done_callback(functools.partial(self.on_set_password_done, selected_devkit))

    def on_set_password_done(self, selected_devkit, f):
        try:
            f.result()
        except Exception as e:
            devkit_client.log_exception(e)
        self.toolbar.signal_pressed.emit(name=RefreshStatus.BUTTON_NAME, selected_devkit=selected_devkit)


class ImGui_SDL2_Viewport:
    '''Create a SDL2 window, GL context and run frames.'''

    def __init__(self, width, height, window_name):
        self.default_width = width
        self.default_height = height
        self.window_name = window_name
        self.sdl_window = None
        self.gl_context = None
        self.sdl_width = ctypes.c_int(0)
        self.sdl_height = ctypes.c_int(0)
        self.running = False

        # enable/disable
        self.verbose_fps = False
        # perf verbose state
        self.avg_frametime = None
        self.avg_swaptime = None
        self.perf_count = 0
        self.verbose_last = None

        # set to None for no limiter
        self.fps_limiter = 60.

        self.signal_draw = signalslot.Signal()

    @property
    def width(self):
        return self.sdl_width.value

    @property
    def height(self):
        return self.sdl_height.value

    def _create_gl_window(self, best_settings=True):
        sdl2.SDL_GL_ResetAttributes()

        sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_DOUBLEBUFFER, 1)
        sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_DEPTH_SIZE, 24)
        sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_STENCIL_SIZE, 8)
        if best_settings:
            sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_ACCELERATED_VISUAL, 1)
            # Multisample looks ok on Linux, but is blurry on Windows
            sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_MULTISAMPLEBUFFERS, 0 if platform.system() == 'Windows' else 1)
            sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_MULTISAMPLESAMPLES, 0 if platform.system() == 'Windows' else 4)
        else:
            sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_ACCELERATED_VISUAL, 1)
            sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_MULTISAMPLEBUFFERS, 0)
            sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_MULTISAMPLESAMPLES, 0)
        sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_CONTEXT_FLAGS, sdl2.SDL_GL_CONTEXT_FORWARD_COMPATIBLE_FLAG)
        sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_CONTEXT_MAJOR_VERSION, 4 if best_settings else 3)
        sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_CONTEXT_MINOR_VERSION, 1)
        sdl2.SDL_GL_SetAttribute(sdl2.SDL_GL_CONTEXT_PROFILE_MASK, sdl2.SDL_GL_CONTEXT_PROFILE_CORE)

        sdl2.SDL_SetHint(sdl2.SDL_HINT_MAC_CTRL_CLICK_EMULATE_RIGHT_CLICK, b"1")
        sdl2.SDL_SetHint(sdl2.SDL_HINT_VIDEO_HIGHDPI_DISABLED, b"1")
        # Do not disable system composition, which in turn would disable transparent windows in CEF
        sdl2.SDL_SetHint(sdl2.SDL_HINT_VIDEO_X11_NET_WM_BYPASS_COMPOSITOR, b"0")
        # Do not inhibit the screen saver when this is running
        sdl2.SDL_SetHint(sdl2.SDL_HINT_VIDEO_ALLOW_SCREENSAVER, b"1")

        self.sdl_window = sdl2.SDL_CreateWindow(self.window_name.encode('utf-8'),
                                    sdl2.SDL_WINDOWPOS_CENTERED, sdl2.SDL_WINDOWPOS_CENTERED,
                                    self.default_width, self.default_height,
                                    sdl2.SDL_WINDOW_OPENGL|sdl2.SDL_WINDOW_RESIZABLE
                                        )

        if self.sdl_window is None:
            logger.warning('SDL_CreateWindow failed: {}'.format(sdl2.SDL_GetError()))
            return False

        icon_file = os.path.join(devkit_client.ROOT_DIR, ICON_FILENAME).encode()
        assert os.path.exists(icon_file)

        # https://github.com/libsdl-org/SDL/blob/SDL2/src/video/x11/SDL_x11window.c#L750
        # SDL_assert(icon->format->format == SDL_PIXELFORMAT_ARGB8888);
        # https://github.com/libsdl-org/SDL/blob/SDL2/src/video/windows/SDL_windowswindow.c#L639
        # ok, not documented otherwise, but SDL_SetWindowIcon expects ARGB8888

        # Load some pixels. Uncompressed TGAs are trivially easy, we don't need sdl2.sdlimage..
        tga = open(icon_file,'rb').read()
        assert tga[0] == 0 # no image ID
        assert tga[1] == 0 # no colormap
        assert tga[2] == 2 # uncompressed true-color image
        w = int.from_bytes(tga[12:12+2], byteorder='little', signed=False)
        h = int.from_bytes(tga[14:14+2], byteorder='little', signed=False)
        depth = tga[16]
        assert depth == 32 # RGBA

        pixels = ctypes.create_string_buffer(tga[18:18+w*h*4])
        icon = sdl2.SDL_CreateRGBSurfaceWithFormatFrom(pixels, w, h, 32, w*4, sdl2.SDL_PIXELFORMAT_ARGB8888)
        assert icon is not None
        assert icon.contents.format.contents.format == sdl2.SDL_PIXELFORMAT_ARGB8888

        sdl2.SDL_SetWindowIcon(self.sdl_window, icon)
        sdl2.SDL_FreeSurface(icon)
        del pixels

        self.gl_context = sdl2.SDL_GL_CreateContext(self.sdl_window)
        if self.gl_context is None:
            logger.warning('SDL_GL_CreateContext failed: {}'.format(sdl2.SDL_GetError()))
            return False

        sdl2.SDL_GL_MakeCurrent(self.sdl_window, self.gl_context)

        if sdl2.SDL_GL_SetSwapInterval(1) < 0:
            # not worth an abort or settings degrade, we have a frame limiter too
            logger.warning('SDL_GL_SetSwapInterval failed: {}'.format(sdl2.SDL_GetError()))

        return True

    def report_versions(self):
        logger.info('Public build devkit client UI %s', devkit_client.__version__)
        logger.info('Python %s', platform.python_version())
        logger.info('Using pyimgui %s', imgui.__version__)
        logger.info('Using imgui %s', imgui.get_version())
        version = sdl2.SDL_version()
        sdl2.SDL_GetVersion(version)
        logger.info('Using SDL2 %s.%s.%s', version.major, version.minor, version.patch)

    def setup(self):
        self.report_versions()

        if platform.system() == 'Windows':
            # Fix the taskbar icon setup when running via python.exe (dev mode)
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Valve.SteamDeckDevkitClient')
            except Exception:
                pass

        if platform.system() == 'Linux':
            if is_running_under_wsl():
                sdl2.SDL_SetHint(sdl2.SDL_HINT_VIDEODRIVER, b"x11")
            else:
                # Fix startup on wayland - this needs to be set before init
                sdl2.SDL_SetHint(sdl2.SDL_HINT_VIDEODRIVER, b"wayland,x11")

        if sdl2.SDL_Init(sdl2.SDL_INIT_EVERYTHING) < 0:
            raise Exception(f'SDL_Init failed: {sdl2.SDL_GetErrorMsg()}')

        if self._create_gl_window(best_settings=True):
            return
        logger.info('Try GL context creation with more conservative settings')
        if not self._create_gl_window(best_settings=False):
            raise Exception('Could not create OpenGL window')

    def main(self):
        imgui.create_context()
        impl = imgui.integrations.sdl2.SDL2Renderer(self.sdl_window)

        event = sdl2.SDL_Event()
        self.running = True
        while self.running:
            frame_time = time.perf_counter()
            while sdl2.SDL_PollEvent(ctypes.byref(event)) != 0:
                if event.type == sdl2.SDL_QUIT:
                    self.running = False
                    break
                impl.process_event(event)
            impl.process_inputs()

            sdl2.SDL_GetWindowSize(self.sdl_window, ctypes.byref(self.sdl_width), ctypes.byref(self.sdl_height))

            imgui.new_frame()

            self.signal_draw.emit()

            gl.glClearColor(.2, .2, .2, 1)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT)

            imgui.render()
            impl.render(imgui.get_draw_data())

            swap_time = time.perf_counter()
            sdl2.SDL_GL_SwapWindow(self.sdl_window)

            t = time.perf_counter()
            swap_time = t - swap_time
            frame_time = t - frame_time

            # crude fps limiter, when vsync is silently broken, or too high
            if self.fps_limiter is not None:
                early = 1./self.fps_limiter - frame_time
                early -= swap_time
                if early > 0.001:
                    limiter_sleep = time.perf_counter()
                    time.sleep(early)
                    limiter_sleep = time.perf_counter() - limiter_sleep
                    # so verbose reports the corrected (limited) fps
                    frame_time += limiter_sleep

            if self.verbose_fps:
                self.perf_count += 1
                if self.perf_count == 1:
                    self.avg_swaptime = swap_time
                    self.avg_frametime = frame_time
                else:
                    self.avg_swaptime += (swap_time - self.avg_swaptime) / self.perf_count
                    self.avg_frametime += (frame_time - self.avg_frametime) / self.perf_count

                if self.verbose_last is None:
                    self.verbose_last = time.perf_counter()
                if t - self.verbose_last > 1.: # every second
                    logger.info(f'fps: {1./self.avg_frametime:4.1f} Hz' )
                    logger.info(f'swap delay: {self.avg_swaptime*1000.:4.1f} ms')
                    self.perf_count = 0
                    self.verbose_last = t

        impl.shutdown()
        sdl2.SDL_GL_DeleteContext(self.gl_context)
        sdl2.SDL_DestroyWindow(self.sdl_window)
        sdl2.SDL_Quit()


class Settings(collections.abc.MutableMapping):
    def __init__(self):
        self.is_shutdown = True
        self.settings_path = os.path.expanduser(os.path.join('~', '.devkit-client-gui', 'settings.pickle'))
        self.settings = {}
        if os.path.exists(self.settings_path):
            try:
                self.settings = pickle.load(open(self.settings_path, 'rb'))
            except Exception as e:
                # it is best to hard abort, in case this is a 'transient' error
                # if we continue with empty settings, the destructor will write out an empty file and wipe saved settings
                # this happens before the main window is up, but the exception dialog will still come up (even though it's not easy to parse)
                devkit_client.log_exception(e)
                raise Exception(f'Failed to load settings from {self.settings_path} - delete or move the file out of the way.')
            logger.info('Loaded settings: %r', self.settings_path)
        # destructor won't attempt to serialize settings again, any further changes will be lost
        self.is_shutdown = False

    def save_settings(self):
        # Settings are normally saved through an atexit handler, but in some cases an explicit save is useful
        os.makedirs(os.path.dirname(self.settings_path), exist_ok=True)
        pickle.dump(self.settings, open(self.settings_path, 'wb'))
        # because of atexit - trying to maximize the chances this gets printed somewhere
        sys.stderr.write('Saved settings {!r}\n'.format(self.settings_path))
        sys.stderr.flush()

    def shutdown(self):
        '''Use this to save settings and avoid problems due to interpreter shutting down in the destructor.'''
        if self.is_shutdown:
            return
        self.save_settings()
        self.is_shutdown = True

    def on_shutdown_signal(self, **kwargs):
        self.shutdown()

    def __del__(self):
        if self.is_shutdown:
            return
        if sys.is_finalizing():
            sys.stderr.write('Settings.__del__: interpreter is shutting down, cannot serialize settings!\n')
            sys.stderr.flush()
            return
        self.shutdown()

    def __getitem__(self, key):
        return self.settings.__getitem__(key)

    def __setitem__(self, key, value):
        return self.settings.__setitem__(key, value)

    def __delitem__(self, key):
        return self.settings.__delitem__(key)

    def __iter__(self):
        return self.settings.__iter__()

    def __len__(self):
        return self.settings.__len__()


class APIHandler(http.server.BaseHTTPRequestHandler):
    def _respond(self, d):
        self.send_response(http.HTTPStatus.OK)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(d).encode('UTF-8', 'replace'))

    def do_GET(self):
        client_api = self.server.client_api
        if self.path == '/selected_devkit':
            ret = {}
            selected_devkit = client_api.devkits_window.selected_devkit
            if selected_devkit is not None:
                ret = selected_devkit.machine.__dict__
            self._respond(ret)
            return
        if self.path == '/ssh_key_path':
            _, key_path, _ = devkit_client.ensure_devkit_key()
            self._respond({'key_path':key_path})
            return
        if self.path == '/title_settings':
            d = client_api.signal_title_settings.emit()
            self._respond(d)
            return
        self.send_error(http.HTTPStatus.NOT_FOUND)

    def do_POST(self):
        client_api = self.server.client_api
        if self.path == '/post_event':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            event = json.loads(post_data)
            logger.info('received an event: %r', event)
            name = None
            arch = None
            try:
                if (event['type'] == 'build' and event['status'] == 'success'):
                    name = event['name']
                    arch = event.get('arch')
            except Exception:
                pass
            if name is None:
                msg = f'malformed event: {event!r}'
                logger.error(msg)
                self.send_error(http.HTTPStatus.BAD_REQUEST, msg)
                return
            try:
                client_api.signal_build_success.emit(name=name, arch=arch)
            except Exception as e:
                msg = f'processing failed: {e!r}'
                logger.error(msg)
                self.send_error(http.HTTPStatus.INTERNAL_SERVER_ERROR, msg)
            self._respond({})
            return
        self.send_error(http.HTTPStatus.NOT_FOUND)


class ClientAPI(threading.Thread):
    """Primitive REST API server to expose information and basic commands to other local tools."""

    # devkit service listens on 32000 (all interfaces), so we're staying close for now
    HOST = '127.0.0.1'
    PORT = 32010

    def __init__(self, devkits_window):
        super(ClientAPI, self).__init__(daemon=True)
        self.devkits_window = devkits_window
        self.signal_title_settings = signalslot.Signal()
        self.signal_build_success = signalslot.Signal()

    def setup(self):
        self.start()

    def run(self):
        logger.info('Starting client API server')
        httpd = http.server.HTTPServer((ClientAPI.HOST, ClientAPI.PORT), APIHandler)
        httpd.client_api = self
        httpd.serve_forever()


def setup_console_handler(conf):
    # Setup the console handler as early as possible to catch early messages
    # Messages are collected, but may still be lost if an error happens before we get a chance to display the console
    root_logger = logging.getLogger()
    root_logger.setLevel(conf.verbose)
    console_handler = ConsoleHandler(
        root_logger,
        logging.Formatter('%(message)s')
    )
    console_handler.setup()
    if conf.logfile is not None:
        root_logger.addHandler(logging.FileHandler(conf.logfile))
    return console_handler


def main():
    parser = argparse.ArgumentParser(
        description='Steam Devkit Management Tool'
    )
    parser.add_argument(
        '--verbose', required=False, action='store',
        default='INFO', const='DEBUG', nargs='?',
        help='Set logging verbosity.'
    )
    parser.add_argument(
        '--logfile', required=False, action='store',
        help='Log to a file.'
    )
    parser.add_argument(
        '--valve', required=False, action='store_true',
        help='Force Valve mode features (default: auto detect).'
    )
    parser.add_argument(
        '--check-port-timeout', required=False, action='store',
        default=4,
        help='Timeout when checking open ports (default 4) - may need to be bumped up on very slow networks.'
    )
    parser.add_argument(
        '--disable-rsync-compress', required=False, action='store_true',
        help='Disable rsync compression (-z) during file transfers.'
    )
    if platform.system() != 'Windows':
        parser.add_argument(
            '--disable-popen-capture', required=False, action='store_true',
            help='Disable capturing of launched external processes output to the status window.'
        )
    if platform.system() == 'Windows':
        parser.add_argument(
            '--with-conemu', required=False, action='store',
            help='Configure run in terminal to use given exe with conemu syntax. Set to blank to clear.'
        )
        parser.add_argument(
            '--with-cmder', required=False, action='store',
            help='Configure run in terminal to use given exe with cmder syntax. Set to blank to clear.'
        )

    conf = parser.parse_args()

    devkit_client.g_disable_rsync_compress = conf.disable_rsync_compress

    if not getattr(sys, 'frozen', False) and sys.stderr is not None:
        # This sets up a default logging to stderr, unrelated to the console logging path
        logging.basicConfig(format='%(message)s', level=conf.verbose)
        console_handler = setup_console_handler(conf)
    else:
        # We are frozen, and sys.stderr is None (e.g. Windows)
        console_handler = setup_console_handler(conf)
        adapter = FileToConsoleHandlerAdapter(console_handler)
        sys.stderr = adapter
        sys.stdout = adapter
        logger.info('Running frozen - stdout/stderr redirectors are setup')


    # uncomment to enable zeroconf DEBUG verbose
    #zeroconf.log.setLevel(conf.verbose)

    # a reasonable level of verbosity, don't even do more when using --verbose
    logging.getLogger('paramiko').setLevel(logging.WARNING)

    devkit_client.proxy.disable_proxy()

    shutdown_signal = signalslot.Signal()

    if platform.system() != 'Windows' and conf.disable_popen_capture:
        devkit_client.g_linux_captured_popen_factory.enabled = False
    devkit_client.g_linux_captured_popen_factory.set_shutdown_signal( shutdown_signal )

    settings = Settings()
    shutdown_signal.connect(settings.on_shutdown_signal)
    atexit.register(settings.shutdown) # saves settings on abnormal termination

    devkit_client.g_win_custom_terminal.setup(conf, settings)

    devkit_commands = DevkitCommands(conf, shutdown_signal)
    devkit_commands.setup()

    viewport = ImGui_SDL2_Viewport(1280, 720, "Steam Devkit Management Tool")
    viewport.setup()

    # All of these hooks into the draw signal of the viewport
    toolbar = Toolbar(viewport)
    toolbar.setup()

    screenshot = Screenshot(devkit_commands, viewport, toolbar, settings)
    screenshot.setup()
    perf_overlay = PerfOverlay(devkit_commands, viewport, toolbar, settings)
    perf_overlay.setup()
    gpu_trace = GPUTrace(devkit_commands, viewport, toolbar, settings)
    gpu_trace.setup()
    rgp_capture = RGPCapture(devkit_commands,  viewport, toolbar, settings)
    rgp_capture.setup()
    renderdoc_capture = RenderDocCapture(devkit_commands,  viewport, toolbar, settings)
    renderdoc_capture.setup()
    proton_logs = ProtonLogs(devkit_commands, viewport, toolbar, settings)
    proton_logs.setup()
    controller_configs = ControllerConfigs(devkit_commands, viewport, toolbar, settings)
    controller_configs.setup()
    delete_title = DeleteTitle(devkit_commands, viewport, toolbar, settings)
    delete_title.setup()
    list_titles = ListTitles(devkit_commands, viewport, toolbar, settings)
    list_titles.setup()
    restart_session = RestartSession(devkit_commands, viewport, toolbar, settings)
    restart_session.setup()
    browse_files = BrowseFiles(devkit_commands, viewport, toolbar, settings)
    browse_files.setup()
    change_password = ChangePassword(devkit_commands, viewport, toolbar, settings)
    change_password.setup()
    cef_console = CEFConsole(devkit_commands, viewport, toolbar, settings)
    cef_console.setup()

    devkits_window = DevkitsWindow(
        conf,
        devkit_commands,
        settings,
        screenshot,
        perf_overlay,
        gpu_trace,
        rgp_capture,
        renderdoc_capture,
        proton_logs,
        controller_configs,
        delete_title,
        shutdown_signal,
        viewport,
        toolbar
    )
    devkits_window.setup()
    # DevkitsWindow emits this signal in various places, it makes sense to connect and process the common work locally
    devkits_window.signal_selected_devkit.connect(devkits_window.on_selected_devkit)

    devkits_window.signal_selected_devkit.connect(perf_overlay.on_selected_devkit)

    client_api = ClientAPI(devkits_window)
    client_api.setup()

    console_window = ConsoleWindow(conf, console_handler, settings, viewport, toolbar)
    console_window.setup()
    refresh_status = RefreshStatus(devkit_commands, devkits_window, viewport, toolbar)
    refresh_status.setup()
    update_title = UpdateTitle(devkit_commands, devkits_window, settings, False, client_api, viewport, toolbar)
    update_title.setup()
    view_steam_logs = DeviceLogs(devkit_commands, devkits_window, settings, viewport, toolbar)
    view_steam_logs.setup()
    remote_shell = RemoteShell(devkit_commands, devkits_window, toolbar)
    remote_shell.setup()

    viewport.main()
    shutdown_signal.emit()
