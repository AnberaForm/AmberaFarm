# -*- coding: utf-8 -*-
"""Generated PNG maps and sprite atlases; nearest-neighbor display only."""
from pathlib import Path
import pygame
from asset_layout import restore_pixel_assets
from scene_maps import MAPS

PROPS = ('tree', 'fountain', 'quest_board', 'carriage',
         'plant', 'rug', 'table', 'lamp',
         'bench', 'mailbox', 'crate', 'sign',
         'bed', 'chest', 'tools', 'fish_crate')
FISH_IDS = ('medaka', 'funa', 'ayu', 'koi', 'unagi', 'masu', 'king_salmon', 'gold_koi')
PROP_REGIONS = ((25,52,284,320), (345,105,286,260), (649,79,257,266), (929,114,309,242),
                (53,401,235,250), (327,465,311,170), (665,435,260,209), (1013,403,164,247),
                (36,717,322,196), (429,664,148,257), (677,689,249,243), (1027,662,199,259),
                (48,930,257,279), (364,991,249,192), (671,986,279,215), (975,968,248,240))


class PixelArt:
    def __init__(self, root):
        self.project_root = Path(root)
        self.restored_assets = restore_pixel_assets(self.project_root)
        root = self.project_root/'assets'
        self.maps = {}
        self.room_views = {}
        self.sprites = {}
        self.scaled = {}
        self.asset_errors = {}
        self.sprite_errors = {}
        for spec in MAPS.values():
            if spec.asset in self.maps: continue
            path = root/'scenes'/(spec.asset+'.png')
            raw = self.load_image(path, alpha=False)
            if raw is not None:
                self.maps[spec.asset] = pygame.transform.scale(raw, spec.size)
                if spec.size == (1280, 768):
                    self.room_views[spec.asset] = pygame.transform.scale(self.maps[spec.asset], (960, 576))
        for name, columns, rows, keys in (('props', 4, 4, PROPS), ('fish', 4, 2, FISH_IDS)):
            path = root/'scenery'/(name+'.png')
            sheet = self.load_image(path, alpha=True)
            if sheet is None: continue
            for index, key in enumerate(keys):
                column, row = index%columns, index//columns
                if name == 'props':
                    # Generated objects use unequal row spacing; preserve entire
                    # tree trunks, lamps and bed feet instead of clipping a grid.
                    x, y, width, height = PROP_REGIONS[index]
                    left, right = round(x/1254*sheet.get_width()), round((x+width)/1254*sheet.get_width())
                    top, bottom = round(y/1254*sheet.get_height()), round((y+height)/1254*sheet.get_height())
                else:
                    left, right = round(column*sheet.get_width()/columns), round((column+1)*sheet.get_width()/columns)
                    top, bottom = round(row*sheet.get_height()/rows), round((row+1)*sheet.get_height()/rows)
                if right<=left or bottom<=top:
                    self.sprite_errors[key] = f'assets/scenery/{name}.png: sprite region is empty or too small'
                    continue
                sprite = sheet.subsurface((left, top, right-left, bottom-top)).copy()
                bounds = sprite.get_bounding_rect(min_alpha=128)
                if bounds.width and bounds.height:
                    self.sprites[key] = sprite.subsurface(bounds).copy()
                else:
                    self.sprite_errors[key] = f'assets/scenery/{name}.png: sprite region is fully transparent'

    def load_image(self, path, alpha):
        relative = path.relative_to(self.project_root).as_posix()
        if not path.is_file():
            self.asset_errors[relative] = 'missing file'
            return None
        try:
            raw = pygame.image.load(str(path))
            return raw.convert_alpha() if alpha else raw.convert()
        except (OSError, pygame.error) as error:
            self.asset_errors[relative] = 'could not decode image: '+str(error)
            return None

    def diagnostics(self):
        expected = len({spec.asset for spec in MAPS.values()})
        lines = [f'Pixel-art assets: backgrounds {len(self.maps)}/{expected}, '
                 f'sprites {len(self.sprites)}/{len(PROPS)+len(FISH_IDS)}']
        if self.restored_assets:
            lines.append(f'Recovered {len(self.restored_assets)} flattened image uploads into assets/scenes and assets/scenery.')
        for relative, reason in sorted(self.asset_errors.items()):
            lines.append(f'  {relative}: {reason}')
            # Point out common upload layouts without accepting wrong paths.
            path = Path(relative)
            for alternative in (self.project_root/'assets'/path,
                                self.project_root/'assets'/path.name,
                                self.project_root/path.name):
                if alternative.is_file():
                    actual = alternative.relative_to(self.project_root).as_posix()
                    lines.append(f'    Found at {actual}; move it to {relative}')
        for key, reason in sorted(self.sprite_errors.items()):
            lines.append(f'  Sprite {key}: {reason}')
        if not self.complete():
            lines.append('Upload assets/scenes/*.png and assets/scenery/{props,fish}.png '
                         'to the repository root with those exact folder names.')
        return '\n'.join(lines)

    def require_complete(self):
        if not self.complete():
            raise RuntimeError('Pixel-art asset check failed:\n'+self.diagnostics())

    def sprite(self, key, size):
        cache_key = key, tuple(size)
        if cache_key not in self.scaled:
            raw = self.sprites.get(key)
            if raw is None: return None
            scale = min(size[0]/raw.get_width(), size[1]/raw.get_height())
            self.scaled[cache_key] = pygame.transform.scale(raw, (max(1, round(raw.get_width()*scale)),
                                                                  max(1, round(raw.get_height()*scale))))
        return self.scaled[cache_key]

    def draw(self, target, key, rect):
        rect = pygame.Rect(rect)
        sprite = self.sprite(key, rect.size)
        if sprite is None: return False
        target.blit(sprite, sprite.get_rect(center=rect.center))
        return True

    def complete(self):
        return (not self.asset_errors and not self.sprite_errors
                and len(self.maps) == len({spec.asset for spec in MAPS.values()})
                and all(key in self.sprites for key in (*PROPS, *FISH_IDS)))
