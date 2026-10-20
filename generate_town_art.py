# -*- coding: utf-8 -*-
"""Deterministic, hand-authored pixel-art building sprites; Pillow is needed only
for recreating the PNG sources. Runtime needs only pygame and bundled PNGs."""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[1] / 'assets' / 'buildings'
ROOT.mkdir(parents=True, exist_ok=True)
styles={
    'home':((166,82,77),(229,204,155),(97,72,58),'house'),
    'greenhouse':((79,145,119),(213,235,197),(63,112,96),'glass'),
    'shop':((185,109,69),(245,216,153),(112,72,46),'seeds'),
    'general_store':((89,134,174),(235,207,162),(62,87,107),'goods'),
    'workshop':((160,112,181),(233,204,166),(86,60,104),'outfit'),
    'hall':((111,93,166),(218,192,154),(67,64,105),'arena'),
    'cafe':((169,90,97),(246,219,176),(111,56,67),'coffee'),
    'shipping':((126,118,84),(213,192,141),(83,75,58),'crate'),
    'fish_market':((74,142,168),(228,213,182),(52,93,123),'fish'),
}

def build(style):
    roof,wall,trim,icon=style
    img=Image.new('RGBA',(112,88),(0,0,0,0))
    d=ImageDraw.Draw(img)
    def rect(v,c):d.rectangle(v,fill=c)
    # Foundation and shadow. Keep each point aligned to an integer tile pixel.
    rect((5,72,108,81),(42,68,57,130));rect((5,41,106,74),trim)
    rect((9,39,102,72),wall)
    for y in range(44,71,8):
        d.line((11,y,100,y),fill=tuple(max(0,c-12) for c in wall),width=1)
    # Deep roof with ridgeline, outline and tiles, isometric-ish frontal elevation.
    d.polygon([(2,38),(10,10),(54,1),(102,10),(110,38)],fill=trim)
    d.polygon([(8,34),(15,13),(54,5),(97,13),(105,34)],fill=roof)
    for y in (14,20,26,31):
        d.line((16,y,97,y),fill=tuple(min(255,c+20) for c in roof),width=2)
    for x in range(21,102,15):
        d.line((x,14,x-3,32),fill=tuple(max(0,c-27) for c in roof),width=1)
    # Doorway & porch, two glass windows with frames.
    rect((48,51,66,75),trim);rect((51,54,63,74),(110,74,56));rect((60,64,61,66),(243,215,118))
    for x in (19,78):
        rect((x-2,49,x+17,64),trim);rect((x,51,x+15,62),(148,204,212));
        rect((x+7,51,x+8,62),trim);rect((x,56,x+15,57),trim)
    # Unique shop sign, readable silhouette and themed accents.
    rect((40,37,74,50),trim);rect((43,39,71,47),(236,213,158))
    if icon=='house':
        rect((49,40,63,44),(181,95,82));rect((55,38,57,46),(188,110,87))
        rect((6,53,13,72),(160,111,76));rect((9,56,11,68),(238,196,114))
    elif icon=='glass':
        for xx in (15,33,79,94):
            rect((xx,25,xx+4,35),(98,192,180));rect((xx+1,27,xx+3,30),(216,250,217))
        rect((47,40,67,45),(68,155,112))
    elif icon=='seeds':
        for cx,cy in ((51,44),(57,42),(63,44)):
            d.ellipse((cx-3,cy-3,cx+3,cy+2),fill=(103,152,80))
        rect((7,57,18,67),(135,85,49));rect((92,57,103,67),(135,85,49))
    elif icon=='goods':
        rect((49,41,65,46),(109,141,196));rect((53,39,60,43),(230,225,195))
        for x in (9,95):rect((x,64,x+7,73),(139,92,57))
    elif icon=='outfit':
        d.polygon([(49,42),(54,40),(57,43),(60,40),(65,42),(63,47),(50,47)],fill=(167,95,161))
        rect((10,56,18,72),(135,100,148));rect((92,56,100,72),(135,100,148))
    elif icon=='arena':
        rect((45,40,69,47),(76,91,147));rect((47,42,67,45),(236,206,85))
        rect((12,56,22,72),(144,108,71));rect((90,56,100,72),(144,108,71))
        # flags
        rect((3,14,5,45),(89,69,70));d.polygon([(5,16),(19,20),(5,25)],fill=(236,198,92))
        rect((105,14,107,45),(89,69,70));d.polygon([(107,16),(94,20),(107,25)],fill=(232,112,112))
    elif icon=='coffee':
        rect((50,41,62,46),(146,83,61));rect((61,42,65,44),(146,83,61));rect((51,39,60,39),(243,226,214))
        for xx in (13,86):rect((xx,46,xx+7,49),(184,108,93))
    elif icon=='crate':
        rect((48,41,64,47),(141,91,57));d.line((49,42,63,46),fill=(222,176,110),width=2)
        for xx in (6,96):
            rect((xx,60,xx+10,73),(133,99,58));d.line((xx,60,xx+10,73),fill=(228,183,126),width=2)
    elif icon=='fish':
        d.ellipse((45,41,64,47),fill=(60,154,191));d.polygon([(61,44),(67,40),(67,48)],fill=(60,154,191))
        rect((7,62,14,72),(76,148,180));rect((96,62,103,72),(76,148,180))
    # Decorative flowerpots.
    for xx in (34,75):
        rect((xx,68,xx+6,75),(170,99,70));rect((xx+2,62,xx+4,70),(62,130,73))
        rect((xx-1,63,xx+1,66),(106,166,84));rect((xx+5,62,xx+7,65),(106,166,84))
    return img

for name,colors in styles.items():
    build(colors).save(ROOT / f'{name}.png',optimize=True)
print(f'created {len(styles)} sprites in {ROOT}')
