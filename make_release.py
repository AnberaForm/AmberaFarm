# -*- coding: utf-8 -*-
"""Release utility (maintainer use): builds restricted update ZIP and HTTPS manifest.
Never includes users' saves, passwords or update_config.json.
"""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path
from updater import ALLOWED,current_version,version_parts

ROOT=Path(__file__).resolve().parent

def make(package_url,destination=None):
    from updater import _url
    _url(package_url)
    version=current_version();version_parts(version)
    destination=Path(destination or ROOT/'release');destination.mkdir(parents=True,exist_ok=True)
    filename='AmberaFarm_update_'+version.replace('.','_')+'.zip'
    package=destination/filename
    with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED,compresslevel=8) as z:
        for name in sorted(ALLOWED):
            f=ROOT/name
            if f.is_file():z.write(f,name)
    digest=hashlib.sha256(package.read_bytes()).hexdigest()
    manifest={'version':version,'package_url':package_url,'sha256':digest,
              'notes':'Ambera Farm v'+version+' update'}
    (destination/'update_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return package,manifest

if __name__=='__main__':
    a=argparse.ArgumentParser()
    a.add_argument('--package-url',required=True,help='Final https URL of the update ZIP')
    a.add_argument('--output',default='release')
    args=a.parse_args()
    file,manifest=make(args.package_url,ROOT/args.output)
    print('Built:',file,'\nSHA256:',manifest['sha256'])
