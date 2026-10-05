// What changed, per version, newest first. The Hub shows the entry for the running version
// (or the newest one). Written for the person using the keyboard, not for the commit log:
// what they can now do, what stopped happening.
const CHANGELOG = [
  {
    version: "0.6.0",
    date: "2026-10-05",
    notes: [
      "A bug report can carry screenshots: attach them, or paste one anywhere on the report page (Win+Shift+S, then Ctrl+V). Up to five images go to the issue with the report.",
      "Devices › Troubleshooting has a split-link check for a right half that will not connect. It reads both halves and says what to do first: plug both in, update the half on older firmware, or run the guided split-link repair, which the check opens for you.",
      "The pairing check now looks at each half's bond list as well as the address it points at, so two halves that point at each other but are not actually bonded no longer read as paired.",
      "Read settings replaces Dump settings, which returned nothing on current firmware. It shows what the selected half reports: firmware, Bluetooth addresses and bonds, battery and module. Timeouts, host OS and LED brightness can be set but not read back from the keyboard.",
      "The battery reads 100% when the keyboard is full, on any firmware.",
      "A module profile still used by a layer can be deleted anyway, or the warning dismissed.",
      "With LED Colors on in light mode, a key with a white LED keeps a gray edge instead of disappearing into the board.",
      "The Hub links the create-collective organization on GitHub, the Create Knowledge Base and Create Companion. About links the source for OpenFlow, Create Companion and the legacy firmware.",
      "All text in the app uses American spelling.",
      "Keyboard firmware updates, the guided split-link repair and recovery tools stay held back in this build.",
    ],
  },
  {
    version: "0.5.0",
    date: "2026-09-26",
    notes: [
      "Keys with a double-tap, hold or tap+hold are written the way NayaFlow writes them, in far fewer bytes, and NayaFlow can read them back. A key set up in NayaFlow no longer shows a RAW value: it reads as what it does (LALT + F4, say) and flashes back unchanged instead of being left out.",
      "Any of the four behaviors can hold any action, not only a key: a layer switch or a Bluetooth device can be a double-tap, and a key that switches layers on tap can have a double-tap too. A behavior set to Disabled shows as Disabled, and one OpenFlow cannot write is kept on the keyboard rather than erased.",
      "Module profiles stop piling up \"(on board)\" copies. A profile you flash and read back without editing it matches itself; before, many came back as a new copy on every read, and even straight after a flash.",
      "What you pick for an axis is what gets written. Choosing Vertical Scroll (or any motion) for pinch & spread or a swipe used to write the axis's default motion whatever you chose; clearing an axis now leaves it empty, and a key pair on an inverted axis comes out the right way round.",
      "Keyboard LED brightness works on the Tune. Any gesture can raise or lower the backlight, a swipe one step at a time, and the new Keyboard LED Brightness pair makes pinch and spread dim and brighten smoothly. Picking an LED action used to write nothing, so the gesture kept its old binding. NayaFlow's own LED swipes never worked; they are still recognized on a read, and the next flash from OpenFlow replaces them with ones that do.",
      "Pinch & spread starts empty, as it does in NayaFlow. Zoom is one pick away, and profiles already set to zoom keep it.",
      "Flashing no longer asks you to read the keyboard first: the flash reads it itself. Module slots the profile does not use are removed on every flash, as NayaFlow does, and the preview lists which ones.",
      "Shortcuts with two names (Page Up and PG_UP, Enter and Return) no longer count as a change, and a copy of a copy is named \"(on board) 2\" rather than \"(on board) (on board)\".",
    ],
  },
  {
    version: "0.4.0",
    date: "2026-09-25",
    notes: [
      "Home-row mods type in order. A key with a tap and a hold was written in the keyboard's four-behavior form, which holds the tap back, so on fast typing the next letter came out first (\"efw\" for \"few\") or a letter went missing. It is now written the way NayaFlow writes it, and fast typing comes out clean.",
      "Interrupt Flavor does what the settings page says. With nothing chosen it shows Balanced, and Balanced is now what reaches the keyboard; before, an unset flavor went out as Hold-Preferred, which turns home-row keys into modifiers on fast rolls.",
      "A double-tap OpenFlow cannot write yet is left on the keyboard and named in the flash report. It used to be erased without a word, so a double-tap set in NayaFlow could disappear on the first flash from OpenFlow.",
      "Pinch and Spread are labeled as such when you split them, instead of - and +. A pair such as Volume set on pinch & spread without splitting it now flashes as that pair; it used to flash as zoom whatever you chose. Screen Brightness is offered as a pair too.",
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
      "A flash no longer reports failure on layers it correctly did not need to write, and the multi-behavior star sits on its own key rather than drifting onto a neighbor or the module bay on the right half.",
      "Naya Touch profiles show their picture in the title bar again.",
      "Settings has a Firmware tab that shows what each half is running and which versions exist, and an About tab about OpenFlow itself. Updating the firmware from it is held back for now.",
    ],
  },
  {
    version: "0.3.0-beta.2",
    date: "2026-09-19",
    notes: [
      "Pinch and spread are two separate gestures on the Touch and the Tune, and together they are a zoom axis: pinch to zoom out, spread to zoom in, as smooth motion rather than repeated keystrokes. Split them and each direction can do something of its own.",
      "Commands meant for the right half reach the right half. Reading, flashing, the LED buttons and the diagnostics could all act on the left instead when the right was not recognized, with nothing said about it.",
      "Flashing no longer fails because of one key. A binding that cannot be written is named, with what the key will keep doing, and everything else still flashes.",
      "A key set only to tap stops coming back as tap and hold after a read, and stops re-creating itself every time you flash.",
      "A keyboard that shows up on more than one COM port is handled: OpenFlow uses the port that answers, shows both halves once each, and lets you ignore a port left behind by a disconnect.",
      "Shortcut names say what the chord does on the tab you found it under, so a Windows chord is no longer labeled with a macOS action. Thirteen everyday shortcuts were added and four of our own names corrected.",
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
      "Settings: what the keyboard really stores for multi-behavior keys is the tapping term and the interrupt flavor; the timings with no firmware mapping are listed but inert.",
    ],
  },
  {
    version: "0.1.0",
    date: "2026-09-17",
    notes: [
      "OpenFlow runs as a desktop app: a Windows installer and a portable build, with the backend bundled and your profiles seeded on first run.",
      "Light and dark themes, following the OS or your choice from the switch in the top bar.",
      "Bindings redrawn: the selected key and its behaviors in a band under the board, the action palette with every F key on one row, the Layers and Module profiles cards.",
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
