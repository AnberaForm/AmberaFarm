# -*- coding: utf-8 -*-
"""Choose one of seven front-view characters, with four mood frames each."""
AVATARS=(
 ('original_girl','花の髪飾り'),
 ('mint_girl','ミントの少女'),
 ('blue_girl','メガネの少女'),
 ('blonde_girl','元気な少女'),
 ('farmer_boy','牧場の少年'),
 ('cafe_boy','カフェの少年'),
 ('silver_boy','湖畔の少年'),
)
IDS=tuple(i for i,_ in AVATARS)
LABELS=dict(AVATARS)
MOODS=('idle','wink','calm','happy')

def valid_avatar(value):
    return value if value in IDS else 'original_girl'
