"""Build/install a wheel into an isolated venv; exercise bundled runtime assets."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv
from accept_clean_home import clean_env

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix='contextcanon-install-') as tmp:
        base = Path(tmp)
        scripts = base / 'venv' / ('Scripts' if os.name == 'nt' else 'bin')
        python = scripts / ('python.exe' if os.name == 'nt' else 'python')
        cli = scripts / ('contextcanon.exe' if os.name == 'nt' else 'contextcanon')
        env = clean_env(str(base / 'home'))
        Path(env['HOME']).mkdir()
        env.update(PIP_CACHE_DIR=str(base / 'pip-cache'), PIP_DISABLE_PIP_VERSION_CHECK='1')
        subprocess.run([sys.executable, '-m', 'venv', str(base / 'venv')], env=env, cwd=base, check=True, timeout=120)
        subprocess.run([str(python), '-m', 'pip', 'install', '--no-cache-dir', '--disable-pip-version-check', str(ROOT)],
                       env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
        checks = []
        for args in (['--version'], ['doctor'], ['demo', 'seed', '--reset'],
                     ['profile', 'get', '--key', 'tooling.editor'], ['benchmark', 'smoke'], ['guard', 'plan']):
            proc = subprocess.run([str(cli)] + args, env=env, cwd=base, check=True,
                                  capture_output=True, text=True, encoding='utf-8', timeout=60)
            data = json.loads(proc.stdout)
            if args[0] == 'profile':
                assert data['fact']['value'] == 'zed'
            if args[0] == 'benchmark':
                assert data['contextcanon_score'] == data['cases']
            if args[0] == 'guard':
                assert data['outcome'] == 'planned'
            checks.append({'command': args, 'status': 'PASS'})
        print(json.dumps(checks, indent=2))


if __name__ == '__main__':
    main()
