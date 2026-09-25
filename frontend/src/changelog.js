// What changed, per version, newest first. The Hub shows the entry for the running version
// (or the newest one). Written for the person using the keyboard, not for the commit log:
// what they can now do, what stopped happening.
const CHANGELOG = [
  {
    version: "0.4.0",
    date: "2026-09-25",
    notes: [
      "Home-row mods type in order. A key with a tap and a hold was written in the keyboard's four-behaviour form, which holds the tap back, so on fast typing the next letter came out first (\"efw\" for \"few\") or a letter went missing. It is now written the way NayaFlow writes it, and fast typing comes out clean.",
      "Interrupt Flavor does what the settings page says. With nothing chosen it shows Balanced, and Balanced is now what reaches the keyboard; before, an unset flavour went out as Hold-Preferred, which turns home-row keys into modifiers on fast rolls.",
      "A double-tap OpenFlow cannot write yet is left on the keyboard and named in the flash report. It used to be erased without a word, so a double-tap set in NayaFlow could disappear on the first flash from OpenFlow.",
      "Pinch and Spread are labelled as such when you split them, instead of - and +. A pair such as Volume set on pinch & spread without splitting it now flashes as that pair; it used to flash as zoom whatever you chose. Screen Brightness is offered as a pair too.",
      "Importing a module profile file, such as a Create Companion export, gives you every gesture the module has, with the file's bindings in place of the defaults. A split dial in the file lands on the dial's two directions.",
      "Interface scaling keeps the value you set. On the Bindings and LED Map pages the layers column can be hidden, so the keyboard picture gets the room, and the picture no longer shrinks more than it should as the interface is enlarged.",
      "Module profiles named \"(on board)\" say what that means: a copy kept from a read that matched none of your saved profiles.",
      "Behind the scenes: module firmware updates, a guided repair for halves that no longer connect, and recovery for a half left in the bootloader. These stay held back in this build, like the keyboard firmware update.",
    ],
  },
  {
    version: "0.3.1",
    date: "2026-09-22",
    notes: [
      "A key that holds for a layer (the stock Enter and Backspace, or any thumb key you set that way) reads back as exactly that and flashes back exactly as it was, instead of showing a RAW value and being left out of the flash.",
      "Double-tap works on a key that has no Hold set. Tap plus Double-tap alone used to fire the tap twice; the key is now written the way the keyboard needs to notice a second tap.",
      "When a binding cannot be written, the flash report names the binding that actually failed and says why in the encoder's own words, rather than blaming the key's tap.",
      "A flash no longer reports failure on layers it correctly did not need to write, and the multi-behaviour star sits on its own key rather than drifting onto a neighbour or the module bay on the right half.",
      "Naya Touch profiles show their picture in the title bar again.",
      "Settings has a Firmware tab that shows what each half is running and which versions exist, and an About tab about OpenFlow itself. Updating the firmware from it is held back for now.",
    ],
  },
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
