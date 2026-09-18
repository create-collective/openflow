// What changed, per version, newest first. The Hub shows the entry for the running version
// (or the newest one). Written for the person using the keyboard, not for the commit log:
// what they can now do, what stopped happening.
const CHANGELOG = [
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
