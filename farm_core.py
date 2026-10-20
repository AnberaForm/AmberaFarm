# -*- coding: utf-8 -*-
"""Ambera Farm: gameplay rules, V1 save migration, portable tests (no pygame dependency).

The 12 crops and growing durations are from the user's specification.
Shop prices, starting balance, quests and rewards are explicitly PROVISIONAL new gameplay.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json, math, os, shutil, tempfile, time
from fishing_core import FISH, FISH_BY_ID, add_catch, sell_fish

SECONDS_PER_GAME_MINUTE = 20
PLOT_COLUMNS, PLOT_ROWS = 6, 4
PLOT_COUNT = PLOT_COLUMNS * PLOT_ROWS
SAVE_VERSION = 2
STARTING_COINS = 200  # new provisional balancing, not supplied in original game

@dataclass(frozen=True)
class Crop:
    id: str
    name: str
    filename: str
    grow_minutes: int
    note: str
    buy_price: int    # PROVISIONAL, editable
    sell_price: int   # PROVISIONAL, editable
    @property
    def grow_seconds(self):
        return self.grow_minutes * SECONDS_PER_GAME_MINUTE

CROPS = (
    Crop('kaiware','カイワレ大根','kaiware.png',30,'チュートリアル向け',10,20),
    Crop('radish','ラディッシュ','radish.png',60,'序盤向け',16,34),
    Crop('kabu','カブ','kabu.png',90,'回転率重視',22,48),
    Crop('ichigo','イチゴ','ichigo.png',180,'ジャム素材の構想',30,70),
    Crop('kyuri','キュウリ','kyuri.png',240,'連作は未確定',38,88),
    Crop('tomato','トマト','tomato.png',360,'料理素材の構想',48,115),
    Crop('potato','ジャガイモ','potato.png',720,'料理素材の構想',66,158),
    Crop('corn','トウモロコシ','corn.png',1080,'飼料素材の構想',85,205),
    Crop('komugi','小麦','komugi.png',1440,'加工素材の構想',100,245),
    Crop('kabotya','カボチャ','kabotya.png',2880,'イベント素材の構想',160,410),
    Crop('suika','スイカ','suika.png',4320,'高額出荷の構想',230,610),
    Crop('kin_ringo','金のリンゴ','kin_ringo.png',10080,'再収穫間隔未確定',600,1700),
)
CROP_BY_ID = {c.id:c for c in CROPS}

# Mission (ID, title, description, tracking stat, target, coins reward)
MISSIONS = (
    ('plant1','最初の一歩','作物の種を1つ植える','planted',1,40),
    ('buy3','種屋のお客さん','種を合計3個購入する','bought',3,50),
    ('harvest1','初めての収穫','作物を1個収穫する','harvested',1,100),
    ('ship3','出荷の練習','作物を合計3個出荷する','shipped',3,80),
    ('plant10','畑を耕す人','合計10回植え付ける','planted',10,140),
    ('variety3','作物コレクター','3種類の作物を収穫する','varieties',3,180),
    ('harvest20','牧場の働き者','合計20個収穫する','harvested',20,300),
    ('fish1','初めての釣果','魚を1匹釣り上げる','fish_caught',1,80),
    ('fish5','釣り好き','魚を合計5匹釣る','fish_caught',5,140),
    ('fishsell3','湖の恵み','魚を3匹売る','fish_sold',3,110),
    ('fishvariety','魚類図鑑','3種類の魚を釣る','fish_varieties',3,220),
)
MISSION_BY_ID = {m[0]:m for m in MISSIONS}

class SaveError(Exception):
    pass

def state_path():
    if os.environ.get('APPDATA'):
        return Path(os.environ['APPDATA']) / 'AmberaFarm' / 'save.json'
    return Path.home() / '.local' / 'share' / 'AmberaFarm' / 'save.json'

def _number(value, label, minimum=0):
    if isinstance(value,bool) or not isinstance(value,(int,float)):
        raise SaveError(f'{label}が数値ではありません。')
    value=float(value)
    if not math.isfinite(value) or value<minimum:
        raise SaveError(f'{label}の値が不正です。')
    return value

def _count(value, label):
    if isinstance(value,bool) or not isinstance(value,int) or value<0:
        raise SaveError(f'{label}の値が不正です。')
    return value

def new_state(now=None):
    now=time.time() if now is None else float(now)
    return dict(version=SAVE_VERSION,created_at=now,plots=[None]*PLOT_COUNT,
        warehouse={c.id:0 for c in CROPS}, harvest_total=0,history=[],
        selected_crop='kaiware',coins=STARTING_COINS,
        seeds={c.id:(4 if c.id=='kaiware' else 0) for c in CROPS},
        stats={'planted':0,'bought':0,'harvested':0,'shipped':0,'fish_caught':0,'fish_sold':0},
        harvested_types={c.id:0 for c in CROPS},
        missions_claimed=[],player=[10.5*32,11.5*32],
        fish_inventory={f.id:0 for f in FISH},
        fish_caught_types={f.id:0 for f in FISH},
        story_flags=[],
    )

def validate_state(raw):
    if not isinstance(raw,dict) or raw.get('version') not in (1,2):
        raise SaveError('セーブ形式またはバージョンが不正です。')
    initial=new_state(_number(raw.get('created_at'),'開始日時'))
    initial['version']=SAVE_VERSION
    plots=raw.get('plots')
    if not isinstance(plots,list) or len(plots)!=PLOT_COUNT:
        raise SaveError('畑データが不正です。')
    cleaned=[]
    for i,p in enumerate(plots):
        if p is None:
            cleaned.append(None);continue
        if not isinstance(p,dict) or p.get('crop') not in CROP_BY_ID:
            raise SaveError(f'{i+1}番の畑データが不正です。')
        cleaned.append({'crop':p['crop'],'planted_at':_number(p.get('planted_at'),'植え付け日時')})
    initial['plots']=cleaned
    for field in ('warehouse',):
        if not isinstance(raw.get(field),dict):
            raise SaveError('倉庫データが不正です。')
        initial[field]={c.id:_count(raw[field].get(c.id,0),field) for c in CROPS}
    initial['harvest_total']=_count(raw.get('harvest_total',0),'収穫合計')
    history=raw.get('history',[])
    if not isinstance(history,list):raise SaveError('履歴が不正です。')
    initial['history']=[]
    for e in history[-100:]:
        if not isinstance(e,dict) or e.get('crop') not in CROP_BY_ID:raise SaveError('履歴の作物が不正です。')
        initial['history'].append({'crop':e['crop'],'at':_number(e.get('at'),'収穫日時')})
    selected=raw.get('selected_crop')
    if selected in CROP_BY_ID:initial['selected_crop']=selected
    if raw['version']==1:
        # Preserve the V1 farm and inventory. Add starter economy, without erasing old harvest count.
        initial['stats']['harvested']=initial['harvest_total']
        for e in initial['history']:
            initial['harvested_types'][e['crop']]+=1
        from v8_features import init_v8
        return init_v8(initial)
    initial['coins']=_count(raw.get('coins',STARTING_COINS),'所持金')
    seeds=raw.get('seeds')
    if not isinstance(seeds,dict):raise SaveError('種のデータが不正です。')
    initial['seeds']={c.id:_count(seeds.get(c.id,0),'種の個数') for c in CROPS}
    stats=raw.get('stats')
    if not isinstance(stats,dict):raise SaveError('統計データが不正です。')
    initial['stats']={k:_count(stats.get(k,0),k) for k in ('planted','bought','harvested','shipped','fish_caught','fish_sold')}
    types=raw.get('harvested_types')
    if not isinstance(types,dict):raise SaveError('収穫種類のデータが不正です。')
    initial['harvested_types']={c.id:_count(types.get(c.id,0),'種類別の収穫数') for c in CROPS}
    claimed=raw.get('missions_claimed',[])
    if not isinstance(claimed,list) or any(x not in MISSION_BY_ID for x in claimed) or len(claimed)!=len(set(claimed)):
        raise SaveError('ミッションのデータが不正です。')
    initial['missions_claimed']=list(claimed)
    pos=raw.get('player',initial['player'])
    if not isinstance(pos,list) or len(pos)!=2:
        raise SaveError('プレイヤー座標が不正です。')
    initial['player']=[_number(x,'座標') for x in pos]
    # Optional V2 extension: old V2 save files automatically gain fishing and story data.
    for field in ('fish_inventory', 'fish_caught_types'):
        original=raw.get(field, {})
        if not isinstance(original, dict):
            raise SaveError(f'{field}のデータが不正です。')
        initial[field]={f.id:_count(original.get(f.id,0),field) for f in FISH}
    flags=raw.get('story_flags', [])
    if (not isinstance(flags, list) or len(flags)>1000
            or any(not isinstance(x,str) or len(x)>128 for x in flags)
            or len(flags)!=len(set(flags))):
        raise SaveError('ストーリーフラグが不正です。')
    initial['story_flags']=flags.copy()
    # Preserve the v8 gameplay fields while migrating the original V2 saves.
    from v8_features import validate_v8
    for field in ('stamina','stamina_updated_at','plot_preparation','consumables','outfits','outfit_index',
                  'outfit_draft','friends','player_uid','friend_ids','local_chat','player_name','mail_claimed',
                  'event_tokens','event_claimed','event_earned_on','event_daily_count'):
        if field in raw:
            initial[field]=raw[field]
    try:
        validate_v8(initial)
    except ValueError as exc:
        raise SaveError(str(exc)) from exc
    return initial

def load_json(file):
    try:
        with Path(file).open('r',encoding='utf-8-sig') as f:
            return validate_state(json.load(f))
    except (OSError,ValueError,UnicodeError,TypeError) as e:
        raise SaveError(f'セーブを読み込めません: {e}') from e

def load_state(file=None,now=None):
    file=state_path() if file is None else Path(file)
    if not file.exists():return new_state(now),'新しい牧場を準備しました。'
    try:
        loaded=load_json(file)
        return loaded, 'セーブを読み込みました。' if loaded['version']==2 else '以前の牧場を引き継ぎました。'
    except SaveError as exc:
        bak=file.with_suffix('.bak.json')
        if bak.exists():
            try:return load_json(bak),f'バックアップから復元しました（{exc}）'
            except SaveError:pass
        raise

def save_state(state,file=None,create_backup=True):
    file=state_path() if file is None else Path(file)
    data=validate_state(state)
    path=None
    try:
        file.parent.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix='.ambera_',suffix='.tmp',dir=str(file.parent))
        path=Path(name)
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
            json.dump(data,f,ensure_ascii=False,indent=2)
            f.flush();os.fsync(f.fileno())
        if create_backup and file.exists():
            try:
                load_json(file)
                shutil.copy2(file,file.with_suffix('.bak.json'))
            except SaveError:pass
        os.replace(path,file)
    except (OSError,ValueError,TypeError) as e:
        raise SaveError(f'保存失敗: {e}') from e
    finally:
        if path is not None and path.exists():path.unlink()

def progress_for(plot,now=None):
    if plot is None:return 0.,0.,False
    now=time.time() if now is None else float(now)
    elapsed=max(0.,now-plot['planted_at'])
    duration=CROP_BY_ID[plot['crop']].grow_seconds
    remaining=max(0.,duration-elapsed)
    return min(1.,elapsed/duration),remaining,remaining==0.

def plant(state,index,crop_id,now=None):
    if not 0<=index<PLOT_COUNT or crop_id not in CROP_BY_ID or state['plots'][index] is not None:
        return False
    if state['seeds'][crop_id]<=0:return False
    state['plots'][index]={'crop':crop_id,'planted_at':time.time() if now is None else float(now)}
    state['seeds'][crop_id]-=1
    state['stats']['planted']+=1
    return True

def harvest(state,index,now=None):
    if not 0<=index<PLOT_COUNT:return None
    p=state['plots'][index]
    now=time.time() if now is None else float(now)
    if p is None or not progress_for(p,now)[2]:return None
    crop=p['crop']
    state['plots'][index]=None
    state['warehouse'][crop]+=1
    state['harvest_total']+=1
    state['stats']['harvested']+=1
    state['harvested_types'][crop]+=1
    state['history'].append({'crop':crop,'at':now})
    state['history']=state['history'][-100:]
    return crop

def buy_seeds(state,crop_id,quantity=1):
    if crop_id not in CROP_BY_ID or isinstance(quantity,bool) or not isinstance(quantity,int) or quantity<=0:return False
    cost=CROP_BY_ID[crop_id].buy_price*quantity
    if state['coins']<cost:return False
    state['coins']-=cost
    state['seeds'][crop_id]+=quantity
    state['stats']['bought']+=quantity
    return True

def sell_crops(state,crop_id,quantity=1):
    if crop_id not in CROP_BY_ID or isinstance(quantity,bool) or not isinstance(quantity,int) or quantity<=0:return False
    if state['warehouse'][crop_id]<quantity:return False
    state['warehouse'][crop_id]-=quantity
    state['coins']+=CROP_BY_ID[crop_id].sell_price*quantity
    state['stats']['shipped']+=quantity
    return True

def mission_progress(state,mission_id):
    mission=MISSION_BY_ID[mission_id]
    if mission[3]=='fish_varieties':
        amount=sum(1 for n in state['fish_caught_types'].values() if n>0)
    elif mission[3]=='varieties':
        amount=sum(1 for n in state['harvested_types'].values() if n>0)
    else:amount=state['stats'][mission[3]]
    return min(amount,mission[4]),mission[4]

def claim_mission(state,mission_id):
    if mission_id not in MISSION_BY_ID or mission_id in state['missions_claimed']:return False
    progress,target=mission_progress(state,mission_id)
    if progress<target:return False
    state['missions_claimed'].append(mission_id)
    state['coins']+=MISSION_BY_ID[mission_id][5]
    return True

def clock_at(state,now=None):
    now=time.time() if now is None else float(now)
    total=360+int(max(0,now-state['created_at'])//SECONDS_PER_GAME_MINUTE)
    return total//1440+1,(total%1440)//60,total%60

def time_short(seconds):
    if seconds<=0:return '収穫OK'
    minutes=max(1,math.ceil(seconds/60))
    d,rem=divmod(minutes,1440)
    h,m=divmod(rem,60)
    if d:return f'{d}日{h}時間' if h else f'{d}日'
    if h:return f'{h}時間{m}分' if m else f'{h}時間'
    return f'{m}分'

def duration_text(seconds):
    if seconds%3600==0:return f'{seconds//3600}時間'
    if seconds>=3600:return f'{seconds//3600}時間{seconds//60%60}分'
    return f'{seconds//60}分'
