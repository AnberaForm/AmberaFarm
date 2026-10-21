"""Reproduce the Actions failure and verify a useful failure, rather than skipping it."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def display(monkeypatch):
    monkeypatch.setenv('SDL_VIDEODRIVER','dummy')
    monkeypatch.setenv('SDL_AUDIODRIVER','dummy')
    import pygame
    pygame.display.init();pygame.display.set_mode((1,1))
    yield
    pygame.quit()


def copy_art(destination):
    for directory in ('scenes','scenery'):
        shutil.copytree(ROOT/'assets'/directory,destination/'assets'/directory)


@pytest.mark.parametrize('relative',('assets/scenes/home.png','assets/scenery/props.png','assets/scenery/fish.png'))
def test_missing_png_fails_with_its_actual_path(tmp_path,display,relative):
    from pixel_art import PixelArt
    copy_art(tmp_path)
    (tmp_path/relative).unlink()
    art=PixelArt(tmp_path)
    assert not art.complete()
    with pytest.raises(RuntimeError,match=relative):art.require_complete()
    assert relative+': missing file' in art.diagnostics()


def test_nested_upload_reports_the_wrong_and_correct_paths(tmp_path,display):
    from pixel_art import PixelArt
    copy_art(tmp_path/'assets')
    art=PixelArt(tmp_path)
    assert not art.complete()
    report=art.diagnostics()
    assert 'assets/scenes/home.png: missing file' in report
    assert 'Found at assets/assets/scenes/home.png; move it to assets/scenes/home.png' in report


def test_corrupt_png_is_reported_without_disabling_validation(tmp_path,display):
    from pixel_art import PixelArt
    copy_art(tmp_path)
    (tmp_path/'assets/scenery/props.png').write_bytes(b'broken PNG upload')
    art=PixelArt(tmp_path)
    assert not art.complete()
    assert 'assets/scenery/props.png: could not decode image' in art.diagnostics()


def test_transparent_atlas_reports_its_source_file_and_missing_sprites(tmp_path,display):
    import pygame
    from pixel_art import PixelArt
    copy_art(tmp_path)
    image=pygame.Surface((1254,1254),pygame.SRCALPHA)
    pygame.image.save(image,str(tmp_path/'assets/scenery/props.png'))
    art=PixelArt(tmp_path)
    assert not art.complete()
    assert 'assets/scenery/props.png: sprite region is fully transparent' in art.diagnostics()


def test_cli_returns_failure_and_paths_when_upload_is_incomplete(tmp_path):
    environment=dict(os.environ,SDL_VIDEODRIVER='dummy',SDL_AUDIODRIVER='dummy')
    result=subprocess.run([sys.executable,str(ROOT/'tools/check_pixel_assets.py'),'--root',str(tmp_path)],
                          capture_output=True,text=True,env=environment)
    assert result.returncode==1
    assert 'backgrounds 0/10, sprites 0/24' in result.stdout
    assert 'assets/scenes/home.png: missing file' in result.stdout
    assert 'assets/scenery/props.png: missing file' in result.stdout
