# -*- coding: utf-8 -*-
"""Editable story nodes driven by data/story_events.json; no pygame dependency.

New nodes require id, title, lines[], speaker, trigger. Trigger examples:
  {"kind":"always"}
  {"kind":"stat", "name":"fish_caught", "at_least": 1}
  {"kind":"flag", "id":"intro_lake"}
Nodes can be reordered/added independently of the UI or game logic.
"""
from __future__ import annotations
import json
from pathlib import Path


def load_story(path):
    content = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(content, list):
        raise ValueError('Story nodes must form a list')
    used = set()
    for item in content:
        if (not isinstance(item, dict) or not isinstance(item.get('id'), str)
            or not item['id'] or item['id'] in used or not isinstance(item.get('lines'), list)
            or not all(isinstance(line, str) for line in item['lines'])):
            raise ValueError('Invalid or duplicate story node')
        used.add(item['id'])
    return content


def available_story(story_nodes, state, npc="nagi"):
    seen = set(state.get('story_flags', []))
    for event in story_nodes:
        if event.get("npc", "nagi") != npc: continue
        if event['id'] in seen: continue
        condition = event.get('trigger', {'kind': 'always'})
        kind = condition.get('kind')
        if kind == 'always': return event
        if kind == 'stat' and state.get('stats', {}).get(condition.get('name'), 0) >= condition.get('at_least', 1):
            return event
        if kind == 'flag' and condition.get('id') in seen:
            return event
    return None


def finish_story(state, event_id):
    flags = state.setdefault('story_flags', [])
    if event_id not in flags:
        flags.append(event_id)
        return True
    return False
