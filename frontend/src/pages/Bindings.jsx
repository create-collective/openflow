import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { POS_LABEL } from "../lib/layout";
import KeymapBoard from "../components/KeymapBoard";
import LayerList from "../components/LayerList";
import SelectedKeyPanel from "../components/SelectedKeyPanel";
import ActionPalette from "../components/ActionPalette";

export default function Bindings() {
  const [profile, setProfile] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [macros, setMacros] = useState([]);
  const [activeLayerId, setActiveLayerId] = useState(null);
  const [selectedPos, setSelectedPos] = useState(null);
  const [activeSlot, setActiveSlot] = useState("tap");
  const [err, setErr] = useState(null);
  const navigate = useNavigate();

  const load = useCallback(async () => {
    try {
      const [ud, acts, mac] = await Promise.all([api.userdata(), api.actions(), api.macros()]);
      const p = ud.profiles[0] || null;
      setProfile(p);
      setCatalog(acts);
      setMacros(mac.macros || []);
      if (p && p.layers[0]) setActiveLayerId((cur) => cur || p.layers[0].id);
    } catch (e) {
      setErr(e.message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const layer = useMemo(
    () => profile?.layers.find((l) => l.id === activeLayerId) || null,
    [profile, activeLayerId]
  );

  const keysByPosition = useMemo(() => {
    const map = {};
    layer?.keys.forEach((k) => (map[k.positionId] = k));
    return map;
  }, [layer]);

  const selectedKey = selectedPos != null ? keysByPosition[selectedPos] : null;

  const moduleLabels = useMemo(() => {
    // Placeholder module labels; wired to module_config_bindings in Modules work.
    return { left: "Module", right: "Module" };
  }, []);

  async function bind(pick) {
    if (selectedPos == null || !activeLayerId) return;
    try {
      await api.setKeyBinding({
        layerId: activeLayerId,
        positionId: selectedPos,
        actionCode: pick.actionCode,
        actionType: pick.actionType,
        behavior: activeSlot,
      });
      await load();
    } catch (e) {
      setErr(e.message);
    }
  }

  async function clearSlot(slot) {
    if (selectedPos == null || !activeLayerId) return;
    try {
      await api.clearKeyBinding({
        layerId: activeLayerId,
        positionId: selectedPos,
        behavior: slot,
      });
      await load();
    } catch (e) {
      setErr(e.message);
    }
  }

  if (!profile) {
    return (
      <div>
        <h1 className="page-title">Bindings</h1>
        <div className="card">
          <div className="empty">{err || "Loading keymap…"}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="editor">
      <div className="editor-top">
        <LayerList
          profile={profile}
          layers={profile.layers}
          activeLayerId={activeLayerId}
          onSelect={(id) => {
            setActiveLayerId(id);
            setSelectedPos(null);
          }}
        />
        <div className="board-wrap">
          <div className="board-header">
            {profile.layers.findIndex((l) => l.id === activeLayerId)}{"  "}
            <strong>{layer?.name}</strong>
          </div>
          <KeymapBoard
            keysByPosition={keysByPosition}
            mode="bindings"
            selectedPosition={selectedPos}
            onSelectKey={(pos) => {
              setSelectedPos(pos);
              setActiveSlot("tap");
            }}
            onSelectModule={(side) => navigate(`/module-configuration?side=${side}`)}
            moduleLabels={moduleLabels}
          />
        </div>
      </div>

      {err && <div className="phase-note" style={{ margin: "8px 0" }}>{err}</div>}

      <div className="editor-bottom">
        <SelectedKeyPanel
          label={selectedPos != null ? POS_LABEL[selectedPos] : null}
          bindings={selectedKey?.bindings || {}}
          slots={catalog?.behaviorSlots || []}
          activeSlot={activeSlot}
          onSelectSlot={setActiveSlot}
          onClearSlot={clearSlot}
        />
        <ActionPalette
          catalog={catalog}
          layers={profile.layers}
          macros={macros}
          disabled={selectedPos == null}
          onPick={bind}
        />
      </div>
    </div>
  );
}
