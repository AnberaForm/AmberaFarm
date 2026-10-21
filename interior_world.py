# -*- coding: utf-8 -*-
"""Walkable local interiors. Geometry is screen-local and never overwrites outdoor coordinates."""
from dataclasses import dataclass

ROOMS=('home','shop','shipping','fish_market','general_store','hall','greenhouse','workshop','cafe')
LEFT,TOP,RIGHT,BOTTOM=240,165,1039,565
SPAWN=(637.,519.)
@dataclass(frozen=True)
class Station:
    label: str
    x: float
    y: float
    action: str

STATIONS={
 'home':(Station('ベッド',367,302,'home_rest'),Station('収納',818,306,'chest'),Station('家具',558,260,'decor'),Station('データ管理',911,451,'data_menu')),
 'shop':(Station('たねを買う',430,289,'shop'),),
 'shipping':(Station('出荷する',480,303,'shipping'),),
 'fish_market':(Station('魚を売る',470,299,'fish_market'),),
 'general_store':(Station('雑貨を買う',490,302,'general_store'),),
 'hall':(Station('カブボール',448,299,'arena'),Station('ミニゲーム',829,302,'duel')),
 'greenhouse':(Station('日替わり依頼',505,298,'daily_board'),),
 'workshop':(Station('衣装工房',502,304,'costume'),),
 'cafe':(Station('カフェのメニュー',418,298,'general_store'),Station('フレンド',815,303,'friends')),
}

def walkable(x,y):
    # Floor and counter are distinct; entry from bottom edge.
    return LEFT+22<=x<=RIGHT-22 and TOP+125<=y<=BOTTOM-17

def move(pos,dx,dy):
    x,y=pos
    if walkable(x+dx,y):x+=dx
    if walkable(x,y+dy):y+=dy
    return (x,y)

def nearby(room,pos,radius=90):
    if room not in STATIONS:return None
    x,y=pos
    stations=sorted(STATIONS[room],key=lambda s:(s.x-x)**2+(s.y-y)**2)
    if not stations:return None
    chosen=stations[0]
    return chosen if (chosen.x-x)**2+(chosen.y-y)**2<=radius**2 else None
