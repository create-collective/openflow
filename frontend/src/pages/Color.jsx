import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { hsvToHex, isValidHex, deviceColor } from "../lib/color";
import useProfileEditor from "../lib/useProfileEditor";
import BoardFit from "../components/BoardFit";
import RailColumn from "../components/RailColumn";
import KeymapBoard from "../components/KeymapBoard";
import LayerList from "../components/LayerList";
import Button from "../components/ui/Button";
import Card from "../components/ui/Card";
import Notice from "../components/ui/Notice";

// Base swatches (recovered "Rainbow" palette + off). Users add custom colors.
const BASE_SWATCHES = [
  null, "#ff0000", "#ff6f00", "#ffe500", "#00ff00", "#00ffd9", "#0000ff", "#6f00ff", "#ffffff",
];
// ZMK-style RGB animations NayaFlow exposed.
// The device's own animation enum, byte 2 of each layer-list entry. Order matters: it is the
// same table the LED keypress records use (keymap_read.LAYER_ANIMATIONS), confirmed against a
// probe board carrying a different effect on each layer.
const ANIMATIONS = [
  { id: "solid", label: "Solid" },
  { id: "breathe", label: "Breathe" },
  { id: "swirl", label: "Swirl" },
  { id: "spectrum", label: "Spectrum" },
];
const TOOLS = [
  { id: "brush", label: "Brush", icon: "🖌" },
  { id: "fill", label: "Fill", icon: "🪣" },
  { id: "pipette", label: "Pipette", icon: "💧" },
];

// The LED map: the same layers and board as Bindings, painted instead of bound. Profiles,
// layers and their handlers come from useProfileEditor (shared with Bindings); the profile
// menu and Flash are in the shell's profile bar. What stays here is the painting: the brush,
// the tool, the swatches and the colour creator.
export default function Color() {
  const ed = useProfileEditor();
  const { profile, layer, keysByPosition, layerMap } = ed;
  const [brush, setBrush] = useState("#00ff00");
  const [tool, setTool] = useState("brush");
  const [swatches, setSwatches] = useState(BASE_SWATCHES);
  // Custom color creator state
  const [showCreator, setShowCreator] = useState(false);
  const [hue, setHue] = useState(120);
  const [sat, setSat] = useState(100);
  const [hex, setHex] = useState("#00ff00");
  // The action catalogue, purely for its `names`: KeymapBoard needs it to draw NayaFlow's
  // keycap icons. Without it `names` defaults to {} and every cap silently falls back to its
  // text legend, which is why this board used to render in a different face and size from the
  // identical board on Bindings.
  const [names, setNames] = useState({});

  useEffect(() => {
    let alive = true;
    api.actions().then((acts) => { if (alive) setNames(acts?.names || {}); }).catch(() => {});
    return () => { alive = false; };
  }, []);

  // What the BOARD will look like after a flash. The device stores hue + SATURATION and no
  // per-key brightness, so every fully-bright colour survives exactly and dark ones come back
  // at full brightness (#808080 -> white, #800000 -> red). keysByPosition is left alone so the
  // pipette picks up the colour the user chose, not the approximation.
  const boardKeys = useMemo(() => {
    const out = {};
    for (const [pos, k] of Object.entries(keysByPosition)) {
      const dev = deviceColor(k.colorHex);
      out[pos] = dev ? { ...k, colorHex: dev.hex } : k;
    }
    return out;
  }, [keysByPosition]);

  const brushDevice = deviceColor(brush);

  // Resolved once per swatch rather than three times per swatch per render, and, more to the
  // point, `deviceColor` returns null for anything that is not a valid hex, so calling it inline
  // in both the title and the chip meant one bad swatch value would throw and blank the page.
  const swatchViews = useMemo(
    () => swatches.map((c) => ({ c, dev: deviceColor(c) })),
    [swatches]
  );

  async function onKey(positionId) {
    if (!layer) return;
    try {
      if (tool === "pipette") {
        const c = keysByPosition[positionId]?.colorHex;
        if (c) { setBrush(c); setHex(c); }
        return;
      }
      const value = brush;
      if (tool === "fill") {
        await api.fillLayerColor({ layerId: layer.id, colorHex: value });
      } else {
        await api.setKeyColor({ layerId: layer.id, positionId, colorHex: value });
      }
      await ed.reload();
    } catch (e) {
      ed.setErr(e.message);
    }
  }

  function applyCreator(fromHsv) {
    const val = fromHsv ? hsvToHex(hue, sat) : hex;
    if (!isValidHex(val)) return;
    if (fromHsv) setHex(val);
    setBrush(val);
  }

  function addSwatch() {
    if (isValidHex(brush) && !swatches.includes(brush)) setSwatches([...swatches, brush]);
    setShowCreator(false);
  }

  // The docked modules' LED blocks. The left block sits inside the key range so it was already
  // reachable by painting keys; the right has no key position at all, which is why a flash used
  // to leave the right module showing whatever wrote it last. See flash.MODULE_LED_BLOCKS.
  async function paintModule(side) {
    if (tool === "pipette") {
      const c = layer?.moduleLed?.[side];
      if (c) { setBrush(c); setHex(c); }
      return;
    }
    await setModuleLed(side, brush);
  }

  async function setModuleLed(side, colorHex) {
    if (!layer) return;
    try {
      await api.setModuleLed({ layerId: layer.id, side, colorHex });
      await ed.reload();
    } catch (e) { ed.setErr(e.message); }
  }

  async function setAnimation(anim) {
    if (!layer) return;
    try {
      await api.setLayerAnimation({ layerId: layer.id, animation: anim });
      await ed.reload();
    } catch (e) { ed.setErr(e.message); }
  }

  if (!profile) {
    return <div><h1 className="page-title">LED Map</h1><Card><div className="empty">{ed.error || "Loading…"}</div></Card></div>;
  }

  return (
    // The same two containers as Bindings: the Layers card on the left, the board with its two
    // cards under it on the right, each stacking on its own.
    <div className="editor editor-split">
      <RailColumn>
          <LayerList
            profiles={ed.profiles.filter((p) => p.id !== profile.id)}
            layers={profile.layers}
            activeLayerId={layer?.id}
            onSelect={(id) => ed.setActiveLayerId(id)}
            notice={ed.layerNotice}
            onDismissNotice={() => ed.setLayerNotice(null)}
            {...ed.layerHandlers}
            {...ed.layerFileHandlers}
          />
      </RailColumn>
      <div className="editor-main">
        <div className="board-wrap">
          <div className="board-header">
            <div>
              <strong>{layer?.name}</strong> — LED view
              <span className="page-sub" style={{ marginLeft: 8 }}>
                shown as the keyboard will light it
              </span>
            </div>
          </div>
          <BoardFit>
            <KeymapBoard keysByPosition={boardKeys} mode="color" onSelectKey={onKey} layerMap={layerMap}
              names={names} moduleLed={layer?.moduleLed} onModuleLed={paintModule} />
          </BoardFit>
        </div>

      {ed.error && <Notice tone="err" style={{ margin: "8px 0" }}>{ed.error}</Notice>}

      <div className="editor-bottom color-bottom">
        <div>
          <Card title="LED Mapping Tools">
            <div className="btn-row">
              {TOOLS.map((t) => (
                <Button key={t.id} variant={tool === t.id ? "primary" : "secondary"} onClick={() => setTool(t.id)}>
                  {t.icon} {t.label}
                </Button>
              ))}
            </div>
          </Card>

          <Card title="LED Color Palette">
            <p className="page-sub" style={{ marginBottom: 10 }}>
              The keyboard stores a hue and a saturation — <strong>brightness is a keyboard-wide
              setting</strong>, not per key. So pale colors and white come out exactly as
              picked, while dark ones light up at full brightness. The board above shows the
              real result.
            </p>
            <div className="swatches">
              {swatchViews.map(({ c, dev }, i) => (
                <button
                  key={i}
                  type="button"
                  className={"swatch" + (brush === c ? " active" : "") + (c ? "" : " off")}
                  style={c ? { background: c } : undefined}
                  onClick={() => { setBrush(c); if (c) setHex(c); }}
                  title={!c ? "Off" : dev && !dev.exact ? `${c} — lights up as ${dev.hex}` : c}
                >
                  {dev && !dev.exact && (
                    <span className="swatch-dev" style={{ background: dev.hex }} />
                  )}
                </button>
              ))}
              <button type="button" className="swatch add" title="Create color" onClick={() => setShowCreator((v) => !v)}>+</button>
            </div>

            {showCreator && (
              <div className="color-creator">
                <label>Hue: {hue}
                  <input type="range" min="0" max="360" value={hue}
                    onChange={(e) => { setHue(+e.target.value); }} onInput={() => applyCreator(true)} />
                </label>
                <label>Saturation: {sat}
                  <input type="range" min="0" max="100" value={sat}
                    onChange={(e) => { setSat(+e.target.value); }} onInput={() => applyCreator(true)} />
                </label>
                <div className="creator-row">
                  <div className="creator-preview" title="The color you picked"
                    style={{ background: isValidHex(hex) ? hex : "#000" }} />
                  <span className="creator-arrow" aria-hidden="true">→</span>
                  <div className="creator-preview" title="How the keyboard will light it"
                    style={{ background: brushDevice ? brushDevice.hex : "#000" }} />
                  <input className="mac-input" value={hex}
                    onChange={(e) => setHex(e.target.value)}
                    onBlur={() => applyCreator(false)} />
                  <Button onClick={() => applyCreator(true)}>Use HSV</Button>
                  <Button variant="primary" onClick={addSwatch}>Add swatch</Button>
                </div>
                {brushDevice && (
                  <p className="page-sub" style={{ marginTop: 6 }}>
                    {brushDevice.exact
                      ? `The keyboard can show this exactly — hue ${brushDevice.hue}°, saturation ${brushDevice.saturation}%.`
                      : `Stored as hue ${brushDevice.hue}°, saturation ${brushDevice.saturation}% — the keyboard has no per-key brightness, so it will light up ${brushDevice.hex}.`}
                  </p>
                )}
              </div>
            )}
          </Card>
        </div>

        <Card title="Animations">
          {/* This card really was app-only until 2026-09-08, and the reason it looked that way
              is worth keeping: the animation is byte 2 of the layer's entry in the DEVICE'S LAYER
              LIST, and every board we had ever captured was set to solid on every layer, so the
              byte read 0x00 everywhere we looked and sat in the parser as an unnamed constant.
              Worse, the encoder hardcoded 0x00, so any flash that wrote the layer list silently
              reset all three layers to solid. A probe profile with a different effect per layer
              is what exposed it. */}
          <p className="page-sub" style={{ marginBottom: 12 }}>
            Per-layer, and written to the keyboard.
          </p>
          <div className="anim-list">
            {ANIMATIONS.map((a) => (
              <button
                key={a.id || "none"}
                type="button"
                className={"anim-item" + ((layer?.animationId || null) === a.id ? " active" : "")}
                onClick={() => setAnimation(a.id)}
              >
                {a.label}
              </button>
            ))}
          </div>
        </Card>
      </div>
      </div>
    </div>
  );
}
