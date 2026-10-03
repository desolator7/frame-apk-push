# -*- coding: utf-8 -*-

#MIT License
#
#Copyright (c) 2017-2022 Valve Software inc., Collabora Ltd
#
#Permission is hereby granted, free of charge, to any person obtaining a copy
#of this software and associated documentation files (the "Software"), to deal
#in the Software without restriction, including without limitation the rights
#to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#copies of the Software, and to permit persons to whom the Software is
#furnished to do so, subject to the following conditions:
#
#The above copyright notice and this permission notice shall be included in all
#copies or substantial portions of the Software.
#
#THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
#SOFTWARE.

# Creates exe of python script and puts dependent modules in lib folder
# run from the virtualenv, top level:
# C:\steamos-devkit> python .\setup\cxfreeze-windows.py build

import sys
import os
import tomllib
from cx_Freeze import setup, Executable

assert sys.platform == 'win32'

# Map from PyPI package names to Python module names
# Only needed when they differ
module_map = {
    'pywin32': 'win32api',
    'pysdl2': 'sdl2',
    'pysdl2-dll': 'sdl2dll',
    'pyopengl': 'OpenGL',
    'pynacl': 'nacl',
    'netifaces-plus': 'netifaces',
    'cx-freeze': None, # skip
}

# Parse pyproject.toml to get dependencies
with open('pyproject.toml', 'rb') as f:
    pyproject = tomllib.load(f)

modules = []
for dep in pyproject['project']['dependencies']:
    # Skip platform-specific packages (Windows-only packages like cx-freeze, pywin32)
    if 'sys_platform' in dep:
        # Check if this is a Windows-specific package
        # Handle both single and double quotes, with flexible whitespace
        import re
        if re.search(r"sys_platform\s*==\s*['\"]win32['\"]", dep):
            # Extract package name before the semicolon (platform condition)
            pkg = dep.split(';')[0].strip()
        else:
            # Skip non-Windows platform packages (e.g., linux-only packages)
            continue
    else:
        pkg = dep

    # Handle git dependencies (e.g., imgui)
    if '@' in pkg and 'git+' in pkg:
        # Extract package name from "pkgname[extras] @ git+url"
        pkg = pkg.split('@')[0].strip()

    # Remove version constraints and extras
    pkg = pkg.split('[')[0].split('>')[0].split('<')[0].split('=')[0].split('!')[0].strip()

    # Skip comment lines or empty strings
    if not pkg or pkg.startswith('#'):
        continue

    # Apply module name mapping
    if pkg in module_map:
        module_name = module_map[pkg]
        if module_name is not None:
            modules.append(module_name)
    else:
        modules.append(pkg)

print(f'modules: {modules!r}')

build_exe_options = {
    'packages': modules, # this actually takes a list of module names
     # TEMP - we need tkinter for the Windows file dialog workaround, remove again when we have a better solution
    #'excludes': ['tkinter'],
    'excludes': [],
    'path': ['client'] + sys.path,
    # Add vcredist dlls
    'include_msvcr': True,
}

# cx_Freeze 8.x uses 'gui' instead of 'Win32GUI'
base = 'gui'

setup(
    name='steamos-devkit',
    description='SteamOS Devkit Client',
    options={'build_exe': build_exe_options},
    executables=[
        Executable('client/devkit-gui.py', base=base),
    ],
    package_dir={'': 'client'},
)
