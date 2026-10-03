"""Exercise the compatibility library against an emulated Lepton libc."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from frame_apk_push.core import ROOT


@pytest.fixture(scope='module')
def identity_probe(tmp_path_factory):
    cc = shutil.which('clang') or shutil.which('gcc')
    if not cc:
        pytest.skip('C compiler required for native identity tests')
    path = tmp_path_factory.mktemp('native')
    (path / 'fake.c').write_text(r'''
#include <stdlib.h>
#include <errno.h>
#include <unistd.h>
static unsigned uid = 10012, gid = 10012;
const char *getprogname(void) { return getenv("PROBE_NAME"); }
int *__errno(void) { return &errno; }
uid_t getuid(void) { return uid; }
gid_t getgid(void) { return gid; }
int setuid(uid_t u) { if (uid >= 10000) return -1; uid=u; return 0; }
int setgid(gid_t g) { if (gid >= 10000) return -1; gid=g; return 0; }
''')
    (path / 'probe.c').write_text(r'''
#define _GNU_SOURCE
#include <unistd.h>
#include <assert.h>
#include <stdlib.h>
#include <sys/wait.h>
int main(int argc, char **argv) {
    assert(getuid() == 10012 && getgid() == 10012);
    if (argc > 1) {
        assert(setresgid(90000,90000,90000) == -1);
        assert(getgid() == 10012); return 0;
    }
    assert(setuid(90000) == -1); /* gid must transition first */
    assert(setgid(20000) == -1); /* only isolated IDs */
    pid_t child = fork(); assert(child >= 0);
    if (child == 0) {
        assert(setresgid(90000,90000,90000) == 0);
        assert(setresuid(90000,90000,90000) == 0);
        assert(getuid() == 90000 && geteuid() == 90000);
        assert(getgid() == 90000 && getegid() == 90000);
        uid_t r,e,s; gid_t gr,ge,gs;
        assert(getresuid(&r,&e,&s) == 0 && r == 90000 && e == 90000 && s == 90000);
        assert(getresgid(&gr,&ge,&gs) == 0 && gr == 90000 && ge == 90000 && gs == 90000);
        assert(setuid(1000) == -1 && setgid(1000) == -1);
        assert(setuid(90001) == -1 && setgid(90001) == -1);
        assert(setuid(90000) == 0 && setgid(90000) == 0);
        _exit(0);
    }
    int status; waitpid(child, &status, 0);
    assert(WIFEXITED(status) && WEXITSTATUS(status) == 0);
    assert(getuid() == 10012 && getgid() == 10012); /* parent untouched */
    return 0;
}
''')
    for args in (
        ['-shared', '-fPIC', str(path / 'fake.c'), '-o', str(path / 'fake.so')],
        ['-shared', '-fPIC', str(ROOT / 'native/frame_zygote.c'), '-o', str(path / 'shim.so')],
        [str(path / 'probe.c'), '-o', str(path / 'probe')],
    ):
        subprocess.run([cc, *args], check=True, capture_output=True)
    return path


@pytest.mark.parametrize('name', ['org.chromium.chrome_zygote', 'com.android.chrome_zygote'])
def test_zygote_child_can_transition_once_and_cannot_escape(identity_probe, name):
    path = identity_probe
    env = {**os.environ, 'LD_PRELOAD': f'{path}/shim.so:{path}/fake.so',
           'PROBE_NAME': name}
    result = subprocess.run([str(path / 'probe')], env=env, capture_output=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('name', ['org.chromium.chrome', 'other.chrome_zygote',
                                 'org.chromium.chrome_zygote_extra', 'org.chromium.chrome_zygotx',
                                 'com.android.chrome', 'com.android.chrome_zygote_extra',
                                 'other.com.android.chrome_zygote'])
def test_regular_app_cannot_use_zygote_transition(identity_probe, name):
    path = identity_probe
    env = {**os.environ, 'LD_PRELOAD': f'{path}/shim.so:{path}/fake.so',
           'PROBE_NAME': name}
    result = subprocess.run([str(path / 'probe'), 'regular'], env=env, capture_output=True)
    assert result.returncode == 0, result.stderr
