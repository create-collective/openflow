import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { POS_LABEL } from "../lib/layout";
import KeymapBoard from "../components/KeymapBoard";
import LayerList from "../components/LayerList";

// LED color palette (from the recovered "Rainbow" palette + an unset/off swatch).
const SWATCHES = [
  null, "#ff0000", "#ff6f00", "#ffe500", "#00ff00", "#00ffd9", "#0000ff", "#6f00ff", "#ffffff",
];

export default function Color() {
  const [profile, setProfile] = useState(null);
  const [activeLayerId, setActiveLayerId] = useState(null);
  const [selectedPos, setSelectedPos] = useState(null);
  const [brush, setBrush] = useState("#00ff00");
  const [err, setErr] = useState(null);

  const load = useCallback(async () => {
    try {
      const ud = await api.userdata();
      const p = ud.profiles[0] || null;
      setProfile(p);
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

  async function paint(positionId) {
    setSelectedPos(positionId);
    if (!activeLayerId) return;
    try {
      await api.setKeyColor({ layerId: activeLayerId, positionId, colorHex: brush });
      await load();
    } catch (e) {
      setErr(e.message);
    }
  }

  if (!profile) {
    return (
      <div>
        <h1 className="page-title">Color</h1>
        <div className="card"><div className="empty">{err || "Loading…"}</div></div>
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
          onSelect={(id) => setActiveLayerId(id)}
        />
        <div className="board-wrap">
          <div className="board-header">
            <strong>{layer?.name}</strong> — LED view
          </div>
          <KeymapBoard
            keysByPosition={keysByPosition}
            mode="color"
            selectedPosition={selectedPos}
            onSelectKey={paint}
          />
        </div>
      </div>

      {err && <div className="phase-note" style={{ margin: "8px 0" }}>{err}</div>}

      <div className="card" style={{ maxWidth: 520 }}>
        <h3>LED Color Palette</h3>
        <p className="page-sub" style={{ marginBottom: 12 }}>
          Pick a color, then click keys to paint. The off swatch clears a key's color.
        </p>
        <div className="swatches">
          {SWATCHES.map((c, i) => (
            <button
              key={i}
              className={"swatch" + (brush === c ? " active" : "") + (c ? "" : " off")}
              style={c ? { background: c } : undefined}
              onClick={() => setBrush(c)}
              title={c || "Off"}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
