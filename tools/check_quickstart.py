"""Execute the actual documented shell blocks with fresh HOME and synthetic paths."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from accept_clean_home import clean_env


def main():
    blocks = dict(re.findall(r'```(powershell|cmd|bash|sh)\n(.*?)```',
                            (ROOT / 'docs/quickstart/local.md').read_text(encoding='utf-8'), re.S))
    if os.name == 'nt':
        git = Path(shutil.which('git') or '')
        bash = git.parent.parent / 'bin/bash.exe'
        shells = {'powershell': [shutil.which('powershell'), '-NoProfile', '-Command'],
                  'cmd': [os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c'],
                  'bash': [str(bash) if bash.exists() else None, '-c']}
    else:
        shells = {'sh': [shutil.which('bash'), '-c']}
    results = []
    for name, shell in shells.items():
        if not shell[0]:
            results.append({'shell': name, 'status': 'SKIP', 'reason': 'shell not installed'})
            continue
        with tempfile.TemporaryDirectory(prefix='contextcanon-quickstart-') as tmp:
            env = clean_env(tmp)
            env.update(WXT_CONTEXTCANON_PROFILE_DATABASE=str(Path(tmp) / 'profile.db'),
                       WXT_CONTEXTCANON_PROFILE_DATA_DIR=tmp,
                       WXT_CONTEXTCANON_REGISTRY_HOME=str(Path(tmp) / 'registry'),
                       WXT_CONTEXTCANON_REGISTRY_SHARED_STORE=str(Path(tmp) / 'registry/shared.db'))
            payloads = []
            for command in blocks[name].strip().splitlines():
                proc = subprocess.run(shell + [command], cwd=ROOT, env=env,
                                      capture_output=True, text=True, encoding='utf-8', timeout=60)
                if proc.returncode:
                    raise RuntimeError('%s command failed: %s\n%s' % (name, command, proc.stderr))
                payloads.append(json.loads(proc.stdout))
            assert payloads[0]['ok'] is True
            assert payloads[1]['synthetic'] is True
            assert payloads[2]['fact']['value'] == 'zed'
            assert payloads[3]['fact']['value'] == 42
            assert [f['value'] for f in payloads[4]['facts']] == ['vscode', 'zed']
            assert next(f for f in payloads[5]['facts'] if f['key'] == 'tooling.editor')['value'] == 'vscode'
            assert payloads[6]['idempotent'] is True
            assert payloads[7]['contextcanon_score'] == payloads[7]['cases'] == 7
            assert payloads[8]['outcome'] == 'planned'
            results.append({'shell': name, 'status': 'PASS', 'commands': len(payloads)})
    print(json.dumps(results, indent=2))
    return 0 if all(r['status'] == 'PASS' for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
