// What changed, per version, newest first. The Hub shows the entry for the running version
// (or the newest one). Written for the person using the keyboard, not for the commit log:
// what they can now do, what stopped happening.
const CHANGELOG = [
  {
    version: "0.3.0-beta.2",
    date: "2026-09-19",
    notes: [
      "Pinch and spread are two separate gestures on the Touch and the Tune, and together they are a zoom axis: pinch to zoom out, spread to zoom in, as smooth motion rather than repeated keystrokes. Split them and each direction can do something of its own.",
      "Commands meant for the right half reach the right half. Reading, flashing, the LED buttons and the diagnostics could all act on the left instead when the right was not recognised, with nothing said about it.",
      "Flashing no longer fails because of one key. A binding that cannot be written is named, with what the key will keep doing, and everything else still flashes.",
      "A key set only to tap stops coming back as tap and hold after a read, and stops re-creating itself every time you flash.",
      "A keyboard that shows up on more than one COM port is handled: OpenFlow uses the port that answers, shows both halves once each, and lets you ignore a port left behind by a disconnect.",
      "Shortcut names say what the chord does on the tab you found it under, so a Windows chord is no longer labelled with a macOS action. Thirteen everyday shortcuts were added and four of our own names corrected.",
    ],
  },
  {
    version: "0.2.0",
    date: "2026-09-17",
    notes: [
      "Every page restyled: the profile bar, Modules, Macros, Settings and Devices, in both themes.",
      "Report a problem, under More: it collects what OpenFlow knows about your machine, shows you exactly what it will send, and strips hardware identifiers unless you ask for them.",
      "Messages are quieter and clearer: a badge for status, a short notice for a limitation with the technical why behind Details, and a tinted warning only for something that failed.",
      "Modules: a gesture can be cleared with an x rather than only overwritten, the palette sits under the profile it edits, and the action list is readable.",
      "Flash to keyboard is offered on the pages that change what gets written, and its preview says what will be written before you confirm.",
      "Settings: what the keyboard really stores for multi-behaviour keys is the tapping term and the interrupt flavour; the timings with no firmware mapping are listed but inert.",
    ],
  },
  {
    version: "0.1.0",
    date: "2026-09-17",
    notes: [
      "OpenFlow runs as a desktop app: a Windows installer and a portable build, with the backend bundled and your profiles seeded on first run.",
      "Light and dark themes, following the OS or your choice from the switch in the top bar.",
      "Bindings redrawn: the selected key and its behaviours in a band under the board, the action palette with every F key on one row, the Layers and Module profiles cards.",
      "Read from keyboard, Back up and Flash to keyboard are on every page, with both halves and their modules in the bar.",
      "A read never blanks the module bays, and a bay only ever names a profile of its own type.",
    ],
  },
];

export default CHANGELOG;

/** The entry for a version, else the newest. */
export function notesFor(version) {
  return CHANGELOG.find((e) => e.version === version) || CHANGELOG[0];
}
