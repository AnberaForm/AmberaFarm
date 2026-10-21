# -*- coding: utf-8 -*-
"""Capture actual map rendering and generated sprites with isolated save data."""
import os
from pathlib import Path
import sys
import tempfile

os.environ['SDL_VIDEODRIVER']='dummy'
os.environ['SDL_AUDIODRIVER']='dummy'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def render(destination):
    import pygame
    import ambera_farm as app
    from pixel_art import PROPS, FISH_IDS
    from scene_maps import MAPS, OUTDOOR, NEIGHBOR, NEIGHBOR_STORE
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    font=os.environ.get('AMBERA_PREVIEW_FONT')
    if font:app.font_file=lambda:font
    with tempfile.TemporaryDirectory(prefix='ambera_map_preview_') as tmp:
        os.environ['APPDATA']=tmp
        app.Game.fetch_mails=lambda self:None
        app.Game.refresh_notices=lambda self,force=False:None
        game=app.Game();game.scene='world'
        for area in MAPS:
            game.enter_area(area)
            game.warp_started=0
            game.message='';game.message_until=0
            game.render()
            pygame.image.save(game.stage,str(destination/(area.replace(':','_')+'.png')))
        # Screens at points where the furniture/shop interaction actually works.
        for area,point,name in (('room:home',(400,355),'home_bed'),
                                ('room:greenhouse',(505,340),'greenhouse_board'),
                                (NEIGHBOR,(637,350),'neighbor_door'),
                                (NEIGHBOR_STORE,(430,350),'neighbor_counter')):
            game.enter_area(area)
            if area==NEIGHBOR:game.neighbor_pos=list(point)
            else:game.interior_pos=list(point)
            game.warp_started=0;game.render()
            pygame.image.save(game.stage,str(destination/(name+'.png')))
        surface=pygame.Surface((960,600));surface.fill(app.CREAM)
        for index,key in enumerate((*PROPS,*FISH_IDS)):
            x=index%8*120;y=index//8*200
            app.box(surface,(x+3,y+5,114,188),app.PAPER,app.BROWN,3,1)
            game.pixel_art.draw(surface,key,(x+10,y+15,100,140))
            app.text(surface,game.fonts,key,(x+60,y+170),12,app.BROWN,False,True)
        pygame.image.save(surface,str(destination/'sprite_catalog.png'))
        game.enter_area(OUTDOOR);game.player=[850.,470.];game.warp_started=0
        game.render();pygame.image.save(game.stage,str(destination/'outdoor.png'))
        overview=pygame.Surface((1280,808));overview.fill(app.DARK)
        app.text(overview,game.fonts,'アンベラ牧場 v9.4.0 / 実際のゲーム画面',(640,19),24,app.CREAM,True,True)
        cards=(('room_home.png','自宅'),('room_greenhouse.png','温室'),
               ('room_cafe.png','カフェ'),('neighbor_door.png','みずほ町'))
        for i,(filename,label) in enumerate(cards):
            x=i%2*640;y=40+i//2*384
            capture=pygame.image.load(str(destination/filename))
            overview.blit(pygame.transform.scale(capture,(640,360)),(x,y))
            app.text(overview,game.fonts,label,(x+320,y+370),16,app.CREAM,True,True)
        pygame.image.save(overview,str(destination/'AmberaFarm_v9_4_0_Preview.png'))
        pygame.quit()
    print('Captured',destination)


if __name__=='__main__':render(sys.argv[1])
