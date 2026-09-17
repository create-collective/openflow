// The release check, shared by the Hub's box and Settings: one opt-in request to GitHub, no
// updater. The monorepo tags OpenFlow releases `openflow-v0.1.0`, so the version is what is left
// after that prefix; stripping only a leading `v` (as Settings once did) compared "openflow-v0.1.0"
// with "0.1.0" and reported an update forever.
export const REPOS = {
  app: "traviswye/openflow",
  companion: "traviswye/create-companion",
  firmware: "traviswye/openflow-firmware",
  // The CLI our device communication is built on (Cory Bennett, Apache-2.0), vendored under
  // backend/openflow_backend/_vendor/nayactl; see VENDOR.md there.
  nayactl: "Qonfused/nayactl",
};

export function versionFromTag(tag) {
  return String(tag || "").replace(/^(openflow-|companion-)?v/i, "");
}

/** { latest, url } for a repo's latest release; throws with a readable message otherwise. */
export async function latestRelease(repo) {
  const res = await fetch(`https://api.github.com/repos/${repo}/releases/latest`);
  if (!res.ok) throw new Error(res.status === 404 ? "No public releases yet" : `GitHub ${res.status}`);
  const d = await res.json();
  return { latest: versionFromTag(d.tag_name), url: d.html_url || `https://github.com/${repo}/releases` };
}

/** { checking } while it runs, then { latest, current, ahead, url } or { error }. */
export async function checkRelease(repo, current, setter) {
  setter({ checking: true });
  try {
    const { latest, url } = await latestRelease(repo);
    setter({ latest, current, url, ahead: !!latest && !!current && latest !== current });
  } catch (e) {
    setter({ error: e.message });
  }
}
