import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { POS_LABEL } from "../lib/layout";
import KeymapBoard from "../components/KeymapBoard";
import LayerList from "../components/LayerList";
import SelectedKeyPanel from "../components/SelectedKeyPanel";
import ActionPalette from "../components/ActionPalette";

export default function Bindings() {
  const [profile, setProfile] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [activeLayerId, setActiveLayerId] = useState(null);
  const [selectedPos, setSelectedPos] = useState(null);
  const [err, setErr] = useState(null);

  const load = useCallback(async () => {
    try {
      const [ud, acts] = await Promise.all([api.userdata(), api.actions()]);
      const p = ud.profiles[0] || null;
      setProfile(p);
      setCatalog(acts);
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

  async function bind(pick) {
    if (selectedPos == null || !activeLayerId) return;
    try {
      await api.setKeyBinding({
        layerId: activeLayerId,
        positionId: selectedPos,
        actionCode: pick.actionCode,
        actionType: pick.actionType,
        behavior: "press",
      });
      await load();
    } catch (e) {
      setErr(e.message);
    }
  }

  async function clearBinding() {
    if (selectedPos == null || !activeLayerId) return;
    try {
      await api.clearKeyBinding({ layerId: activeLayerId, positionId: selectedPos });
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
            onSelectKey={setSelectedPos}
          />
        </div>
      </div>

      {err && <div className="phase-note" style={{ margin: "8px 0" }}>{err}</div>}

      <div className="editor-bottom">
        <SelectedKeyPanel
          label={selectedPos != null ? POS_LABEL[selectedPos] : null}
          binding={selectedKey?.binding}
          onClear={clearBinding}
        />
        <ActionPalette
          catalog={catalog}
          layers={profile.layers}
          disabled={selectedPos == null}
          onPick={bind}
        />
      </div>
    </div>
  );
}
