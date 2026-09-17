import Button from "../ui/Button";
import Notice from "../ui/Notice";
import SettingField from "../SettingField";

// A module profile's settings, each on the shared SettingField. `writable` is this schema's
// word for the same thing `provenance` says on the Settings page: a field we have capture
// evidence for is flashed, one we do not is app-only. What the keyboard holds for a setting
// (from the last read of the slot this profile is on) is shown, never silently adopted: a
// differing board value comes with one click to take it.
export default function ModuleSettingsTab({ config, onDevice, onSetSetting }) {
  return (
    <div className="module-settings">
      {config.settingsSchema.map((f) => {
        const live = (onDevice?.settings || []).find((x) => x.id === f.id);
        return (
          <div key={f.id}>
            <SettingField
              f={{ ...f, provenance: f.writable === false ? "app" : "verified" }}
              onChange={onSetSetting} />
            {live && live.differs && (
              <Notice className="module-setting-live">
                On the keyboard: <strong>{String(live.device)}</strong>
                <Button className="module-setting-take"
                  onClick={() => onSetSetting(f.id, live.device)}
                  title="Set this profile's value to what the keyboard holds.">
                  Use the keyboard's value
                </Button>
              </Notice>
            )}
          </div>
        );
      })}
    </div>
  );
}
