# -*- coding: utf-8 -*-
"""Distance-driven walking poses and cached, transparent four-direction sheets."""
from dataclasses import dataclass
import math
from pathlib import Path

DIRECTIONS = ('down', 'left', 'right', 'up')
FRAMES = 4
STRIDE_PIXELS = 44.


@dataclass
class WalkCycle:
    facing: str = 'down'
    distance: float = 0.
    moving: bool = False
    previous: tuple | None = None
    scene: str = ''

    def observe(self, position, scene='outdoor'):
        point = tuple(float(x) for x in position)
        if self.previous is None or self.scene != scene:
            self.previous, self.scene = point, scene
            self.distance = 0.
            self.moving = False
            return self.facing, 0
        dx, dy = point[0] - self.previous[0], point[1] - self.previous[1]
        self.previous = point
        moved = math.hypot(dx, dy)
        self.moving = .08 < moved < 55.
        if self.moving:
            self.facing = ('right' if dx > 0 else 'left') if abs(dx) > abs(dy) else ('down' if dy > 0 else 'up')
            self.distance = (self.distance + moved) % STRIDE_PIXELS
        else:
            self.distance = 0.
        return self.facing, (int(self.distance / STRIDE_PIXELS * FRAMES) % FRAMES if self.moving else 0)


class AvatarAtlas:
    def __init__(self, root):
        import pygame
        from character_avatars import IDS
        self.frames = {}
        self.cache = {}
        for avatar in IDS:
            path = Path(root) / 'assets' / 'avatars' / (avatar + '_walk.png')
            if not path.is_file():
                continue
            sheet = pygame.image.load(str(path)).convert_alpha()
            width, height = sheet.get_size()
            if width < 128 or height < 128:
                raise ValueError('歩行シートが小さすぎます: ' + path.name)
            cw, ch = width // 4, height // 4
            cells = [sheet.subsurface((round(col*width/4), round(row*height/4), cw, ch)).copy()
                     for row in range(4) for col in range(4)]
            # One common crop preserves foot placement across all animation cells.
            bounds = cells[0].get_bounding_rect(min_alpha=32)
            for cell in cells[1:]:
                bounds = bounds.union(cell.get_bounding_rect(min_alpha=32))
            if bounds.width < 2 or bounds.height < 2:
                raise ValueError('歩行シートが空です: ' + path.name)
            for row, direction in enumerate(DIRECTIONS):
                for col in range(4):
                    self.frames[(avatar, direction, col)] = cells[row*4+col].subsurface(bounds).copy()

    def sprite(self, avatar, direction, frame, size, outfit=None):
        import pygame
        from v8_features import OUTFIT_COLORS
        garment = (outfit.get('shirt', 0), outfit.get('hat', 0)) if outfit else None
        key = (avatar, direction, frame % 4, tuple(size), garment)
        if key in self.cache:
            return self.cache[key]
        source = self.frames.get((avatar, direction, frame % 4))
        if source is None:
            return None
        # Preserve aspect ratio and transparency; no smoothing of pixel art.
        ratio = min(size[0] / source.get_width(), size[1] / source.get_height())
        scaled = pygame.transform.scale(source, (max(1, round(source.get_width()*ratio)),
                                                  max(1, round(source.get_height()*ratio))))
        if garment:
            # In-game costume dye: original art remains the default (index 0).
            scaled = scaled.copy()
            w, h = scaled.get_size()
            for y in range(int(h*.53), int(h*.86)):
                for x in range(w):
                    color = scaled.get_at((x, y))
                    # Dye fabric, preserving outlines, the face and pink hands.
                    if (color.a < 120 or max(color.r,color.g,color.b)<65
                            or color.r>170 and color.r>color.g+15 and color.b>color.g*.90):
                        continue
                    # Rounded garment mask follows the torso and sleeves.
                    if ((x/w-.5)/.49)**2+((y/h-.685)/.19)**2>1:
                        continue
                    luminance = max(.27, (color.r + color.g + color.b)/650)
                    tint = OUTFIT_COLORS[garment[0] % len(OUTFIT_COLORS)]
                    scaled.set_at((x, y), (*[min(255, int(c*luminance)) for c in tint], color.a))
            # A small bow accent, rather than a flat bar painted over the hair.
            bx,by=int(w*.74),int(h*.24)
            radius=max(2,int(w*.06))
            tint=OUTFIT_COLORS[garment[1] % len(OUTFIT_COLORS)]
            pygame.draw.polygon(scaled,(66,46,42),[(bx-radius-1,by-radius-1),(bx+radius+1,by+radius+1),
                                                 (bx+radius+1,by-radius-1),(bx-radius-1,by+radius+1)])
            pygame.draw.polygon(scaled,tint,[(bx-radius,by-radius),(bx+radius,by+radius),
                                            (bx+radius,by-radius),(bx-radius,by+radius)])
        self.cache[key] = scaled
        if len(self.cache) > 1400:
            self.cache.pop(next(iter(self.cache)))
        return scaled
