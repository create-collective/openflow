import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { baysFromHalves, readDockedModules, lastDockedModules } from "../lib/dockedModules";
import { useDeviceStream } from "../lib/deviceStream";
import { subscribeDeviceState, getDeviceState, deviceHasBeenRead } from "../lib/deviceState";
import { setShortcutTable } from "../lib/shortcutNames";
import { POS_LABEL } from "../lib/layout";
import { actionText } from "../lib/keylabels";
import { clearSaved, useOnDeviceRead } from "../lib/deviceActions";
import useProfileEditor from "../lib/useProfileEditor";
import BoardFit from "../components/BoardFit";
import KeymapBoard from "../components/KeymapBoard";
import LayerList from "../components/LayerList";
import ModuleProfileList from "../components/ModuleProfileList";
import SelectedKeyPanel from "../components/SelectedKeyPanel";
import ActionPalette from "../components/ActionPalette";
import Button from "../components/ui/Button";
import Card from "../components/ui/Card";
import Notice from "../components/ui/Notice";

// The keymap editor: layers and the board on top, the selected key's behaviours and the action
// palette below. Profiles, layers and their handlers come from useProfileEditor (shared with
// LED Map); the profile menu, Read, Back up and Flash are in the shell's profile bar. What
// stays here is the board's own business: the selected key and slot, the LED-outline
// preference, the module bays and their picker, and the action catalog the palette draws from.
export default function Bindings() {
  const [selectedPos, setSelectedPos] = useState(null);
  const ed = useProfileEditor();
  const { profile, layer, keysByPosition, layerMap } = ed;
  const [catalog, setCatalog] = useState(null);
  const [moduleProfiles, setModuleProfiles] = useState([]);
  const [macros, setMacros] = useState([]);
  // Show each key's LED colour as an outline on this page. Remembered, because it is a way of
  // working rather than a one-off view: you turn it on while laying out a layer's colour groups
  // and want it still on when you come back.
  const [ledOutline, setLedOutline] = useState(() => {
    try { return localStorage.getItem("openflow.ledOutline") === "1"; } catch { return false; }
  });
  const [activeSlot, setActiveSlot] = useState("tap");
  const [pickedModule, setPickedModule] = useState(null);
  // Which module picture each bay shows. Not stored in the browser: it comes from the
  // keyboard's last status, which the backend persists (see lib/dockedModules.js), so it is the
  // same in every browser and survives a cleared cache. Until the first read it is empty, and a
  // module can be placed by hand for the session (the palette drag).
  const [moduleAssign, setModuleAssign] = useState({ left: null, right: null });
  const navigate = useNavigate();
  const deviceRead = useSyncExternalStore(subscribeDeviceState, getDeviceState).modules;
  const { data: stream } = useDeviceStream();

  function setAssign(patch) {
    setModuleAssign((prev) => ({ ...prev, ...patch }));
  }

  function assignModule(slot, type) {
    setAssign({ [slot]: type });
    setPickedModule(null);
  }

  // The catalog, the macros and the module profiles: loaded once, and again after a read
  // (a read can capture module profiles the board was running).
  const loadExtras = useCallback(async () => {
    try {
      const [acts, mac, mods] = await Promise.all([api.actions(), api.macros(), api.modules()]);
      setCatalog(acts);
      setShortcutTable(acts.shortcuts);
      setMacros(mac.macros || []);
      setModuleProfiles(mods.modules || []);
    } catch (e) {
      ed.setErr(e.message);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => { loadExtras(); }, [loadExtras]);

  // Only a status that actually saw a module may repaint a bay. Right after a keymap read the
  // port can still be busy and the status comes back with no halves at all; painting THAT
  // blanked both bays and, since the backend keeps the last status, blanked them on the next
  // load too. An empty answer is "unknown", not "nothing docked".
  // `b` is null when the keyboard told us nothing (nothing read yet, or a read that
  // failed); then the board keeps what it had. Anything else is an answer and gets
  // painted, INCLUDING two empty bays -- this used to require at least one bay to be
  // filled, so unplugging the last module left it on screen.
  function paintBays(b) {
    if (b) setAssign(b);
  }

  // After a read, ask the board what is docked. Best effort: the keymap read has already
  // succeeded, so a module query that fails must not turn a good read into an error.
  async function syncDockedModules() {
    try {
      paintBays(await readDockedModules(api));
    } catch { /* leave the existing assignment alone */ }
  }

  // Paint the bays from the last persisted status on mount, without touching the port...
  useEffect(() => {
    let alive = true;
    lastDockedModules(api).then((b) => { if (alive) paintBays(b); }).catch(() => {});
    return () => { alive = false; };
  }, []);
  // ...and from then on follow the devices stream: the six-second poll already says which
  // module sits in which bay (it is what the profile bar shows), so the bays track a module
  // being docked or swapped without anyone pressing Read.
  useEffect(() => {
    paintBays(baysFromHalves(stream?.status?.halves));
  }, [stream]);

  // A read (from the profile bar) has already reloaded the profiles and switched to the one it
  // produced; what is left is this page's own follow-up.
  useOnDeviceRead(async () => {
    setSelectedPos(null);
    await syncDockedModules();
    await loadExtras();
  });
  // The selection belongs to a profile: switching (from the bar, or by a read) drops it.
  useEffect(() => { setSelectedPos(null); }, [profile?.id]);

  // Which module profile is running in one bay of the layer being edited.
  //
  // Three steps, and skipping any of them lands on the wrong profile: the layer's own bay
  // assignment, falling back to the BASE layer because an unset bay inherits from layer 0
  // (not from the nearest layer below: proved by overriding a bay on layer 1 and pressing
  // the buttons on layer 2); then the device read, because the profile a bay names may be an
  // edited copy while the board is running the version we captured from it.
  function liveConfigForBay(type, bay) {
    if (!profile || !bay) return null;
    const cur = profile.layers.find((l) => l.id === ed.activeLayerId);
    const base = profile.layers.find((l) => l.orderId === 0) || profile.layers[0];
    const key = `${type}:keyboard_${bay}`;
    let id = cur?.bays?.[key];
    if (!id || id === "transparent") id = base?.bays?.[key];
    if (!id || id === "transparent" || id === "disabled") return null;
    const entry = Object.values(deviceRead || {}).find((e) => e.uuid === id);
    return entry?.matched || id;
  }

  // Everything the board's module row needs to offer a profile per bay.
  //
  // A choice is written against the LAYER being edited. Set them on the base layer and the rest
  // inherit; change one elsewhere and only that layer differs; the flash then works out that
  // the board needs the base layer's profiles plus that alternate.
  const bayUI = useMemo(() => {
    if (!profile || !catalog) return null;
    const cur = profile.layers.find((l) => l.id === ed.activeLayerId);
    const base = profile.layers.find((l) => l.orderId === 0) || profile.layers[0];
    const key = (type, side) => `${type}:keyboard_${side}`;
    // A control with no side is SYMMETRIC: it governs both bays, and a write with no side
    // sets both (db.userdata.set_layer_bay). Reading only the left was the bug -- a Touch
    // assigned to the right bay alone read as Disabled (SCRUM-92).
    const sidesOf = (side) => (side ? [side] : ["left", "right"]);
    const layerLabel = cur ? `Layer ${cur.orderId}${cur.name ? ` ${cur.name}` : ""}` : null;
    const liveIds = new Set(
      Object.values(deviceRead || {}).map((e) => e.matched).filter(Boolean));

    // Strictly what THIS profile has stored, falling back to the base layer for an unset bay.
    // It deliberately does NOT re-resolve through the device read: the profile is a choice
    // about what to flash next, not a mirror of the keyboard. The read still marks which
    // entries are live; that is a label on the options, not a change to the answer.
    //
    // A bay's value counts only if it names a profile of the bay's own type; anything else
    // (a read once stored a Track id in a Tune bay) is unset, and the layer follows the base
    // layer. The backend applies the same rule when it flashes.
    const typeOf = (id) => (moduleProfiles || []).find((m) => m.id === id)?.type;
    const oneBay = (l, type, side) => {
      const v = l?.bays?.[key(type, side)];
      if (!v || v === "transparent") return null;
      if (v === "disabled") return v;
      return typeOf(v) === type.toUpperCase() ? v : null;
    };
    // An assigned bay is the truthful answer for a symmetric control: "disabled on the
    // left, running a profile on the right" is a board that HAS that profile.
    const ownFor = (l, type, side) => {
      const vals = sidesOf(side).map((s) => oneBay(l, type, s));
      return vals.find((v) => v && v !== "disabled") ?? vals.find((v) => v) ?? null;
    };
    const selectedFor = (type, side) => ownFor(cur, type, side) ?? ownFor(base, type, side) ?? null;
    // The two bays of a symmetric control holding different things. Nothing we write can
    // produce it; a profile configured in NayaFlow can. Worth saying out loud, because one
    // control cannot express it and the next pick will flatten it onto both sides.
    const splitFor = (type, side) => {
      if (side) return false;
      const l = oneBay(cur, type, "left") ?? oneBay(base, type, "left");
      const r = oneBay(cur, type, "right") ?? oneBay(base, type, "right");
      return l !== r;
    };

    return {
      layerLabel,
      // A Track profile belongs to one side: the left and right units are different hardware,
      // so the left bay must not offer right-hand profiles. Symmetric modules have a single
      // variant and every profile of the type is valid in either bay. A Track profile with NO
      // side tag is offered in both bays (imported profiles arrive that way).
      profilesFor: (type, side) => {
        const t = type.toUpperCase();
        const want = t === "TRACK" && side ? `TRACK_${side.toUpperCase()}` : null;
        return (moduleProfiles || [])
          .filter((m) => m.type === t && (!want || !m.variant || m.variant === want))
          .map((m) => ({ id: m.id, name: m.name + (want && !m.variant ? " (no side set)" : ""),
                         onBoard: liveIds.has(m.id) }));
      },
      selectedFor,
      splitFor,
      // True when the layer follows the base layer here: it says nothing, or it says the
      // same thing (the owner's rule: base is whatever equals layer 0).
      inheritedFor: (type, side) => {
        if (!cur || cur.id === base?.id) return false;
        const own = ownFor(cur, type, side);
        return own == null || own === ownFor(base, type, side);
      },
      onPick: async (type, side, configId) => {
        try {
          await api.setLayerBay({
            layerId: ed.activeLayerId, moduleType: type.toUpperCase(), side, configId,
          });
          await ed.reload();
        } catch (e) { ed.setErr(e.message); }
      },
      onManage: (type, side) => {
        const id = selectedFor(type, side);
        navigate(id && id !== "disabled"
          ? `/module-configuration?config=${id}`
          : `/module-configuration?type=${type.toUpperCase()}`);
      },
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile, catalog, ed.activeLayerId, deviceRead, moduleProfiles]);

  const selectedKey = selectedPos != null ? keysByPosition[selectedPos] : null;
  // "A → Hold" for the palette's head: the key by its tap legend (its position when unbound),
  // the slot by its label.
  const slotLabel = catalog?.behaviorSlots?.find((s) => s.id === activeSlot)?.label || activeSlot;
  const keyName = selectedPos == null ? null
    : selectedKey?.bindings?.tap ? actionText(selectedKey.bindings.tap, layerMap) : POS_LABEL[selectedPos];

  async function bind(pick) {
    if (selectedPos == null || !layer) return;
    try {
      await api.setKeyBinding({
        layerId: layer.id, positionId: selectedPos,
        actionCode: pick.actionCode, actionType: pick.actionType, behavior: activeSlot,
      });
      clearSaved();
      await ed.reload();
    } catch (e) { ed.setErr(e.message); }
  }

  async function clearSlot(slot) {
    if (selectedPos == null || !layer) return;
    try {
      await api.clearKeyBinding({ layerId: layer.id, positionId: selectedPos, behavior: slot });
      clearSaved();
      await ed.reload();
    } catch (e) { ed.setErr(e.message); }
  }

  const err = ed.error;

  if (!profile) {
    return (
      <div>
        <h1 className="page-title">Bindings</h1>
        <Card><div className="empty">{err || "Loading keymap…"}</div></Card>
      </div>
    );
  }

  return (
    // Two containers side by side: the left column (layers, module profiles) and the main
    // column (the board, then the selected-key band and the palette), each stacking on its own
    // so neither pushes the other around.
    <div className="editor editor-split">
      <div className="layer-col">
          <LayerList
            profiles={ed.profiles.filter((p) => p.id !== profile.id)}
            layers={profile.layers}
            activeLayerId={layer?.id}
            onSelect={(id) => { ed.setActiveLayerId(id); setSelectedPos(null); }}
            notice={ed.layerNotice}
            onDismissNotice={() => ed.setLayerNotice(null)}
            {...ed.layerHandlers}
            {...ed.layerFileHandlers}
          />
          <ModuleProfileList bays={bayUI} boardKnown={!!deviceRead && Object.keys(deviceRead).length > 0} />
      </div>
      <div className="editor-main">
        <div className="board-wrap">
          <div className="board-header">
            <div>
              <strong>{layer?.name}</strong>
              <Button
                size="xs"
                variant={ledOutline ? "primary" : "secondary"}
                className="led-toggle"
                style={{ marginLeft: 10 }}
                pressed={ledOutline}
                title={ledOutline
                  ? "Hide LED colors"
                  : "Outline each key in its LED color, so you can see bindings and color groups together"}
                onClick={() => {
                  const next = !ledOutline;
                  setLedOutline(next);
                  try { localStorage.setItem("openflow.ledOutline", next ? "1" : "0"); } catch { /* ignore */ }
                }}
              >
                ◌ LED Colors
              </Button>
            </div>
          </div>
          <BoardFit>
          <KeymapBoard
            keysByPosition={keysByPosition}
            mode="bindings"
            ledOutline={ledOutline}
            selectedPosition={selectedPos}
            onSelectKey={(pos) => { setSelectedPos(pos); setActiveSlot("tap"); }}
            layerMap={layerMap}
            names={catalog?.names || {}}
            moduleAssign={moduleAssign}
            showModulePalette
            onAssignModule={assignModule}
            pickedModule={pickedModule}
            onPickModule={setPickedModule}
            bays={bayUI}
            // Before the board has EVER been read, placing a module by hand is useful:
            // nothing else can know what is docked. After that it is not: a read replaces the
            // whole assignment. Gated on "ever read" rather than "currently known", because a
            // flash clears the detail and that would switch dragging back on after every one.
            allowModuleDrag={!deviceHasBeenRead()}
            onSelectModule={(type, bay) => {
              const id = liveConfigForBay(type, bay);
              navigate(id ? `/module-configuration?config=${id}` : `/module-configuration?type=${type}`);
            }}
          />
          </BoardFit>
        </div>

      {err && <Notice tone="err" style={{ margin: "8px 0" }}>{err}</Notice>}

      <div className="editor-bottom bindings-bottom">
        <SelectedKeyPanel
          label={selectedPos != null ? POS_LABEL[selectedPos] : null}
          bindings={selectedKey?.bindings || {}}
          slots={catalog?.behaviorSlots || []}
          names={catalog?.names || {}}
          activeSlot={activeSlot}
          onSelectSlot={setActiveSlot}
          onClearSlot={clearSlot}
          layerMap={layerMap}
        />
        <ActionPalette
          assigning={keyName ? `${keyName} → ${slotLabel}` : null}
          catalog={catalog}
          layers={profile.layers}
          currentLayerIndex={profile.layers.findIndex((l) => l.id === ed.activeLayerId)}
          macros={macros}
          disabled={selectedPos == null}
          onPick={bind}
        />
      </div>
      </div>
    </div>
  );
}
