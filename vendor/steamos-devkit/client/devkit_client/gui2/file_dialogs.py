import os
import sys
import subprocess
import logging

import xdialog

logger = logging.getLogger(__name__)


def browse_directory(title, current_path=''):
    try:
        result = xdialog.directory(title, initial_directory=current_path)
        return result if result else ''
    except Exception as e:
        logger.error(f'File dialog error: {e}')
        return ''


def browse_file(title, current_path='', filetypes=None):
    try:
        result = xdialog.open_file(title, filetypes=filetypes, initial_directory=current_path)
        return result if result else ''
    except Exception as e:
        logger.error(f'File dialog error: {e}')
        return ''


def open_folder(path):
    os.makedirs(path, exist_ok=True)
    if sys.platform == 'win32':
        os.startfile(path)
    else:
        subprocess.Popen(['xdg-open', path])
