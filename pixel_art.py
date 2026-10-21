# -*- coding: utf-8 -*-
"""Generated PNG maps and sprite atlases; nearest-neighbor display only."""
from pathlib import Path
import pygame
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
        root = Path(root)/'assets'
        self.maps = {}
        self.room_views = {}
        self.sprites = {}
        self.scaled = {}
        for spec in MAPS.values():
            if spec.asset in self.maps: continue
            path = root/'scenes'/(spec.asset+'.png')
            if path.is_file():
                raw = pygame.image.load(str(path)).convert()
                self.maps[spec.asset] = pygame.transform.scale(raw, spec.size)
                if spec.size == (1280, 768):
                    self.room_views[spec.asset] = pygame.transform.scale(self.maps[spec.asset], (960, 576))
        for name, columns, rows, keys in (('props', 4, 4, PROPS), ('fish', 4, 2, FISH_IDS)):
            path = root/'scenery'/(name+'.png')
            if not path.is_file(): continue
            sheet = pygame.image.load(str(path)).convert_alpha()
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
                sprite = sheet.subsurface((left, top, right-left, bottom-top)).copy()
                bounds = sprite.get_bounding_rect(min_alpha=128)
                if bounds.width and bounds.height:
                    self.sprites[key] = sprite.subsurface(bounds).copy()

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
        return (len(self.maps) == len({spec.asset for spec in MAPS.values()})
                and all(key in self.sprites for key in (*PROPS, *FISH_IDS)))
