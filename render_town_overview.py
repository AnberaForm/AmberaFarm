# -*- coding: utf-8 -*-
"""Preview actual building sprites and collision layout without pygame.
This is a development illustration, not an in-game screenshot.
"""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw, ImageFont
from world_map import (BUILDINGS,TREE_POSITIONS,TRAVEL_STOPS,
                       water_at,path_at,plaza_at,flower_at,TILE,
                       WORLD_W,WORLD_H,plot_world)

ROOT=Path(__file__).resolve().parents[1]
scale=2
w,h=WORLD_W*TILE,WORLD_H*TILE
im=Image.new('RGBA',(w,h),(98,157,87,255));d=ImageDraw.Draw(im)
for ty in range(WORLD_H):
 for tx in range(WORLD_W):
  x,y=tx*TILE,ty*TILE
  n=(tx*113+ty*71+tx*ty*17)%17
  shade=(93+n//4,151+n//3,80+n//3,255)
  if water_at(tx,ty):
   shade=(66+n,129+n,170+n//2,255)
  elif plaza_at(tx,ty):shade=(194+n//3,180+n//4,150+n//4,255)
  elif path_at(tx,ty):shade=(193+n//3,159+n//4,110+n//4,255)
  d.rectangle((x,y,x+31,y+31),fill=shade)
  if flower_at(tx,ty):
   for px,py in ((9,9),(22,14),(14,24)):
    d.rectangle((x+px-3,y+py-3,x+px+3,y+py+3),fill=(233,180,178,255));d.rectangle((x+px,y+py,x+px+2,y+py+2),fill=(255,228,139,255))
  if water_at(tx,ty) and n%3==0:d.rectangle((x+7,y+12,x+23,y+15),fill=(128,193,206))
  if plaza_at(tx,ty):
   d.rectangle((x,y,x+31,y+31),outline=(163,147,119))
for tx,ty in TREE_POSITIONS:
 x,y=tx*TILE,ty*TILE
 d.rectangle((x+12,y+17,x+19,y+31),fill=(105,72,49))
 d.rectangle((x+3,y+5,x+28,y+21),fill=(48,116,65))
 d.rectangle((x+8,y+0,x+23,y+13),fill=(61,145,76))
for i in range(24):
 x,y=plot_world(i);x=int(x);y=int(y)
 d.rectangle((x-21,y-21,x+21,y+21),fill=(137,88,55),outline=(87,59,40),width=3)
for tx in range(12,16):
 x,y=tx*TILE,29*TILE
 d.rectangle((x,y+5,x+31,y+27),fill=(165,120,80))
 d.line((x+14,y+7,x+14,y+27),fill=(117,76,48),width=2)
font_path='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
try:font=ImageFont.truetype(font_path,18)
except OSError:font=ImageFont.load_default()
for b in BUILDINGS:
 x,y=b.tile_x*TILE,b.tile_y*TILE
 bw,bh=b.tile_w*TILE,b.tile_h*TILE
 part=Image.open(ROOT/'assets'/'buildings'/(b.key+'.png')).convert('RGBA')
 part=part.resize((bw,bh),Image.Resampling.NEAREST)
 im.alpha_composite(part,(x,y))
 label=b.label
 bbox=d.textbbox((0,0),label,font=font)
 tw=bbox[2]-bbox[0]
 d.rounded_rectangle((x+bw//2-tw//2-9,y+bh//2-17,x+bw//2+tw//2+9,y+bh//2+14),4,fill=(247,227,168),outline=(91,68,48),width=2)
 d.text((x+bw//2-tw//2,y+bh//2-12),label,font=font,fill=(43,54,40))
for key,(label,(px,py)) in TRAVEL_STOPS.items():
 x,y=int(px),int(py)
 d.rectangle((x-4,y-24,x+4,y+7),fill=(96,68,45))
 d.rectangle((x-22,y-28,x+22,y-8),fill=(246,218,138),outline=(106,77,54))
for (x,y,wf,hf) in [(26*TILE,16*TILE,44,35)]:
 d.rectangle((x,y,x+wf,y+hf),fill=(227,193,127),outline=(107,77,48),width=4)
im=im.convert('RGB').resize((w//2,h//2),Image.Resampling.NEAREST)
out=Path('/mnt/data/AmberaFarm_V0_90_Town_Layout_Preview.png')
im.save(out,optimize=True)
print(out,im.size)
