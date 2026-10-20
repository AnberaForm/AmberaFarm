"""Fail CI instead of publishing a release with inconsistent versions."""
import argparse
import json
from pathlib import Path
from exe_launcher import parse_version


def verify(tag):
    expected = json.loads((Path(__file__).parent / 'version.json').read_text(encoding='utf-8'))['version']
    parse_version(expected)
    if tag != 'v' + expected:
        raise SystemExit(f'Tag mismatch: expected v{expected}, got {tag}')
    print('Release tag verified:', tag)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--tag', required=True)
    verify(parser.parse_args().tag)
