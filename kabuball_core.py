# -*- coding: utf-8 -*-
"""Deterministic host-simulated 1v1 Kabuball arena.

Room host is authoritative for positions/scoring but is NOT a trusted economy
server. Therefore this module intentionally never transfers wagered currency.
"""
from __future__ import annotations
import math
import time

LEFT,TOP,RIGHT,BOTTOM=120.,95.,840.,445.
MID_X,MID_Y=480.,270.
GOAL_TOP,GOAL_BOTTOM=210.,330.
PLAYER_R=18.
BALL_R=10.
DURATION=180.
OVERTIME=60.


def clamp(v,lo,hi):return max(lo,min(hi,v))

def vector(x,y):
    length=math.hypot(x,y)
    return (x/length,y/length) if length>1e-8 else (0.,0.)


def valid_input(v):
    if not isinstance(v,dict):return None
    try:
        x,y,aim_x,aim_y=(float(v.get(k,0)) for k in ('dx','dy','ax','ay'))
    except (ValueError,TypeError,OverflowError):return None
    if not all(math.isfinite(n) for n in (x,y,aim_x,aim_y)):return None
    if max(abs(x),abs(y),abs(aim_x),abs(aim_y))>100:return None
    dx,dy=vector(x,y)
    ax,ay=vector(aim_x,aim_y)
    return {'dx':dx,'dy':dy,'ax':ax,'ay':ay,
            'dash':v.get('dash') is True,'shoot':v.get('shoot') is True,
            'tackle':v.get('tackle') is True,'feint':v.get('feint') is True,
            'pass':v.get('pass') is True}


class KabuballMatch:
    def __init__(self,ident,a,b,now=None,duration=DURATION):
        self.id=int(ident);self.ids=(a,b)
        self.created=time.monotonic() if now is None else float(now)
        self.last=self.created
        self.status='pending'
        self.duration=float(duration)
        self.started=0.
        self.pause_until=0.
        self.overtime=False
        self.scores=[0,0]
        self.goal_pauses=[]
        self.players=[dict(id=a,x=298.,y=270.,stamina=100.,face=(1.,0.),shoot_cd=0.,tackle_cd=0.,feint_cd=0.,charge=0.,was_shoot=False,was_pass=False,was_tackle=False,was_feint=False),
                      dict(id=b,x=662.,y=270.,stamina=100.,face=(-1.,0.),shoot_cd=0.,tackle_cd=0.,feint_cd=0.,charge=0.,was_shoot=False,was_pass=False,was_tackle=False,was_feint=False)]
        self.inputs={a:valid_input({}), b:valid_input({})}
        self.ball={'x':MID_X,'y':MID_Y,'vx':0.,'vy':0.,'owner':None}
        self.ended_at=0.
        self.completed=False
        self.reason=''
        self.invited_replay=set()

    def accept(self,now=None):
        if self.status!='pending':return False
        now=time.monotonic() if now is None else float(now)
        self.status='active';self.started=now+3.;self.last=now;self.pause_until=self.started
        return True

    def update_input(self,pid,inp):
        clean=valid_input(inp)
        if self.status!='active' or pid not in self.inputs or clean is None:return False
        self.inputs[pid]=clean
        return True

    def reset_positions(self):
        self.players[0].update(x=298.,y=MID_Y,face=(1.,0.))
        self.players[1].update(x=662.,y=MID_Y,face=(-1.,0.))
        self.ball.update(x=MID_X,y=MID_Y,vx=0.,vy=0.,owner=None)
        for p in self.players:
            p['was_shoot']=p['was_tackle']=p['was_feint']=p['was_pass']=False
            p['charge']=0.

    def _score(self,team,now):
        self.scores[team]+=1
        self.reset_positions()
        self.pause_until=now+3.
        self.goal_pauses.append((now,self.pause_until))
        if self.overtime:self.finish(now)

    def finish(self,now):
        if self.status=='active':
            self.status='finished';self.ended_at=now

    def abort(self,now=None):
        self.status='canceled';self.ended_at=time.monotonic() if now is None else now

    def elapsed(self,now):
        paused=sum(max(0.,min(now,end)-start) for start,end in self.goal_pauses)
        return max(0.,now-self.started-paused)

    def step(self,now=None):
        now=time.monotonic() if now is None else float(now)
        dt=clamp(now-self.last,0.,.07)
        self.last=now
        if self.status!='active':return
        if now < self.started or now < self.pause_until:return
        elapsed=self.elapsed(now)
        if elapsed >= self.duration and not self.overtime:
            if self.scores[0]!=self.scores[1]:self.finish(now);return
            self.overtime=True
        if elapsed >= self.duration+OVERTIME:self.finish(now);return
        # Bounded physics timestep to avoid tunneling through thin walls.
        count=max(1,math.ceil(dt/(1./90.)))
        for _ in range(count):self._substep(dt/count,now)

    def _substep(self,dt,now):
        if self.status!='active':return
        for p in self.players:
            inp=self.inputs[p['id']]
            dx,dy=inp['dx'],inp['dy']
            if dx or dy:p['face']=(dx,dy)
            moving=bool(dx or dy)
            sprint=moving and inp['dash'] and p['stamina']>=1.
            speed=245 if sprint else 160
            p['x']=clamp(p['x']+dx*speed*dt,LEFT+PLAYER_R,RIGHT-PLAYER_R)
            p['y']=clamp(p['y']+dy*speed*dt,TOP+PLAYER_R,BOTTOM-PLAYER_R)
            p['stamina']=clamp(p['stamina']+(-25 if sprint else 18)*dt,0.,100.)
            for key in ('shoot_cd','tackle_cd','feint_cd'):
                p[key]=max(0.,p[key]-dt)
        a,b=self.players
        vx,vy=b['x']-a['x'],b['y']-a['y']
        length=math.hypot(vx,vy)
        if 0 < length < 2*PLAYER_R:
            nx,ny=vx/length,vy/length
            shift=(2*PLAYER_R-length)/2
            a['x']-=nx*shift;a['y']-=ny*shift
            b['x']+=nx*shift;b['y']+=ny*shift
        ball=self.ball
        owner=next((p for p in self.players if p['id']==ball['owner']),None)
        if owner is not None:
            inp=self.inputs[owner['id']]
            if inp['shoot'] and owner['shoot_cd']<=0:
                owner['charge']=min(1.,owner['charge']+dt)
            shooting=owner['was_shoot'] and not inp['shoot'] and owner['shoot_cd']<=0
            passing=inp['pass'] and not owner['was_pass'] and owner['shoot_cd']<=0
            if shooting or passing:
                aim=(inp['ax'],inp['ay'])
                if aim==(0.,0.):aim=owner['face']
                power=(245.+365.*owner['charge']) if shooting else 275.
                ball['owner']=None
                # Place ball outside the player's collision radius, before applying velocity.
                ball['x']=owner['x']+aim[0]*(PLAYER_R+BALL_R+3)
                ball['y']=owner['y']+aim[1]*(PLAYER_R+BALL_R+3)
                ball['vx'],ball['vy']=(aim[0]*power,aim[1]*power)
                owner['shoot_cd']=.3
                owner['charge']=0.
            else:
                face=owner['face']
                ball['x']=owner['x']+face[0]*29
                ball['y']=owner['y']+face[1]*29
                ball['vx']=ball['vy']=0.
        if ball['owner'] is None:
            ball['x']+=ball['vx']*dt
            ball['y']+=ball['vy']*dt
            drag=math.exp(-1.8*dt)
            ball['vx']*=drag;ball['vy']*=drag
            if ball['y']<TOP+BALL_R:
                ball['y']=TOP+BALL_R;ball['vy']=abs(ball['vy'])*.81
            if ball['y']>BOTTOM-BALL_R:
                ball['y']=BOTTOM-BALL_R;ball['vy']=-abs(ball['vy'])*.81
            if ball['x'] < LEFT+BALL_R:
                if GOAL_TOP <= ball['y'] <= GOAL_BOTTOM:self._score(1,now);return
                ball['x']=LEFT+BALL_R;ball['vx']=abs(ball['vx'])*.81
            if ball['x'] > RIGHT-BALL_R:
                if GOAL_TOP <= ball['y'] <= GOAL_BOTTOM:self._score(0,now);return
                ball['x']=RIGHT-BALL_R;ball['vx']=-abs(ball['vx'])*.81
            if math.hypot(ball['vx'],ball['vy'])<380:
                for p in self.players:
                    if p['shoot_cd']<=0 and math.hypot(p['x']-ball['x'],p['y']-ball['y'])<=PLAYER_R+BALL_R+2:
                        ball['owner']=p['id'];ball['vx']=ball['vy']=0.;break
        for p in self.players:
            inp=self.inputs[p['id']]
            other=b if p is a else a
            if inp['tackle'] and not p['was_tackle'] and p['tackle_cd']<=0:
                p['tackle_cd']=.9
                if ball['owner']==other['id'] and math.hypot(p['x']-other['x'],p['y']-other['y'])<=61:
                    ball['owner']=p['id']
            if inp['feint'] and not p['was_feint'] and p['feint_cd']<=0 and p['stamina']>=22:
                dx,dy=inp['dx'],inp['dy']
                if dx or dy:
                    p['x']=clamp(p['x']+dx*34,LEFT+PLAYER_R,RIGHT-PLAYER_R)
                    p['y']=clamp(p['y']+dy*34,TOP+PLAYER_R,BOTTOM-PLAYER_R)
                    p['stamina']-=22;p['feint_cd']=2.
            p['was_shoot']=inp['shoot'];p['was_pass']=inp['pass'];p['was_tackle']=inp['tackle'];p['was_feint']=inp['feint']

    def view(self,pid,now=None):
        now=time.monotonic() if now is None else float(now)
        elapsed=self.elapsed(now) if self.status in ('active','finished') else 0.
        return {'id':self.id,'status':self.status,'side':self.ids.index(pid),
                'scores':list(self.scores),'players':[{'id':p['id'],'x':round(p['x'],2),'y':round(p['y'],2),
                  'stamina':round(p['stamina'],1),'charge':round(p['charge'],2)} for p in self.players],
                'ball':{k:(round(v,2) if isinstance(v,float) else v) for k,v in self.ball.items()},
                'remaining':max(0.,(self.duration+(OVERTIME if self.overtime else 0))-elapsed),
                'overtime':self.overtime,'start_in':max(0.,self.pause_until-now),
                'reason':self.reason,'replay':pid in self.invited_replay}
