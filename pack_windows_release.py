# -*- coding: utf-8 -*-
"""Produces distribution ZIP + self-update ZIP + manifest from built Windows EXEs.

Launch bundle user gets ONCE, later only game EXEs are updated from GitHub Releases.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile
from exe_launcher import parse_version

BASE = Path(__file__).resolve().parent


def pack(exe_folder: Path, output: Path, repo: str, version: str):
    parse_version(version)
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('GitHub repository must be owner/name')
    exe_folder = Path(exe_folder)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    exes = {name: (exe_folder / name).read_bytes() for name in (
        'AmberaFarm.exe', 'AmberaGame.exe', 'AmberaStoryEditor.exe')}
    version_bytes = (json.dumps({'version': version}) + '\n').encode('utf-8')
    payload_name = 'AmberaFarm_payload_v' + version + '.zip'
    payload = output / payload_name
    with zipfile.ZipFile(payload, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=8) as z:
        z.writestr('app/AmberaGame.exe', exes['AmberaGame.exe'])
        # Existing v0.7 launchers require this legacy file in updates.
        z.writestr('app/AmberaStoryEditor.exe', exes['AmberaStoryEditor.exe'])
        z.writestr('version.json', version_bytes)
    with payload.open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    manifest_url = f'https://github.com/{repo}/releases/latest/download/update_manifest.json'
    package_url = f'https://github.com/{repo}/releases/download/v{version}/{payload_name}'
    manifest = {'version': version, 'package_url': package_url, 'sha256': digest,
                'notes': 'Ambera Farm Windows v' + version}
    (output / 'update_manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    config = {'auto_update': True, 'manifest_url': manifest_url}
    install = output / ('AmberaFarm_Windows_v' + version + '.zip')
    with zipfile.ZipFile(install, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=8) as z:
        z.writestr('AmberaFarm.exe', exes['AmberaFarm.exe'])
        z.writestr('app/AmberaGame.exe', exes['AmberaGame.exe'])
        z.writestr('version.json', version_bytes)
        z.writestr('update_config.json', json.dumps(config, indent=2) + '\n')
        z.writestr('START_HERE.txt', (
            'AMBERA FARM - WINDOWS\r\n\r\n'
            '1. Extract the WHOLE ZIP into a writable folder (for example Desktop/AmberaFarm).\r\n'
            '2. Double click AmberaFarm.exe (NOT app/AmberaGame.exe).\r\n'
            '3. The launcher checks for updates on every start, then starts the game.\r\n'
            '4. Admin editor is separate; it is not distributed to players.\r\n'
            '5. Save data: %%APPDATA%%\\AmberaFarm\\save.json.\r\n'
            '6. Game works offline. Failed updates do not block offline play.\r\n'
            'Online co-op remains direct IP/LAN (no public matchmaking).\r\n'
            f'Build: v{version}\r\n').encode('ascii'))
    return install, payload, output / 'update_manifest.json'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', required=True, help='public GitHub owner/repository')
    parser.add_argument('--version', required=True)
    parser.add_argument('--exe-dir', default=str(BASE / 'build_output' / 'exe'))
    parser.add_argument('--output', default=str(BASE / 'build_output' / 'release'))
    args = parser.parse_args()
    if json.loads((BASE / 'version.json').read_text(encoding='utf-8'))['version'] != args.version:
        parser.error('Version must match version.json')
    for file in pack(Path(args.exe_dir), Path(args.output), args.repo, args.version):
        print('CREATED', file)
