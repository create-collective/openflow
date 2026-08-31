// Client-side file download / upload helpers for profile & layer backups.

export function downloadJSON(filename, data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// Open a file picker and resolve the parsed JSON of the chosen file.
export function pickJSONFile() {
  return new Promise((resolve, reject) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "application/json,.json";
    input.onchange = () => {
      const file = input.files && input.files[0];
      if (!file) return resolve(null);
      const reader = new FileReader();
      reader.onload = () => {
        try {
          resolve(JSON.parse(reader.result));
        } catch (e) {
          reject(new Error("Not a valid JSON file"));
        }
      };
      reader.onerror = () => reject(new Error("Could not read file"));
      reader.readAsText(file);
    };
    input.click();
  });
}

export function safeName(s) {
  return (s || "backup").replace(/[^a-z0-9_-]+/gi, "_");
}
