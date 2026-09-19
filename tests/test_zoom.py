import base64
from contextlib import redirect_stdout
import hashlib
import hmac
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from sparkie.zoom_config import meeting_config, private_write, sdk_path, selected_platform
from sparkie.primitive import doctor
from sparkie import zoom_macos

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('zoom_sanity', ROOT / 'scripts/zoom-sanity.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
ENV = {'ZOOM_CLIENT_ID': 'client-test', 'ZOOM_CLIENT_SECRET': 'secret-test',
       'ZOOM_MEETING_ID': '123 4567-8901', 'ZOOM_MEETING_PASSWORD': '001234'}


class ZoomConfigTests(unittest.TestCase):
    def test_jwt_signature_and_normalized_meeting_number(self):
        config = meeting_config(ENV, now=10000)
        self.assertEqual(config['meeting_number'], '12345678901')
        self.assertEqual(config['meeting_password'], '001234')
        header, payload, signature = config['token'].split('.')
        decoded = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
        self.assertEqual(decoded, {'appKey': 'client-test', 'iat': 9970, 'exp': 13570,
                                  'tokenExp': 13570, 'mn': '12345678901', 'role': 0})
        actual = base64.urlsafe_b64decode(signature + '=' * (-len(signature) % 4))
        self.assertEqual(actual, hmac.new(b'secret-test', f'{header}.{payload}'.encode(), hashlib.sha256).digest())

    def test_invalid_configuration_is_rejected_without_echoing_values(self):
        for value in ['https://zoom.us/j/12345678901', '１２３４５６７８９０１', '123']:
            with self.assertRaises(ValueError) as caught:
                meeting_config(dict(ENV, ZOOM_MEETING_ID=value))
            self.assertNotIn(value, str(caught.exception))
        with self.assertRaisesRegex(ValueError, 'Missing: ZOOM_CLIENT_SECRET'):
            meeting_config(dict(ENV, ZOOM_CLIENT_SECRET=''))

    def test_platform_defaults_and_sdk_override(self):
        self.assertEqual(selected_platform({}), 'linux')
        with self.assertRaises(ValueError):
            selected_platform({'ZOOM_PLATFORM': 'invalid'})
        env = {'ZOOM_SDK_PATH': '/linux', 'ZOOM_MACOS_SDK_PATH': '/mac'}
        self.assertEqual(sdk_path('linux', env), Path('/linux'))
        self.assertEqual(sdk_path('macos', env), Path('/mac'))
        self.assertEqual(sdk_path('macos', {'ZOOM_SDK_PATH': '/fallback'}), Path('/fallback'))

    def test_private_config_restricts_existing_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config'
            path.touch(mode=0o644)
            private_write(path, 'private')
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


class LinuxCompatibilityTests(unittest.TestCase):
    def test_existing_start_still_uses_pinned_image_and_receive_only_flags(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, ENV, clear=True), \
             patch.object(runner, 'ROOT', Path(directory)), patch.object(runner, 'docker') as docker, \
             patch.object(runner.subprocess, 'run', side_effect=[
                 subprocess.CompletedProcess([], 1, ''), subprocess.CompletedProcess([], 0)]), \
             redirect_stdout(io.StringIO()):
            runner.start()
            args = docker.call_args.args
            self.assertIn('sparkie-zoom-sanity:7.0.5', args)
            self.assertIn('linux/arm64', args)
            config = (Path(directory) / '.runtime/zoom-sanity/live-config.txt').read_text()
            self.assertIn('meeting_number: "12345678901"', config)
            self.assertIn('SendAudioRawData: "false"', config)
            self.assertIn('GetAudioRawData: "true"', config)
            self.assertNotIn('secret-test', config)

    def test_explicit_platform_overrides_environment(self):
        with patch.dict(os.environ, {'ZOOM_PLATFORM': 'macos'}), \
             patch.object(runner, 'load_dotenv'), patch.object(runner, 'start') as start, \
             patch('sys.argv', ['zoom-sanity.py', 'start', '--platform', 'linux']):
            runner.main()
            start.assert_called_once()


class MacLifecycleTests(unittest.TestCase):
    def test_stale_pid_never_signals_unrelated_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime, _, _ = zoom_macos.paths(root)
            private_write(runtime / 'receiver.pid', '4321')
            private_write(runtime / 'config.json', 'secret')
            with patch.object(zoom_macos.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '/unrelated/app\n')), \
                 patch.object(zoom_macos.os, 'kill') as kill, redirect_stdout(io.StringIO()):
                zoom_macos.stop(root)
                kill.assert_not_called()
            self.assertFalse((runtime / 'config.json').exists())

    def test_start_keeps_secrets_out_of_argv_and_child_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime, _, binary = zoom_macos.paths(root)
            binary.parent.mkdir(parents=True)
            binary.touch()
            with patch.dict(os.environ, dict(ENV, OPENAI_API_KEY='other-secret'), clear=True), \
                 patch.object(zoom_macos, 'running_pid', return_value=None), \
                 patch.object(zoom_macos.subprocess, 'Popen') as popen, redirect_stdout(io.StringIO()):
                popen.return_value.pid = 4321
                popen.return_value.wait.side_effect = subprocess.TimeoutExpired('probe', 1)
                zoom_macos.start(root)
                args, kwargs = popen.call_args
                self.assertEqual(args[0], [str(binary)])
                self.assertNotIn('ZOOM_CLIENT_SECRET', kwargs['env'])
                self.assertNotIn('OPENAI_API_KEY', kwargs['env'])
                config = json.loads((runtime / 'config.json').read_text())
                self.assertEqual(config['meeting_password'], '001234')
                self.assertNotIn('secret-test', (runtime / 'config.json').read_text())

    def test_macos_doctor_does_not_require_docker(self):
        env = dict(ENV, DEEPGRAM_API_KEY='test', DEEPGRAM_TTS_MODEL='test', ZOOM_PLATFORM='macos')
        with patch.dict(os.environ, env, clear=True), patch('sparkie.primitive.sdk_present', return_value=True), \
             patch('sparkie.primitive.platform.system', return_value='Darwin'), \
             patch('sparkie.primitive.shutil.which', return_value='/test'), \
             patch('sparkie.primitive.subprocess.run', return_value=subprocess.CompletedProcess([], 0)) as run, \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(doctor(), 0)
            self.assertNotIn('DOCKER', output.getvalue())
            self.assertEqual(run.call_args.args[0], ['xcodebuild', '-version'])


if __name__ == '__main__':
    unittest.main()
