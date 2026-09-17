import { Fragment } from "react";
import ActionPalette from "../components/ActionPalette";
import AxisHalfRows from "../components/modules/AxisHalfRows";
import BindingTarget from "../components/modules/BindingTarget";
import GestureRow from "../components/modules/GestureRow";
import ModuleRail from "../components/modules/ModuleRail";
import ModuleSettingsTab from "../components/modules/ModuleSettingsTab";
import ModuleVisual from "../components/modules/ModuleVisual";
import Card from "../components/ui/Card";
import Notice from "../components/ui/Notice";
import Tabs from "../components/ui/Tabs";
import Toggle from "../components/ui/Toggle";
import { deviceStateAt, deviceStateIsStored } from "../lib/deviceState";
import { targetLabel } from "../lib/moduleLabels";
import useModuleEditor from "../lib/useModuleEditor";

// Module configuration (Touch / Track / Tune). The profile rail on the left; the selected
// profile's bindings (module visual + always-on gestures + per-target tabs) and editable
// settings in the centre; the action palette below, aimed at the selected gesture. All the
// data and every mutation live in useModuleEditor; this file is the layout.
export default function Modules() {
  const ed = useModuleEditor();
  const { config, device, onDevice } = ed;

  // A directional gesture is ONE row until it is split, whether its halves are separate
  // bindings (the dial) or the two ends of an axis pair: same row, same checkbox either way.
  function renderGestureRow(b) {
    const pair = ed.pairFor(b.behavior);
    const axis = ed.axisFor(b.behavior);
    if (ed.isPairHalf(b.behavior) && !ed.pairForHalf(b.behavior)?.split) return null;
    const isSplit = axis ? ed.openAxes.has(b.behavior) : !!pair?.split;
    return (
      <Fragment key={b.id}>
        <GestureRow
          labelFor={ed.labelFor}
          dev={ed.deviceByGesture[b.behavior]}
          b={{ ...b, pairedSplit: isSplit }}
          selected={ed.selectedBindingId === b.id}
          onSelect={isSplit ? undefined : ed.setSelectedBindingId}
          extra={(pair || axis) && (
            // The row itself selects for the palette, so a toggle has to stop the click
            // reaching it; otherwise ticking one just selects the row.
            <>
              {/* Track only. Its axes are the ones you hold in your hand and can have
                  backwards; a Tune's scroll direction is a preference the OS already owns.
                  Invert is not a flag on the device (it swaps which selector each half
                  carries), so this is the app's record of a decision, and a read compares
                  the board against it rather than reading it back. */}
              {axis && config?.type === "TRACK" && !isSplit && (
                <Toggle variant="check" className="split-toggle" label="invert"
                  title="Swap which direction each end of this axis drives."
                  checked={!!axis.invert} disabled={!!ed.busy}
                  onClick={(e) => e.stopPropagation()}
                  onChange={(v) => ed.setAxisInvert(b.behavior, v)} />
              )}
              <Toggle variant="check" className="split-toggle" label="split"
                title="Bind each direction separately."
                checked={isSplit} disabled={!!ed.busy}
                onClick={(e) => e.stopPropagation()}
                onChange={(v) => (axis ? ed.toggleAxisSplit(axis, v) : ed.toggleSplit(pair, b, v))} />
            </>
          )} />
        {axis && isSplit && (
          <AxisHalfRows axis={axis} selectedBindingId={ed.selectedBindingId}
            onSelect={ed.setSelectedBindingId} deviceByGesture={ed.deviceByGesture} labelFor={ed.labelFor} />
        )}
      </Fragment>
    );
  }

  return (
    <div className="modules-page">
      {/* The title lives in the rail, as the storyboard sets it; up here only what the last
          read (from the profile bar) or import did, at the right, in space that is there
          whether or not there is a note, so nothing jumps. */}
      <div className="page-head modules-head">
        <div className="board-notes">
          {ed.imported ? (
            <span className={"saved-note" + (ed.imported.skipped ? "" : " ok")}>
              {ed.imported.verb || "Imported"} {ed.imported.name} — {ed.imported.type.toLowerCase()},{" "}
              {ed.imported.bindings} binding(s)
              {ed.imported.skipped > 0 && ` · ${ed.imported.skipped} entry(s) skipped`}
            </span>
          ) : device ? (
            /* Hydrated from the backend's record of the last read. It says AS OF, because
               that is all it can honestly claim: the board may have been unplugged or
               flashed by NayaFlow since. */
            <span className="saved-note">
              {Object.keys(device).length} module(s) on the keyboard
              {deviceStateIsStored() && deviceStateAt()
                ? ` · as of ${deviceStateAt().toLocaleTimeString()}`
                : ""}
            </span>
          ) : null}
        </div>
      </div>
      {ed.err && <Card><Notice tone="err">{ed.err}</Notice></Card>}

      <div className="module-layout">
        <ModuleRail
          grouped={ed.grouped} variants={ed.variants} selectedId={ed.selectedId} onSelect={ed.selectProfile}
          device={device} isLive={ed.isLive} entryFor={ed.entryFor}
          adding={ed.adding} onToggleAdd={() => ed.setAdding((v) => !v)} onAddProfile={ed.addProfile}
          importing={ed.importing} onImport={ed.importProfile}
          renaming={ed.renaming} renameVal={ed.renameVal} onRenameChange={ed.setRenameVal}
          onStartRename={ed.startRename} onCommitRename={ed.commitRename} onCancelRename={ed.cancelRename}
          onExport={ed.exportProfile} onRemove={ed.removeProfile}
        />

        <div className="module-detail">
          {!config ? (
            <div className="empty">No module configurations found.</div>
          ) : (
            <>
              <h2 className="module-title">
                <img className="module-title-img" alt=""
                  src={`/modules/v2/${config.type === "TRACK" ? (config.variant === "TRACK_RIGHT" ? "track-right" : "track-left") : config.type.toLowerCase()}.png`} />
                {config.name}
              </h2>
              <Tabs variant="underline" ariaLabel="Profile sections" value={ed.tab} onChange={ed.setTab}
                items={[{ id: "bindings", label: "Bindings" }, { id: "settings", label: "Settings" }]} />
              {onDevice && (
                <Notice className="module-note">
                  {ed.isLive(config.id)
                    ? `Running on the keyboard as slot ${onDevice.slot}: ${onDevice.fieldCount} fields, everything matches.`
                    : `Edited since the last read — the keyboard is running something else in slot ${onDevice.slot}` +
                      ` (${onDevice.differs} gesture(s) differ).` +
                      (onDevice.matchedName ? ` The board's version is “${onDevice.matchedName}”.` : "")}
                  {onDevice.trailing > 0 &&
                    ` ${onDevice.trailing} trailing field(s) belong to a previous module config — harmless, left alone.`}
                </Notice>
              )}
              {device && !onDevice && (
                <Notice className="module-note">
                  This config is not currently on the keyboard — nothing is flashed for it.
                </Notice>
              )}

              {ed.tab === "bindings" && (
                <div className="module-bindings">
                  <ModuleVisual type={config.type} activeButton={ed.curTarget}
                    side={config.variant === "TRACK_RIGHT" ? "right" : "left"} />
                  <div className="module-rows">
                  {ed.untargeted.length > 0 && (
                    <>
                      <div className="skp-head"><span>Gesture</span><span className="skp-arrow">→</span><span>Action</span></div>
                      {ed.untargeted.map(renderGestureRow)}
                    </>
                  )}

                  {ed.targets.length > 0 && (
                    <>
                      <Tabs variant="underline" ariaLabel="Button or finger" value={ed.curTarget} onChange={ed.setActiveTarget}
                        items={ed.targets.map((t) => ({ id: t, label: targetLabel(t) }))} />
                      {ed.targetBindings.map(renderGestureRow)}
                    </>
                  )}
                  </div>
                </div>
              )}

              {ed.tab === "settings" && (
                <ModuleSettingsTab config={config} onDevice={onDevice} onSetSetting={ed.setSetting} />
              )}
            </>
          )}
        </div>

        {/* Inside the layout grid, in the SAME column as the module content, so the profile
            rail beside it can run the full height of the page instead of stopping where the
            gesture list ends. Always mounted and never keyed: a conditional render or a key
            would remount the palette on every pick and reset its tab back to the virtual
            keyboard. It is only of use on the Bindings tab of a profile, so on Settings (or
            with nothing to edit) it is hidden rather than unmounted. */}
        <div className="editor-bottom modules-bottom" hidden={!config || ed.tab !== "bindings"}>
          <BindingTarget selectedBinding={ed.selectedBinding} name={ed.selectedTargetName}
            labelFor={ed.labelFor} onDone={() => ed.setSelectedBindingId(null)} />
          <ActionPalette
            catalog={ed.catalog}
            context="module"
            disabled={!ed.selectedBinding}
            disabledHint="Select a gesture above to bind it."
            filter={ed.paletteFilter}
            mouseDirections={!!ed.selectedBinding?.axisHalf}
            tabIds={ed.paletteTabIds}
            defaultTab={ed.paletteTabIds && !ed.paletteTabIds.includes("keyboard") ? ed.paletteTabIds[0] : "keyboard"}
            onPick={ed.pickFromPalette}
          />
        </div>
      </div>
    </div>
  );
}
