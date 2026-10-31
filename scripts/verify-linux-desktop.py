#!/usr/bin/env python3
"""Open the actual published GUI as the ordinary CI user under Xvfb."""
import os, pathlib, subprocess, tempfile, time

assert os.geteuid() != 0, 'The GUI test must run as an ordinary desktop user'
assert pathlib.Path('dist/DicodePing-4.9.92-linux-x64.deb').is_file()
with tempfile.TemporaryDirectory(prefix='dicode-desktop-launch-') as temp:
    env = os.environ.copy(); env['DICODE_DATA_DIR'] = temp
    with open(pathlib.Path(temp) / 'gui.log', 'w+') as output:
        process = subprocess.Popen(['xvfb-run', '-a', str(pathlib.Path('publish/DicodePing').resolve())], env=env, stdout=output, stderr=output, start_new_session=True)
        try:
            time.sleep(8)
            output.seek(0); log = output.read()
            assert process.poll() is None, 'GUI exited before opening: ' + log
            assert pathlib.Path(temp, 'guiConfigs/DicodePingConfig.json').is_file(), 'GUI did not initialize its writable user data'
            assert 'must be launched with administrator' not in log
            print('PASS published Linux GUI opens as an ordinary user with writable user data')
        finally:
            import signal
            os.killpg(process.pid, signal.SIGTERM)
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: os.killpg(process.pid, signal.SIGKILL); process.wait()
