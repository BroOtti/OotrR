"""Area presentations (first visit of a zone: camera tour + area name) never play.

Always on. Two mechanisms, chosen per presentation from what its first visit does
(scan of 1.1.1, 19/11):

* **Pre-marked** (:data:`PREMARKED`): the presentation is gated by a saved
  ``HavePlayedEvent`` Bool that only chooses between it and the normal arrival:
  either the entrance's ``InitEventFlag`` (``FieldAndDungeonEntranceEventRequestActor``:
  ``InitEventName`` while the flag is false, else ``NextEventName``), where the first
  arrival does nothing the normal one does not; or an ``EventQueryHavePlayedEvent``
  switch in ``Dm_SY_BancChangeArrive`` whose two cases merge into the same arrival.
  The flag is written at the end of the new-game opening, with the area's
  ``IsVisitLocation`` (the presentation's name frame is what marks it visited: without
  it the map menu shows "???"). These areas are therefore known on the map from the start.
* **Skipped at the first frame** (every other presentation): the native skip window
  (:func:`oot_rando.patching.qol_patches.add_skip_window`) is entered and left at once,
  as if **+** were pressed on the first frame. The event itself still starts, so what
  its caller does around it (quest steps of the first arrival, Ganon's collapse...)
  is kept; quest steps found inside the window (``SageOfForest Step05`` in the Forest
  Temple presentation) run between the window's start and end. The area name frame
  still opens (the window was not skipped) and marks the area visited. These are:

  - first arrivals that move a quest or write data: Death Mountain Trail
    (``Get_StoneOfFire``), Zora's Domain (``Get_StoneOfWater``), Desert Colossus
    (``SageOfSpirit``), Market (``Goto_HyruleCastle``), Deku Tree (``Get_StoneOfForest``
    + action guide), Goron City (``Get_StoneOfFire``), Forest Temple (``SageOfForest``),
    Gerudo Training Ground (``SubEvent_GetIceArrow``), Death Mountain Crater
    (``DeathMtCrater_IsFirstEntry``);
  - gates that are BoolExp (not writable): Kakariko (``InitDemo_KakarikoVillage``),
    Lake Hylia (``InitDemo_LakeHylia``);
  - presentations started by an ``EventRequestActor`` (Dodongo's Cavern inside, Forest
    Temple inside, Gerudo Valley, Temple of Time x2, Water Temple) or inside a quest
    flow (Jabu-Jabu, Hyrule Field, Ganon's tower collapse): no flag gates them.

Not validated in game.
"""
from oot_rando.patching.qol_patches import (AREA_PRESENTATIONS, SKIP_FADE_OUT_ACTIONS, _successors,
                                            add_skip_window, flow_path, skip_action_class)

# presentation -> (gating HavePlayedEvent flag, IsVisitLocation flag of its name frame)
PREMARKED = {
    'Dm_GanonCastle_0000': ('HavePlayedEvent.Dm_GanonCastle_0000', 'IsVisitLocation.GanonCastle'),
    'Dm_Gerudo_0000': ('HavePlayedEvent.Dm_Gerudo_0000', 'IsVisitLocation.GerudoFortress'),
    'Dm_Graveyard_0000': ('HavePlayedEvent.Dm_Graveyard_0000', 'IsVisitLocation.Graveyard'),
    'Dm_ZoraFountain_0000': ('HavePlayedEvent.Dm_ZoraFountain_0000', 'IsVisitLocation.ZoraFountain'),
    'Goto_FireTemple': ('HavePlayedEvent.Goto_FireTemple', 'IsVisitLocation.FireTemple'),
    'Goto_IceCave': ('HavePlayedEvent.Goto_IceCave', 'IsVisitLocation.IceCavern'),
    'Goto_KakarikoWells': ('HavePlayedEvent.Goto_KakarikoWells', 'IsVisitLocation.BottomOfTheWell'),
    'Goto_SacredForest': ('HavePlayedEvent.Goto_SacredForest', 'IsVisitLocation.SacredForestMeadow'),
    'Goto_ShadowTemple': ('HavePlayedEvent.Goto_ShadowTemple', 'IsVisitLocation.ShadowTemple'),
    # (the entrance's flag keeps the game's own spelling)
    'Goto_SpiritTemple': ('HavePlayedEvent.Goto_SpritTemple', 'IsVisitLocation.SpiritTemple'),
    'Goto_ZoraRiver': ('HavePlayedEvent.Goto_ZoraRiver', 'IsVisitLocation.ZoraRiver'),
}
AUTO_SKIPPED = tuple(name for name in AREA_PRESENTATIONS if name not in PREMARKED)
# Inside a window, these still run when it is left at once (in the window's order).
KEPT_ACTIONS = ('EventExecuteProgressChallengeStep',)
AUTO_PREFIX = 'RandoAutoSkip_'


def start_values():
    """GameData values written at the end of the new-game opening (full mode)."""
    values = {}
    for played, visit in PREMARKED.values():
        values[played] = True
        values[visit] = True
    return values


def auto_skip_presentation(raw):
    """``raw`` with every presentation entry's skip window left on its first frame.

    Returns (bytes, report): the :func:`add_skip_window` records, each with ``auto``
    (the window end jumped to) and ``kept`` (cloned quest steps)."""
    import copy
    import io
    from evfl.container import Container
    from evfl.event import ActionEvent, Event, SubFlowEvent
    from evfl.util import make_index
    from oot_rando.patching.event_patch import _flow, _snapshot
    windowed, records = add_skip_window(raw)
    flow = _flow(windowed)
    chart = flow.flowchart
    events = {e.name: e for e in chart.events}
    entries = {e.name: e for e in chart.entry_points}
    expected = _snapshot(flow)

    def reachable(starts, stops=()):
        seen, stack, order = set(), list(starts), []
        while stack:
            event = stack.pop()
            if event is None or event.name in seen or event.name in stops:
                continue
            seen.add(event.name)
            order.append(event)
            if isinstance(event.data, SubFlowEvent) and not event.data.res_flowchart_name:
                sub = entries.get(event.data.entry_point_name)
                stack.append(sub.main_event.v if sub is not None else None)
            stack.extend(_successors(event))
        return order

    roots = lambda: [e.main_event.v for e in chart.entry_points]
    before = {e.name for e in reachable(roots())}
    by_entry = {}
    for record in records:
        by_entry.setdefault(record['entry'], []).append(record)
    windows = set()
    for entry_name, entry_records in by_entry.items():
        start = entries[entry_name].main_event.v
        ends = [events[r['end']] for r in entry_records]
        region = reachable([start.data.nxt.v], {e.name for e in ends})
        windows |= {e.name for e in region}
        order = {e.name: i for i, e in enumerate(chart.events)}
        kept = sorted((e for e in region if isinstance(e.data, ActionEvent)
                       and e.data.actor_action.v.v in KEPT_ACTIONS), key=lambda e: order[e.name])
        after = ends[0]
        clones = []
        for index, original in reversed(list(enumerate(kept))):
            clone = Event()
            clone.name, clone.data = f'{AUTO_PREFIX}{entry_name}_{index}', ActionEvent()
            clone.data.actor, clone.data.actor_action = original.data.actor, original.data.actor_action
            clone.data.params = Container()
            clone.data.params.data = copy.deepcopy(original.data.params.data)
            clone.data.nxt = make_index(after)
            chart.events.append(clone)
            expected[clone.name] = dict(clone.data.params.data)
            clones.insert(0, clone.name)
            after = clone
        start.data.nxt = make_index(after)
        for record in entry_records:
            record['auto'] = ends[0].name
            record['kept'] = [events[e.name].data.params.data.get('StepName') for e in kept]
    # What no longer runs outside the windows: the other branches' cleanup only.
    dropped = before - {e.name for e in reachable(roots())} - windows
    for name in sorted(dropped):
        data = events[name].data
        if name.startswith('Rando') or not isinstance(data, ActionEvent):
            continue
        action = data.actor_action.v.v
        actor = data.actor.v.identifier.name
        params = data.params.data if data.params is not None else {}
        if action not in SKIP_FADE_OUT_ACTIONS and skip_action_class(actor, action, params) != 'cosmetic':
            raise ValueError(f'Auto-skip drops a non-cosmetic action: {name} {action}')
    stream = io.BytesIO()
    flow.write(stream)
    result = stream.getvalue()
    checked = _flow(result)
    if _snapshot(checked) != expected:
        raise ValueError('The presentation auto-skip changed other parameters.')
    checked_entries = {e.name: e for e in checked.flowchart.entry_points}
    checked_events = {e.name: e for e in checked.flowchart.events}
    for record in records:
        start = checked_entries[record['entry']].main_event.v
        nxt = start.data.nxt.v
        while nxt.name.startswith(AUTO_PREFIX):
            nxt = nxt.data.nxt.v
        if (start.data.actor_action.v.v != 'EventTriggerSkipAcceptStart' or nxt.name != record['auto']
                or checked_events[record['auto']].data.actor_action.v.v != 'EventTriggerSkipEnd'):
            raise ValueError('Presentation auto-skip misplaced: ' + record['entry'])
    return result, records


def presentation_files(read_flow, premarked=True):
    """``read_flow(path)`` returns a decompressed flow. Returns ({path: bytes}, report).

    ``premarked``: the :data:`PREMARKED` flags are written at the start (full mode);
    those presentations keep a plain **+** window. Otherwise every one is auto-skipped."""
    files, report = {}, {}
    for name in AREA_PRESENTATIONS:
        raw = read_flow(flow_path(name))
        if premarked and name in PREMARKED:
            files[flow_path(name)], report[name] = add_skip_window(raw)
        else:
            files[flow_path(name)], report[name] = auto_skip_presentation(raw)
    return files, report


def expected_flow(name, original, records):
    """The flow verification rebuilds from the original and its spoiler records."""
    if any(record.get('auto') for record in records):
        return auto_skip_presentation(original)[0]
    return add_skip_window(original)[0]
