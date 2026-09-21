import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api.js";
import Button from "./ui/Button";
import Notice from "./ui/Notice";

// The firmware catalogue, and what of it this machine actually holds.
//
// OpenFlow ships the catalogue -- every image it has classified, by what it targets and which
// NayaFlow release bundled it -- and none of the images. They are Naya's binaries and they would
// put fifteen megabytes of someone else's copyright in the installer. So the list has always
// been able to name a version nobody could flash, and the only way out was an environment
// variable pointing at a tree you had to obtain yourself.
//
// Now each version can be fetched: its files are downloaded from the archive and verified
// against the catalogue's own sha256 before anything is written (backend
// device/firmware_fetch.py). A version is downloaded WHOLE -- both sides, both flash generations
// -- because which of the four a half needs is decided from its product id at flash time, and
// holding three of them is how that decision fails later.
//
// There is no picker dialog. The catalogue list is already grouped by version and already on
// screen, so the button belongs on the group it downloads; "Download all" sits at the top for
// the everything case. A modal listing the same versions a second time would be a worse way to
// say the same thing.

function versionOf(im) {
  return im.versionConfidence === "declared" ? (im.version || im.versionLabel) : null;
}

/** held/total per firmware version, from the backend's join of catalogue against disk. */
export function heldByVersion(images) {
  const out = {};
  for (const im of images || []) {
    if (!im.version) continue;
    const e = (out[im.version] ||= { held: 0, total: 0, bytes: 0 });
    e.total += 1;
    e.bytes += im.bytes || 0;
    if (im.present) e.held += 1;
  }
  return out;
}

export function megabytes(bytes) {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function FirmwareLibrary({ images, onChanged }) {
  const [library, setLibrary] = useState(null);
  const [busy, setBusy] = useState(null);         // the version being fetched, or "all"
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  const reload = useCallback(async () => {
    try {
      setLibrary(await api.firmwareLibrary());
    } catch (e) {
      setError(e.message || String(e));
    }
  }, []);
  useEffect(() => { reload(); }, [reload]);

  const held = heldByVersion(library?.images);
  const missing = Object.entries(held).filter(([, e]) => e.held < e.total);
  const missingBytes = missing.reduce((n, [, e]) => n + e.bytes, 0);
  // "We have not been told yet" is not "there is nothing to download". Without this the button
  // read "All versions downloaded" whenever the backend could not answer -- the most confident
  // possible claim made from no information at all.
  const known = !!library?.images;

  async function download(versions, tag) {
    setBusy(tag);
    setError("");
    setResult(null);
    try {
      const r = await api.fetchFirmware(versions);
      setResult(r);
      await reload();
      // The update dialog resolves against the same directory, so what it can offer just
      // changed.
      onChanged?.();
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setBusy(null);
    }
  }

  const imgs = images || [];
  // One group per distinct firmware: its version number when a NayaFlow release declared one,
  // else the release span that shipped it (the catalogue's versionLabel). Keyboard first,
  // newest release first.
  const label = (im) => im.versionLabel || im.version || "(unknown version)";
  const key = (im) => `${im.target}|${label(im)}`;
  const groups = {};
  for (const im of imgs) (groups[key(im)] ||= []).push(im);
  const order = Object.keys(groups).sort((a, b) => {
    const A = groups[a][0], B = groups[b][0];
    return (A.target === "module") - (B.target === "module")
      || (B.releaseOrder ?? -1) - (A.releaseOrder ?? -1)
      || a.localeCompare(b);
  });
  const ver = (tag) => String(tag || "").replace(/^v/, "");
  const shippedIn = (im) => {
    const b = im.bundles || [];
    if (!b.length) return im.bundle;
    if (b.length === 1) return `NayaFlow ${ver(b[0])}`;
    return `NayaFlow ${ver(b[0])} to ${ver(b[b.length - 1])}, ${b.length} releases`;
  };

  return (
    <>
      <p className="page-sub fw-lib-intro">
        Every firmware image OpenFlow has classified, by what it targets and which NayaFlow
        release bundled it — so a specific version can be picked for an up/downgrade. This is the
        catalogue, not the flasher: use “Update firmware” above, which backs the keyboard up,
        writes one half at a time and verifies the result.
      </p>

      {/* The images are not shipped, so the honest thing is to say where they come from and
          whether that will work from here, next to the button that tries it. */}
      <div className="fw-lib-bar">
        <Button
          onClick={() => download(missing.map(([v]) => v), "all")}
          disabled={!!busy || !known || missing.length === 0}
          busy={busy === "all"}
          title={!known
            ? "Still finding out which images are on this machine"
            : missing.length === 0
            ? "Every catalogued version is already on this machine"
            : `Downloads ${missing.length} version(s) — about ${megabytes(missingBytes)}`}
        >
          {busy === "all" ? "Downloading…"
            : !known ? "Checking what is downloaded…"
            : missing.length === 0 ? "All versions downloaded"
            : `Download all (${missing.length} versions, ${megabytes(missingBytes)})`}
        </Button>
        {library?.dir && <span className="fw-lib-dir">{library.dir}</span>}
      </div>

      {library?.source?.private && (
        <Notice title="The firmware archive is private">
          Images are downloaded from <code>{library.source.url}</code>, which is not public yet,
          so a download will fail unless <code>OPENFLOW_FIRMWARE_TOKEN</code> is set to a token
          that can read it. Every download is checked against the catalogue’s own hash before it
          is kept, wherever it came from.
        </Notice>
      )}
      {error && <Notice tone="err" title="Download failed" onDismiss={() => setError("")}>{error}</Notice>}
      {result && (
        <Notice
          tone={result.failed ? "warn" : "ok"}
          title={result.failed
            ? `${result.fetched} downloaded, ${result.failed} failed`
            : `${result.fetched} image${result.fetched === 1 ? "" : "s"} downloaded`}
          onDismiss={() => setResult(null)}
        >
          {result.failed > 0 && (
            <ul className="fw-lib-failures">
              {result.images.filter((i) => !i.ok).slice(0, 6).map((i) => (
                <li key={i.path}><code>{i.path}</code> — {i.reason}</li>
              ))}
            </ul>
          )}
        </Notice>
      )}

      {order.map((g) => {
        const ims = groups[g];
        const first = ims[0];
        const declared = first.versionConfidence === "declared";
        const kind = first.target === "module" ? "Module" : "Keyboard";
        const title = declared ? `${kind} firmware ${label(first)}` : `${kind} firmware shipped in ${label(first)}`;
        const sub = declared ? shippedIn(first) : "no release declared a version number";
        const v = versionOf(first);
        const h = v ? held[v] : null;
        return (
          <div key={g} className="fw-lib-group">
            <div className="info-sub fw-lib-head">
              <span>{title} <span className="fw-lib-sub">· {sub}</span></span>
              {h && (h.held < h.total ? (
                <Button
                  size="sm"
                  onClick={() => download([v], v)}
                  disabled={!!busy}
                  busy={busy === v}
                  title={`Downloads all ${h.total} files for ${v} — about ${megabytes(h.bytes)}`}
                >
                  {busy === v ? "Downloading…" : `Download (${megabytes(h.bytes)})`}
                </Button>
              ) : (
                <span className="fw-lib-held" title="Every file for this version is on this machine">
                  Downloaded
                </span>
              ))}
            </div>
            {ims.map((im) => (
              <div className="skp-row fw-lib-row" key={`${im.file}-${im.sha256}`} title={im.note || ""}>
                <span className="skp-beh">{im.component || "?"}{im.generation ? ` · gen ${im.generation}` : ""}</span>
                <span className="skp-act fw-lib-file">{im.file}{im.container ? ` in ${im.container}` : ""}</span>
                <span className="v fw-lib-hash">{im.sha256 ? im.sha256 + "…" : "encrypted"}</span>
                <Button
                  disabled
                  className="fw-lib-flag"
                  title={im.flashable
                    ? "Flash this version from “Update firmware” above, which backs up and verifies"
                    : (im.withheldBecause || []).join("; ") || "Not a flashable image"}
                >
                  {im.flashable ? "Flashable" : "—"}
                </Button>
              </div>
            ))}
          </div>
        );
      })}
    </>
  );
}
