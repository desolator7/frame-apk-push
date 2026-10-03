#!/usr/bin/env python3
"""Rebuild the bundled Android helpers without modifying the APK or Lepton."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
R8_VERSION = '9.4.28'
R8_SHA256 = '51af0a9d41cc541d619064224aec628923bd779cbcc5a62cb914ea2d669c4063'
R8_URL = f'https://dl.google.com/dl/android/maven2/com/android/tools/r8/{R8_VERSION}/r8-{R8_VERSION}.jar'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jdk-home', type=Path, help='JDK with java and javac (otherwise PATH)')
    parser.add_argument('--r8-jar', type=Path, required=True, help=R8_URL)
    args = parser.parse_args()
    if digest(args.r8_jar) != R8_SHA256:
        parser.error('R8 hash differs from the pinned build tool')
    clang = shutil.which('clang')
    java = str(args.jdk_home / 'bin/java') if args.jdk_home else shutil.which('java')
    javac = str(args.jdk_home / 'bin/javac') if args.jdk_home else shutil.which('javac')
    if not all((clang, java, javac, shutil.which('ld.lld'))):
        parser.error('clang, ld.lld and a JDK are required')
    with tempfile.TemporaryDirectory(prefix='frame-native-') as directory:
        work = Path(directory)
        library = work / 'libframe-zygote.so'
        subprocess.run([clang, '--target=aarch64-linux-android30', '-fuse-ld=lld',
                        '-shared', '-nostdlib', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-fPIC', '-fno-stack-protector', '-Wl,-soname,libframe-zygote.so',
                        '-Wl,-z,relro,-z,now', '-Wl,--hash-style=both',
                        str(ROOT / 'native/frame_zygote.c'), '-o', str(library)], check=True)
        subprocess.run([javac, '--release', '8', '-Xlint:-options', '-d', str(work),
                        str(ROOT / 'native/FrameRestrictions.java'),
                        str(ROOT / 'native/FrameBrowserPrefs.java'),
                        str(ROOT / 'native/FrameDevtools.java'),
                        str(ROOT / 'native/FrameBrowserXR.java')], check=True)
        classes = sorted(str(path) for path in work.glob('Frame*.class'))
        subprocess.run([java, '-cp', str(args.r8_jar.resolve()), 'com.android.tools.r8.D8',
                        '--release', '--min-api', '30', '--output', str(work), *classes], check=True)
        jar = work / 'frame-services.jar'
        with zipfile.ZipFile(jar, 'w') as archive:
            info = zipfile.ZipInfo('classes.dex', date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, (work / 'classes.dex').read_bytes())
        for path in (library, jar):
            shutil.copyfile(path, ROOT / 'assets' / path.name)
            (ROOT / 'assets' / path.name).chmod(0o644)
    files = ('native/frame_zygote.c', 'native/FrameRestrictions.java', 'native/FrameBrowserPrefs.java',
             'native/FrameDevtools.java', 'native/FrameBrowserXR.java',
             'assets/libframe-zygote.so', 'assets/frame-services.jar')
    manifest = {'target': 'Android 11 / API 30 / AArch64',
                'clang': subprocess.check_output([clang, '--version'], text=True).splitlines()[0],
                'r8': {'version': R8_VERSION, 'source': R8_URL, 'sha256': R8_SHA256},
                'files': {name: digest(ROOT / name) for name in files}}
    (ROOT / 'native/build-info.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
