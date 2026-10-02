// Code signing for release builds, switched on by the inputs a runner is given.
//
// The committed build configuration is the unsigned one (package.json: mac.identity null, no
// azureSignOptions), so a build on a developer's machine never goes looking for certificates.
// The release workflow runs this before electron-builder. With a platform's signing inputs
// present it rewrites package.json IN THE CHECKOUT and exports what electron-builder reads from
// the environment; with none it changes nothing and the build is unsigned, as before. A partial
// set is a mistake (a rotated secret, a deleted variable) and fails the job: better no release
// than one that looks signed in the workflow and is not.
//
//   macOS    APPLE_CERTIFICATE_P12 (base64 of the Developer ID Application .p12),
//            APPLE_CERTIFICATE_PASSWORD, and for notarization APPLE_API_KEY_P8 (the text of the
//            App Store Connect key), APPLE_API_KEY_ID, APPLE_API_ISSUER_ID.
//   Windows  Azure Artifact Signing: AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET (an
//            app registration holding the Certificate Profile Signer role) and where the
//            certificate lives: AZURE_SIGNING_ENDPOINT, AZURE_SIGNING_ACCOUNT,
//            AZURE_SIGNING_PROFILE, AZURE_SIGNING_PUBLISHER (the certificate's subject name).
//   Linux    nothing to sign.
//
//     node scripts/ci-signing.mjs             before the build: configure, or leave unsigned
//     node scripts/ci-signing.mjs --check     say what would happen, change nothing
//     node scripts/ci-signing.mjs --verify    after the build: prove the artefacts are signed
import { execFileSync } from "node:child_process";
import { appendFileSync, existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const PKG = join(ROOT, "package.json");
const args = process.argv.slice(2);
const checkOnly = args.includes("--check");

const INPUTS = {
  darwin: ["APPLE_CERTIFICATE_P12", "APPLE_CERTIFICATE_PASSWORD", "APPLE_API_KEY_P8", "APPLE_API_KEY_ID", "APPLE_API_ISSUER_ID"],
  win32: ["AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET",
    "AZURE_SIGNING_ENDPOINT", "AZURE_SIGNING_ACCOUNT", "AZURE_SIGNING_PROFILE", "AZURE_SIGNING_PUBLISHER"],
};

const env = (name) => (process.env[name] || "").trim();
const fail = (message) => { console.error(`ci-signing: ${message}`); process.exit(1); };

// Later steps of the job see what is written here. Values go in with a delimiter, so a secret
// that spans lines cannot end the entry early.
function exportEnv(name, value) {
  if (checkOnly) return;
  process.env[name] = value;
  if (process.env.GITHUB_ENV) appendFileSync(process.env.GITHUB_ENV, `${name}<<__OPENFLOW_EOF__\n${value}\n__OPENFLOW_EOF__\n`);
}

// What this platform can do with the inputs it has: "signed", "unsigned", or exit on a partial set.
function plan() {
  const wanted = INPUTS[process.platform];
  if (!wanted) return "unsigned";
  const missing = wanted.filter((name) => !env(name));
  if (missing.length === wanted.length) return "unsigned";
  if (missing.length) fail(`signing inputs are incomplete on ${process.platform}; missing ${missing.join(", ")}`);
  return "signed";
}

function configure() {
  const mode = plan();
  if (mode === "unsigned") {
    // Without this electron-builder searches the runner's keychain or certificate store.
    exportEnv("CSC_IDENTITY_AUTO_DISCOVERY", "false");
    console.log(`ci-signing: no signing inputs on ${process.platform}; this build is UNSIGNED`);
    return;
  }

  const pkg = JSON.parse(readFileSync(PKG, "utf8"));
  const build = pkg.build;
  build.forceCodeSigning = true;                 // a signature that fails stops the build

  if (process.platform === "darwin") {
    // identity null means "never sign"; without it electron-builder takes the Developer ID
    // Application identity from the certificate below. The hardened runtime is what
    // notarization requires, with electron-builder's own entitlements for Electron.
    delete build.mac.identity;
    delete build.mac.hardenedRuntime;
    if (!checkOnly) {
      const scratch = process.env.RUNNER_TEMP || tmpdir();
      const p8 = join(scratch, `AuthKey_${env("APPLE_API_KEY_ID")}.p8`);
      writeFileSync(p8, env("APPLE_API_KEY_P8") + "\n", { mode: 0o600 });
      exportEnv("CSC_LINK", env("APPLE_CERTIFICATE_P12"));   // base64 of the .p12; electron-builder decodes it
      exportEnv("CSC_KEY_PASSWORD", env("APPLE_CERTIFICATE_PASSWORD"));
      exportEnv("CSC_IDENTITY_AUTO_DISCOVERY", "true");
      exportEnv("APPLE_API_KEY", p8);             // electron-builder wants the PATH here
      exportEnv("APPLE_API_KEY_ID", env("APPLE_API_KEY_ID"));
      exportEnv("APPLE_API_ISSUER", env("APPLE_API_ISSUER_ID"));
    }
  } else {
    // The frozen backend (extraResources) is an .exe, so electron-builder signs it on the way
    // in, along with the app, the installer, its uninstaller and the portable build.
    build.win.azureSignOptions = {
      publisherName: env("AZURE_SIGNING_PUBLISHER"),
      endpoint: env("AZURE_SIGNING_ENDPOINT"),
      codeSigningAccountName: env("AZURE_SIGNING_ACCOUNT"),
      certificateProfileName: env("AZURE_SIGNING_PROFILE"),
    };
    // The signing module signs in with these, straight from the environment of the build step.
    for (const name of ["AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"]) exportEnv(name, env(name));
  }

  if (!checkOnly) writeFileSync(PKG, JSON.stringify(pkg, null, 2) + "\n");
  exportEnv("OPENFLOW_SIGNED", "1");
  console.log(`ci-signing: ${process.platform} build will be SIGNED${process.platform === "darwin" ? " and notarized" : ""}${checkOnly ? " (check only, nothing changed)" : ""}`);
}

const run = (cmd, cmdArgs) => execFileSync(cmd, cmdArgs, { cwd: ROOT, stdio: "inherit" });

// After the build. electron-builder reports a skipped signature as a log line, not a failure,
// so the artefacts themselves are asked.
function verify() {
  if (process.env.OPENFLOW_SIGNED !== "1") {
    console.log("ci-signing: unsigned build, nothing to verify");
    return;
  }
  const release = join(ROOT, "release");
  if (process.platform === "win32") {
    const exes = readdirSync(release).filter((f) => f.endsWith(".exe")).map((f) => join(release, f));
    const backend = join(release, "win-unpacked", "resources", "backend", "openflow-backend.exe");
    if (!exes.length) fail("no .exe in release/ to verify");
    for (const file of [...exes, backend]) {
      run("powershell", ["-NoProfile", "-NonInteractive", "-Command",
        `$s = Get-AuthenticodeSignature -LiteralPath '${file.replace(/'/g, "''")}'; ` +
        `Write-Host ('{0}  {1}  {2}' -f $s.Status, $s.SignerCertificate.Subject, (Split-Path -Leaf $s.Path)); ` +
        `if ($s.Status -ne 'Valid') { exit 1 }`]);
    }
  } else if (process.platform === "darwin") {
    const apps = readdirSync(release).filter((d) => d.startsWith("mac"))
      .map((d) => join(release, d, "OpenFlow.app")).filter(existsSync);
    if (!apps.length) fail("no OpenFlow.app under release/ to verify");
    for (const app of apps) {
      run("codesign", ["--verify", "--deep", "--strict", "--verbose=2", app]);
      run("xcrun", ["stapler", "validate", app]);
      run("spctl", ["--assess", "--type", "execute", "--verbose=2", app]);
      // The hardened runtime is new to the frozen backend: start it once from inside the
      // signed bundle, the same smoke test the unsigned sidecar passed before packaging.
      run(process.execPath, [join(ROOT, "scripts", "smoke-sidecar.mjs"), join(app, "Contents", "Resources", "backend", "openflow-backend")]);
    }
  }
  console.log("ci-signing: signatures verified");
}

if (args.includes("--verify")) verify();
else configure();
