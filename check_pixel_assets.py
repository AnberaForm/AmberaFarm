# -*- coding: utf-8 -*-
"""Validate installed art and print the actual missing paths before the CI build."""
import argparse
import os
from pathlib import Path
import sys

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=PROJECT)
    args = parser.parse_args()
    import pygame
    from pixel_art import PixelArt
    pygame.display.init()
    pygame.display.set_mode((1, 1))
    try:
        art = PixelArt(args.root)
        print(art.diagnostics())
        if not art.complete():
            print('FAILED: keep the required art check enabled and repair the files listed above.')
            return 1
        print('Pixel-art asset check passed.')
        return 0
    finally:
        pygame.quit()


if __name__ == '__main__':
    raise SystemExit(main())
