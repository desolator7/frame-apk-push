#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import subprocess
import tempfile
import shutil
import glob

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ARTIFACTS_DIR = os.path.join(ROOT_DIR, 'artifacts')

assert sys.platform == 'linux'
assert sys.prefix == sys.base_prefix    # executed at build VM OS level


# don't let python buffering get in the way or readable output
# https://stackoverflow.com/questions/107705/disable-output-buffering
class Unbuffered(object):
   def __init__(self, stream):
       self.stream = stream
   def write(self, data):
       self.stream.write(data)
       self.stream.flush()
   def writelines(self, datas):
       self.stream.writelines(datas)
       self.stream.flush()
   def __getattr__(self, attr):
       return getattr(self.stream, attr)


def call(cmd, cwd):
    print(f'BEGIN CMD: {cmd}')
    subprocess.check_call(cmd, cwd=cwd, shell=True, stderr=subprocess.STDOUT)
    print(f'END CMD: {cmd}')


if __name__ == '__main__':
    sys.stdout = Unbuffered(sys.stdout)
    sys.stderr = Unbuffered(sys.stderr)

    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    for python_minor in (11, 12, 13, 14):
        build_dir = os.path.abspath(os.path.join(ROOT_DIR, f'../steamos-devkit-py3{python_minor}'))
        interpreter = f'python3.{python_minor}'
        # Clean up old build directory to ensure reproducible builds
        if os.path.exists(build_dir):
            venv_dir = os.path.join(build_dir, '.venv')
            if os.path.exists(venv_dir):
                print(f'rmtree {venv_dir}')
                shutil.rmtree(venv_dir)
            print(f'rmtree {build_dir}')
            shutil.rmtree(build_dir)
        print(f'copytree {ROOT_DIR} -> {build_dir}')
        shutil.copytree(ROOT_DIR, build_dir)
        # Update pyproject.toml to target specific Python version
        pyproject_path = os.path.join(build_dir, 'pyproject.toml')
        with open(pyproject_path, 'r') as f:
            content = f.read()
        content = content.replace('requires-python = ">=3.11"', f'requires-python = ">=3.{python_minor},<3.{python_minor + 1}"')
        with open(pyproject_path, 'w') as f:
            f.write(content)
        # Use uv to sync dependencies for the target Python version
        call(f'uv sync --python {interpreter}', build_dir)
        # Activate venv and run packaging script
        venv_python = os.path.join(build_dir, '.venv', 'bin', 'python')
        call(f'{venv_python} ./setup/package-linux.py', build_dir)
        g = glob.glob(f'{build_dir}/devkit-gui*.pyz')
        if len(g) != 1:
            raise Exception('No .pyz build artifact produced? Aborting')
        artifact = g[0]
        print(f'copy {artifact} -> {ARTIFACTS_DIR}')
        shutil.copyfile(artifact, os.path.join(ARTIFACTS_DIR, os.path.basename(artifact)))

