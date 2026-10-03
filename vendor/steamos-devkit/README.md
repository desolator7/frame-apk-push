
# Windows development: one time system configuration

Please adapt these instructions to your setup. The steps outlined here were tested to work.

Install [Chocolatey](https://chocolatey.org)

In an Administrator command prompt:

Install misc utilities:

- `choco install 7zip`

Install Python 3.14:

- `choco install python --version 3.14.0 --params "/qn /norestart ALLUSERS=1 TARGETDIR=c:\Python314"`

Python will install to C:\Python314 for all users.

Restart the Administrator command prompt to pick up the new python.

Install uv (Python package manager):

- `choco install uv`

Restart the Administrator command prompt to pick up the new uv installation.

Install the Microsoft Visual C++ compiler, per https://wiki.python.org/moin/WindowsCompilers:

- `choco install visualstudio2022community`

Then run 'Visual Studio Installer' from the Start menu, and enable the 'Python development' workload, plus the 'Python native development tools' option. See [the pyhon wiki](https://wiki.python.org/moin/WindowsCompilers#Microsoft_Visual_C.2B-.2B-_14.x_with_Visual_Studio_2022_.28x86.2C_x64.2C_ARM.2C_ARM64.29) for more details.

Install cygwin with needed packages:

- `choco install cygwin --params "/InstallDir:C:\cygwin64"`
- `choco install rsync openssh --source=cygwin`

# Windows development: python virtualenv setup

Next, prepare a python virtualenv with all the necessary dependencies. This step needs to be repeated in every fresh clone of the repository.

Open a Visual Studio Developer command prompt in the steamos-devkit folder and run the following:

- Set up the environment: `uv sync --python 3.14`
- Activate: `.\.venv\Scripts\activate.bat`

    If you get an `UnauthorizedAccess` error due to [execution policies](https://docs.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_execution_policies), run the following command first: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process`

You are ready for development. The application can be started by running `python .\client\devkit-gui.py`.

# Windows packaging:

Ensure you have set up the environment with `uv sync` first.

From the activated virtual env:

- `python .\setup\package-windows.py`

# Linux development:

We support Python 3.11 through 3.14. A system with Python 3.14 is recommended (Arch and derivatives, or Ubuntu 24 or newer)

Install uv if you don't have it:
- `curl -LsSf https://astral.sh/uv/install.sh | sh`

Then set up the environment:
- `uv sync`
- `source .venv/bin/activate`
- `cd client`
- `./devkit-gui.py`

# Linux packaging for distribution:

## One time setup:

From a blank Ubuntu 20.04 (focal) - via VM, toolbox, podman, docker etc.:

Installing 3.11, 3.12, 3.13, and 3.14 backports from https://launchpad.net/~deadsnakes/+archive/ubuntu/ppa

As root:

```text
$ add-apt-repository ppa:deadsnakes/ppa
$ apt update
$ apt upgrade
$ apt install gcc g++ python3.11 python3.11-dev python3.11-distutils python3.12 python3.12-dev python3.12-distutils python3.13 python3.13-dev python3.14 python3.14-dev
```

Install uv for each Python version:

As user:

```text
$ curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Package:

- Fresh git clone
- `uv sync --python 3.11`  # or 3.12, 3.13
- `source .venv/bin/activate`
- `./setup/package-linux.py`

Repeat for Python 3.11, 3.12, 3.13, 3.14 etc.
