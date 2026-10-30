"""Build the embedded runtime archive from an unmodified Microsoft Fixed Runtime."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument("runtime", type=Path)
parser.add_argument("--version", required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
destination = root / "vendor/FixedRuntime"
destination.mkdir(parents=True, exist_ok=True)
files = [(file, "browser/" + file.relative_to(args.runtime).as_posix())
         for file in sorted(args.runtime.rglob("*")) if file.is_file()]
files += [(root / "backend/Lenticular-Builder.blend", "Lenticular-Builder.blend"),
          (root / "blender/Lenticulizer_3D_Blender_Addon_v1.18.43.zip", "blender/Lenticulizer_3D_Blender_Addon_v1.18.43.zip"),
          (root / "vendor/WebView2/WebView2Loader.dll", "WebView2Loader.dll")]
files += [(file, "notices/" + file.name) for file in sorted((root / "vendor/notices").glob("*")) if file.is_file()]
manifest = {"version": args.version, "files": []}
archive = destination / "runtime.zip"
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as output:
    for index, (source, name) in enumerate(files):
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        manifest["files"].append({"path": name, "size": source.stat().st_size, "sha256": digest.hexdigest()})
        output.write(source, name)
        if index % 100 == 0:
            print(f"Bundled {index + 1}/{len(files)} runtime files", flush=True)
digest = hashlib.sha256()
with archive.open("rb") as stream:
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
manifest["archive_sha256"] = digest.hexdigest()
manifest["archive_bytes"] = archive.stat().st_size
manifest["unpacked_bytes"] = sum(file["size"] for file in manifest["files"])
(destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(f"Completed: {archive.stat().st_size:,} bytes; {len(files)} files", flush=True)
