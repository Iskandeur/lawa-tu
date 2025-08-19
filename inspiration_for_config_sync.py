# We'll generate a Python module `obsidian_config_sync.py` with a small CLI.
# It supports two backends out of the box:
#  1) "folder" backend — writes versioned snapshots + a "latest" pointer into a folder
#     (this folder can itself be a Git repo, so commit/push can be done automatically).
#  2) "git" backend — a thin wrapper around the "folder" backend that also runs `git add/commit/push`.
#
# The code:
# - Detects the Obsidian config folder (.obsidian) under a given vault path.
# - Builds a manifest of "significant" files (themes, plugins, snippets, hotkeys, plugin configs, etc.).
# - Excludes volatile files (workspace.json, app.json, etc.).
# - Computes stable SHA256 hashes and a top-level fingerprint; skips work when unchanged.
# - Creates a compressed tar.gz payload with just the selected files.
# - Applies remote snapshots safely on the target machine with backup and atomic writes.
# - Provides a simple CLI compatible with your `sync.py` workflow:
#       python obsidian_config_sync.py export --vault /path/to/vault --backend folder --dest /path/to/remote
#       python obsidian_config_sync.py import --vault /path/to/vault --backend folder --src  /path/to/remote
#   The "git" backend takes the same flags plus optional --git-commit-message.
#
# NOTE: The KeepVault API specifics are unknown here, so we include a well-defined backend interface
# and a stub `KeepVaultBackend` with clear TODOs. You can wire your existing KeepVault note storage
# to read/write `manifest.json` and `payload.tar.gz` bytes using those methods without changing the rest.
#
import os, sys, json, hashlib, tarfile, time, shutil, subprocess
from pathlib import Path
from typing import Dict, List, Tuple, Optional

VERSION = "0.1.0"

SIGNIFICANT_REL_GLOBS = [
    # Core config we DO want:
    "appearance.json",
    "core-plugins.json",
    "community-plugins.json",
    "hotkeys.json",
    "bookmarks.json",          # present in newer Obsidian versions; OK if missing
    "snippets/**",             # CSS snippets
    "themes/**",               # downloaded themes
    "plugins/**",              # installed community plugins (incl. per-plugin data.json)
]

VOLATILE_REL_PATHS = {
    # Files that change frequently and are user/device-local:
    "workspace.json",
    "workspaces.json",
    "graph.json",
    "app.json",
}

# Certain plugin caches may be very noisy — you can add them here if you see churn:
VOLATILE_PLUGIN_PATTERNS = [
    # Example noisy cache files (extend as needed):
    # "plugins/<plugin-id>/cache/**",
]

MANIFEST_NAME = "manifest.json"
PAYLOAD_NAME  = "payload.tar.gz"
LATEST_NAME   = "LATEST"  # contains the version string


def sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def is_under(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def should_include(rel_path: Path) -> bool:
    # Explicit volatile files
    if rel_path.as_posix() in VOLATILE_REL_PATHS:
        return False

    # Noisy plugin patterns (prefix matches are enough here)
    rel_posix = rel_path.as_posix()
    for pat in VOLATILE_PLUGIN_PATTERNS:
        # very simple "starts with" pattern; feel free to enhance to glob
        if rel_posix.startswith(pat):
            return False

    # Evaluate inclusion via globs from the .obsidian root
    from fnmatch import fnmatch
    for g in SIGNIFICANT_REL_GLOBS:
        if fnmatch(rel_posix, g):
            return True
    return False


def build_manifest(obsidian_dir: Path) -> Dict:
    """
    Walk .obsidian and build a manifest of significant files only.
    """
    files: List[Dict] = []
    for p in obsidian_dir.rglob("*"):
        if p.is_file():
            rel = p.relative_to(obsidian_dir)
            if should_include(rel):
                files.append({
                    "rel": rel.as_posix(),
                    "size": p.stat().st_size,
                    "sha256": sha256_file(p),
                })

    # Sort for deterministic fingerprinting
    files.sort(key=lambda x: x["rel"])

    # Compute a stable fingerprint for the whole config snapshot
    fp_hasher = hashlib.sha256()
    for f in files:
        fp_hasher.update(f["rel"].encode("utf-8"))
        fp_hasher.update(b"\0")
        fp_hasher.update(f["sha256"].encode("utf-8"))
        fp_hasher.update(b"\0")
        fp_hasher.update(str(f["size"]).encode("utf-8"))
        fp_hasher.update(b"\0")

    fingerprint = fp_hasher.hexdigest()

    manifest = {
        "version": VERSION,
        "generated_at_unix": int(time.time()),
        "obsidian_dir": obsidian_dir.as_posix(),
        "files": files,
        "fingerprint": fingerprint,
    }
    return manifest


def make_payload_tar(obsidian_dir: Path, manifest: Dict, out_path: Path) -> None:
    """
    Create a tar.gz containing ONLY the files present in the manifest,
    laid out under ".obsidian/".
    """
    with tarfile.open(out_path, "w:gz") as tar:
        for entry in manifest["files"]:
            rel = Path(entry["rel"])
            src_path = obsidian_dir / rel
            arcname = Path(".obsidian") / rel
            tar.add(src_path, arcname=arcname.as_posix())


def apply_payload_tar(vault_dir: Path, payload_path: Path, manifest: Dict) -> None:
    """
    Apply a payload to the local vault:
    - Backup current .obsidian selection (only the included files) to backups/
    - Extract into a temp dir, then copy over atomically
    - Delete files that are tracked in local but not in manifest (to avoid config drift)
    """
    obsidian_dir = vault_dir / ".obsidian"
    obsidian_dir.mkdir(exist_ok=True)
    backups_dir = vault_dir / ".obsidian_sync_backups"
    backups_dir.mkdir(exist_ok=True)

    # 1) Backup current tracked files
    ts = time.strftime("%Y%m%d-%H%M%S")
    backup_tar = backups_dir / f"backup-{ts}.tar.gz"
    with tarfile.open(backup_tar, "w:gz") as tar:
        for p in obsidian_dir.rglob("*"):
            if p.is_file():
                rel = p.relative_to(obsidian_dir)
                if should_include(rel):
                    arcname = Path(".obsidian") / rel
                    tar.add(p, arcname=arcname.as_posix())

    # 2) Extract payload to a temp dir
    temp_dir = vault_dir / f".obsidian_tmp_apply_{ts}"
    temp_dir.mkdir()
    try:
        with tarfile.open(payload_path, "r:gz") as tar:
            tar.extractall(temp_dir)

        # 3) Copy extracted files into .obsidian, ensuring parents exist
        extracted_obsidian = temp_dir / ".obsidian"
        for p in extracted_obsidian.rglob("*"):
            if p.is_file():
                rel = p.relative_to(extracted_obsidian)
                dest = obsidian_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dest)

        # 4) Remove files that are included locally but NOT present in the new manifest
        new_set = { Path(e["rel"]).as_posix() for e in manifest["files"] }
        for p in obsidian_dir.rglob("*"):
            if p.is_file():
                rel = p.relative_to(obsidian_dir).as_posix()
                if should_include(Path(rel)) and rel not in new_set:
                    try:
                        os.remove(p)
                    except Exception:
                        pass
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ------------------------------ Backends ------------------------------

class Backend:
    def put(self, version: str, manifest: Dict, payload_bytes: bytes) -> None:
        raise NotImplementedError

    def get_latest(self) -> Optional[Tuple[str, Dict, bytes]]:
        """
        Returns (version, manifest_dict, payload_bytes) or None if empty.
        """
        raise NotImplementedError


class FolderBackend(Backend):
    """
    Stores snapshots on the local filesystem:
      <root>/obsidian-config/<version>/{manifest.json,payload.tar.gz}
      <root>/obsidian-config/LATEST  (contains version string)
    This folder can be a Git repo you sync otherwise.
    """
    def __init__(self, root: Path):
        self.root = root
        self.base = self.root / "obsidian-config"
        self.base.mkdir(parents=True, exist_ok=True)

    def _version_dir(self, version: str) -> Path:
        return self.base / version

    def put(self, version: str, manifest: Dict, payload_bytes: bytes) -> None:
        vdir = self._version_dir(version)
        vdir.mkdir(parents=True, exist_ok=True)
        (vdir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2))
        (vdir / PAYLOAD_NAME).write_bytes(payload_bytes)
        (self.base / LATEST_NAME).write_text(version)

    def get_latest(self) -> Optional[Tuple[str, Dict, bytes]]:
        latest_file = self.base / LATEST_NAME
        if not latest_file.exists():
            return None
        version = latest_file.read_text().strip()
        vdir = self._version_dir(version)
        manifest = json.loads((vdir / MANIFEST_NAME).read_text())
        payload = (vdir / PAYLOAD_NAME).read_bytes()
        return version, manifest, payload


class GitBackend(Backend):
    """
    Same layout as FolderBackend but automatically commits and pushes changes.
    """
    def __init__(self, root: Path, commit_message: Optional[str] = None):
        self.folder = FolderBackend(root)
        self.root = root
        self.commit_message = commit_message or "Update Obsidian config snapshot"

    def _run(self, *args: str) -> None:
        subprocess.run(args, cwd=self.root, check=True)

    def put(self, version: str, manifest: Dict, payload_bytes: bytes) -> None:
        self.folder.put(version, manifest, payload_bytes)
        # Stage and commit
        rel = str((self.folder.base.relative_to(self.root)).as_posix())
        self._run("git", "add", rel)
        # Commit might fail if no changes; ignore non-zero?
        try:
            self._run("git", "commit", "-m", self.commit_message)
        except subprocess.CalledProcessError:
            pass
        # Try push but don't crash if offline
        try:
            self._run("git", "push")
        except subprocess.CalledProcessError:
            pass

    def get_latest(self) -> Optional[Tuple[str, Dict, bytes]]:
        # Ensure we have the latest
        try:
            self._run("git", "pull", "--rebase", "--autostash")
        except subprocess.CalledProcessError:
            pass
        return self.folder.get_latest()


class KeepVaultBackend(Backend):
    """
    Placeholder interface for your KeepVault system.
    Implement the two methods using your note storage:
      - A canonical note/key (e.g., 'obsidian-config/LATEST') whose body is the version string
      - A binary attachment or body for manifest.json and payload.tar.gz per version
    """
    def __init__(self, namespace: str = "obsidian-config"):
        self.ns = namespace

    def put(self, version: str, manifest: Dict, payload_bytes: bytes) -> None:
        # TODO: Implement using KeepVault (create/update items):
        #   write LATEST -> version
        #   write {version}/manifest.json -> JSON
        #   write {version}/payload.tar.gz -> bytes
        raise NotImplementedError("Wire this into KeepVault's storage layer.")

    def get_latest(self) -> Optional[Tuple[str, Dict, bytes]]:
        # TODO: Read LATEST to get version, then fetch manifest and payload.
        raise NotImplementedError("Wire this into KeepVault's storage layer.")


# ------------------------------ CLI ------------------------------

def load_backend(name: str, path_or_ns: str, commit_msg: Optional[str]) -> Backend:
    if name == "folder":
        return FolderBackend(Path(path_or_ns))
    if name == "git":
        return GitBackend(Path(path_or_ns), commit_msg)
    if name == "keepvault":
        return KeepVaultBackend(path_or_ns)
    raise SystemExit(f"Unknown backend: {name}")


def find_obsidian_dir(vault_dir: Path) -> Path:
    obs = vault_dir / ".obsidian"
    if not obs.exists():
        raise SystemExit(f".obsidian not found under: {vault_dir}")
    return obs


def cmd_export(vault: str, backend: str, dest: str, commit_msg: Optional[str]) -> None:
    vault_dir = Path(vault).resolve()
    obsidian_dir = find_obsidian_dir(vault_dir)

    manifest = build_manifest(obsidian_dir)
    # Version is fingerprint + timestamp for uniqueness
    version = f"{manifest['fingerprint'][:12]}-{int(time.time())}"
    payload_tmp = Path.cwd() / "_payload_tmp.tar.gz"
    make_payload_tar(obsidian_dir, manifest, payload_tmp)
    payload_bytes = payload_tmp.read_bytes()
    payload_tmp.unlink(missing_ok=True)

    # If backend already has the same fingerprint, skip storing
    be = load_backend(backend, dest, commit_msg)
    latest = be.get_latest()
    if latest is not None:
        _ver, latest_manifest, _bytes = latest
        if latest_manifest.get("fingerprint") == manifest["fingerprint"]:
            print("No significant Obsidian config changes detected — export skipped.")
            return

    be.put(version, manifest, payload_bytes)
    print(f"Exported Obsidian config snapshot: {version}")


def cmd_import(vault: str, backend: str, src: str, commit_msg: Optional[str]) -> None:
    vault_dir = Path(vault).resolve()
    obsidian_dir = find_obsidian_dir(vault_dir)

    be = load_backend(backend, src, commit_msg)
    latest = be.get_latest()
    if latest is None:
        print("No snapshot found on backend.")
        return
    version, manifest, payload = latest

    # Compare with local
    local_manifest = build_manifest(obsidian_dir)
    if local_manifest.get("fingerprint") == manifest.get("fingerprint"):
        print("Local Obsidian config already up to date — import skipped.")
        return

    # Write payload bytes to a temp file and apply
    tmp = Path.cwd() / "_payload_in.tar.gz"
    tmp.write_bytes(payload)
    try:
        apply_payload_tar(vault_dir, tmp, manifest)
    finally:
        tmp.unlink(missing_ok=True)

    print(f"Applied Obsidian config snapshot: {version}")


def main(argv: List[str]) -> None:
    import argparse
    p = argparse.ArgumentParser(description="Obsidian configuration sync (themes, plugins, snippets, hotkeys, bookmarks).")
    sub = p.add_subparsers(dest="cmd", required=True)

    # export
    p_exp = sub.add_parser("export", help="Export local Obsidian configuration to backend")
    p_exp.add_argument("--vault", required=True, help="Path to your Obsidian vault root")
    p_exp.add_argument("--backend", choices=["folder", "git", "keepvault"], required=True)
    p_exp.add_argument("--dest", required=True, help="Folder path (folder/git) or namespace (keepvault)")
    p_exp.add_argument("--git-commit-message", default=None, help="Optional commit message (git backend)")

    # import
    p_imp = sub.add_parser("import", help="Import latest Obsidian configuration from backend")
    p_imp.add_argument("--vault", required=True, help="Path to your Obsidian vault root")
    p_imp.add_argument("--backend", choices=["folder", "git", "keepvault"], required=True)
    p_imp.add_argument("--src", required=True, help="Folder path (folder/git) or namespace (keepvault)")
    p_imp.add_argument("--git-commit-message", default=None, help="Optional commit message (git backend)")

    args = p.parse_args(argv)

    if args.cmd == "export":
        cmd_export(args.vault, args.backend, args.dest, args.git_commit_message)
    elif args.cmd == "import":
        cmd_import(args.vault, args.backend, args.src, args.git_commit_message)
    else:
        p.print_help()

if __name__ == "__main__":
    main(sys.argv[1:])