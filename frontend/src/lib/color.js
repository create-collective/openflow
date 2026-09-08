// Small HSV/hex helpers for the LED color creator (hue 0-360, sat 0-100, full value).

export function hsvToHex(h, s, v = 100) {
  s /= 100; v /= 100;
  const c = v * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = v - c;
  let r = 0, g = 0, b = 0;
  if (h < 60) [r, g, b] = [c, x, 0];
  else if (h < 120) [r, g, b] = [x, c, 0];
  else if (h < 180) [r, g, b] = [0, c, x];
  else if (h < 240) [r, g, b] = [0, x, c];
  else if (h < 300) [r, g, b] = [x, 0, c];
  else [r, g, b] = [c, 0, x];
  const to = (n) => Math.round((n + m) * 255).toString(16).padStart(2, "0");
  return `#${to(r)}${to(g)}${to(b)}`;
}

export function isValidHex(s) {
  return /^#[0-9a-fA-F]{6}$/.test(s);
}

// --- what the keyboard can actually store ------------------------------------------------- //
// The LED record is [led][hue u16][SATURATION]. Not brightness.
//
// This was wrong in both directions until 2026-09-08 and it is worth stating plainly, because
// the previous version of this file confidently asserted the opposite: we thought the third byte
// was brightness and that saturation was unstorable, so white "had" to flash as red. It flashed
// as red because WE WROTE brightness 100 into a saturation field.
//
// Established by flashing from NayaFlow and reading the board back. Against NayaFlow's own
// database, 17 of 18 colour classes across three layers match, including all 40 white keys:
//     #ffffff -> (hue 0, sat 0)      #ff0000 -> (hue 0, sat 100)     #21ffaa -> (157, 87)
//
// So the map is lossy in BRIGHTNESS, not saturation: #808080 and #ffffff both store as (0, 0),
// and the keyboard shows both at whatever the global brightness is. That is why the board has
// LED_BRIGHTNESS_UP/DOWN keys -- brightness is a device-wide setting, not a per-key one.

/** Python's round(): rounds half to EVEN, which Math.round does not. */
function pyRound(x) {
  const f = Math.floor(x), dd = x - f;
  if (dd > 0.5) return f + 1;
  if (dd < 0.5) return f;
  return f % 2 === 0 ? f : f + 1;
}

/** hex -> the (hue, saturation) the device stores. Mirrors keymap_read.hex_to_hue_sat. */
export function hexToHueSat(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b);
  const d = mx - mn;
  if (d === 0 || mx === 0) return [0, 0];      // any grey, white included
  let h;
  if (mx === r) {
    // `(x % 6 + 6) % 6` would be the tidy way to keep this non-negative and it is WRONG here:
    // adding 6 to a small float and subtracting it again destroys the low bits, turning an exact
    // 20.0 into 19.999999999999982, which then truncates to 19. Python's float `%` is already
    // non-negative for a positive modulus, so only a genuinely negative value needs adjusting --
    // and `x + 6` there is the same single operation Python performs.
    let x = ((g - b) / d) % 6;
    if (x < 0) x += 6;
    h = 60 * x;
  } else if (mx === g) {
    h = 60 * (2 + (b - r) / d);
  } else {
    h = 60 * (4 + (r - g) / d);
  }
  // TRUNCATED, on raw 0-255 ints. Going through 0..1 floats and rounding puts #0084ff on hue
  // 209 where the device stores 208.
  return [((Math.trunc(h) % 360) + 360) % 360, Math.trunc((d / mx) * 100)];
}

/** (hue, saturation) -> hex at FULL brightness, since brightness is not per-key. */
export function hueSatToHex(hueDeg, saturation) {
  const h = ((((hueDeg % 360) + 360) % 360)) / 360;
  const s = Math.max(0, Math.min(100, saturation)) / 100;
  const i = Math.floor(h * 6), f = h * 6 - i;
  const p = 1 - s, q = 1 - s * f, t = 1 - s * (1 - f);
  const rgb = [[1, t, p], [q, 1, p], [p, 1, t], [p, q, 1], [t, p, 1], [1, p, q]][((i % 6) + 6) % 6];
  return "#" + rgb.map((n) => pyRound(n * 255).toString(16).padStart(2, "0")).join("");
}

/**
 * What a colour will look like ON THE KEYBOARD after a flash.
 * null for "off", else { hex, hue, saturation, exact }. `exact` means the board reproduces the
 * chosen colour -- true for every fully-bright colour, false where brightness would be lost.
 */
export function deviceColor(hex) {
  if (!hex || !isValidHex(hex)) return null;
  const [hue, saturation] = hexToHueSat(hex);
  const out = hueSatToHex(hue, saturation);
  return { hex: out, hue, saturation, exact: out.toLowerCase() === hex.toLowerCase() };
}
