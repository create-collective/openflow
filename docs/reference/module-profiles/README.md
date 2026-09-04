# Module profile files

The interchange format for a Naya Create module profile — what the Modules page's
**Import…** button reads and what an export writes.

| File | What it is |
|---|---|
| `module-profile.schema.json` | JSON Schema for the format, with every field documented |
| `naya-touch-windows.json` | A real TOUCH profile (17 gestures, 3 settings) |
| `naya-track-left.json` | A real TRACK profile (11 gestures) |
| `naya-tune-mac-win.json` | A real TUNE profile (17 gestures, 1 setting) |

The three examples are exports of the stock profiles of that name, so they double as the
reference for what each module can express.

## The shape

```json
{
  "format": "openflow.module-profile",
  "version": 1,
  "moduleType": "TUNE",
  "name": "Naya Tune Mac/Win",
  "variant": "TUNE",
  "settings": { "pointer_accel_on": "true" },
  "bindings": {
    "tap:tune:1_finger":  { "actionType": "key",   "actionCode": "F22" },
    "rotate:tune:dial":   { "actionType": "value", "actionCode": "C_VOL_DOWN - C_VOL_UP" }
  }
}
```

**`moduleType` is required**, and it is the field the importer reads first. It decides which
section of the module list the profile lands in, and it is never inferred: Touch and Tune share
gesture names, so a guess would quietly file the profile under the wrong module. A document
without it is refused, as is one whose gestures all belong to some other module type — that
combination almost always means `moduleType` is wrong rather than that the gestures are.

## Direction pairs

Some gestures are a PAIR of directions over two device fields: the motion axes, and the Tune
dial. They are one entry whose `actionCode` names both directions, minus first:

    "mouse - SCROLL_UP - SCROLL_DOWN"     a motion axis
    "C_VOL_DOWN - C_VOL_UP"               the dial (the leading kind is optional)

The **last two** parts are the two directions, which is what lets both spellings parse.

Bind the halves independently and they appear under `split`, with the combined code still
naming the pair:

```json
"vertical:tune:1_finger": {
  "actionType": "value",
  "actionCode": "mouse - SCROLL_UP - SCROLL_DOWN",
  "split": {
    "-": { "actionType": "key", "actionCode": "F18" },
    "+": { "actionType": "key", "actionCode": "F17" }
  }
}
```

`-` is left, up, or counter-clockwise; `+` is right, down, or clockwise.

## Importing

An import is always a **new** profile — never an overwrite — and a name that collides is
numbered. Importing the same file twice leaves you two profiles to compare rather than
silently replacing the one you had.

Gestures the module does not have are ignored and reported in `skipped`.
