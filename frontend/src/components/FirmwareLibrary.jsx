import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api.js";
import Button from "./ui/Button";
import Notice from "./ui/Notice";

// The firmware catalogue, and what of it this machine holds.
//
// OpenFlow ships the catalogue -- every image it has classified, by what it targets and which
// NayaFlow release bundled it -- and none of the images. They are Naya's binaries and they would
// put fifteen megabytes of someone else's copyright in the installer. So each version is fetched
// on demand from the archive and checked against the catalogue's own sha256 before anything is
// written (backend device/firmware_fetch.py).
//
// A version downloads WHOLE -- both sides, both flash generations -- because which of the four a
// half needs is decided from its product id at flash time, and holding three of them is how that
// decision fails later.
//
// DOWNLOADABLE IS NOT FLASHABLE, and conflating them hid most of the archive. Some images are
// withheld from FLASHING: the dongle image (no hardware to prove it on), module apps that are not
// shipping modules, and pre-production keyboard images nobody can place by side. None of that is
// a reason to refuse someone a copy of the file. Every entry with a file of its own
// can be downloaded; whether it can then be written to a keyboard is the badge on its row.
//
// Entries with no file of their own -- the .sfb userapps extracted from FlashMemory.bin -- get no
// button, because there is nothing to fetch separately. Downloading the bundle is how you get
// them, and the row already says which bundle it came out of.
//
// There is no picker dialog: the list is already grouped by version and already on screen, so
// the button belongs on the group it downloads, with "Download all" at the top for everything.

/** held/total/bytes per version label, keyed the way the catalogue names versions. */
export function heldByLabel(catalogue, present) {
  const out = {};
  for (const im of catalogue || []) {
    if (!im.historyPath) continue;          // lives inside a container; nothing to fetch
    const label = im.versionLabel || im.version || im.bundle || "(unknown)";
    const e = (out[label] ||= { held: 0, total: 0, bytes: 0, paths: [], missing: [] });
    e.total += 1;
    const row = present?.[im.historyPath];
    e.bytes += row?.bytes || 0;
    e.paths.push(im.historyPath);
    if (row?.present) e.held += 1;
    else e.missing.push(im.historyPath);
  }
  return out;
}

export function megabytes(bytes) {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function FirmwareLibrary({ images }) {
  const [library, setLibrary] = useState(null);
  const [busy, setBusy] = useState(null);         // the label being fetched, or "all"
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

  // "We have not been told yet" is not "there is nothing to download". Without this the button
  // read "All versions downloaded" whenever the backend could not answer -- the most confident
  // possible claim made from no information at all.
  const known = !!library?.images;
  const present = {};
  for (const row of library?.images || []) present[row.path] = row;

  const imgs = images || [];
  const held = heldByLabel(imgs, present);
  const missingPaths = Object.values(held).flatMap((e) => e.missing);
  const missingLabels = Object.values(held).filter((e) => e.missing.length);
  const missingBytes = missingLabels.reduce(
    (n, e) => n + e.missing.reduce((m, p) => m + (present[p]?.bytes || 0), 0), 0);

  async function download(paths, tag) {
    setBusy(tag);
    setError("");
    setResult(null);
    try {
      setResult(await api.fetchFirmware({ paths }));
      await reload();
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setBusy(null);
    }
  }

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
        catalog, not the flasher: use “Update firmware” above, which backs the keyboard up,
        writes one half at a time and verifies the result. Images are downloaded on demand and
        checked against the hash recorded here before they are kept.
      </p>

      <div className="fw-lib-bar">
        <Button
          onClick={() => download(missingPaths, "all")}
          disabled={!!busy || !known || missingPaths.length === 0}
          busy={busy === "all"}
          title={!known
            ? "Still finding out which images are on this machine"
            : missingPaths.length === 0
            ? "Every image in the catalog is already on this machine"
            : `Downloads ${missingPaths.length} file(s) — about ${megabytes(missingBytes)}`}
        >
          {busy === "all" ? "Downloading…"
            : !known ? "Checking what is downloaded…"
            : missingPaths.length === 0 ? "Everything downloaded"
            : `Download all (${missingLabels.length} versions, ${megabytes(missingBytes)})`}
        </Button>
        {library?.dir && <span className="fw-lib-dir">{library.dir}</span>}
      </div>

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
        const h = held[label(first)];
        return (
          <div key={g} className="fw-lib-group">
            <div className="info-sub fw-lib-head">
              <span>{title} <span className="fw-lib-sub">· {sub}</span></span>
              {h && (h.missing.length ? (
                <Button
                  size="sm"
                  onClick={() => download(h.missing, label(first))}
                  disabled={!!busy || !known}
                  busy={busy === label(first)}
                  title={`Downloads ${h.missing.length} file(s) for this version`}
                >
                  {busy === label(first) ? "Downloading…" : `Download (${megabytes(h.bytes)})`}
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
                <span className="skp-act fw-lib-file">
                  {im.file}
                  {im.container ? ` in ${im.container}` : ""}
                  {/* No file of its own: it is extracted from the bundle above, so there is
                      nothing separate to fetch and no button pretends otherwise. */}
                  {!im.historyPath && im.container && <span className="fw-lib-sub"> · extracted</span>}
                  {im.historyPath && present[im.historyPath]?.present && (
                    <span className="fw-lib-held"> · on this machine</span>
                  )}
                </span>
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
