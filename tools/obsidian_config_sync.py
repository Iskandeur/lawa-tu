import os
import json
import hashlib
import tarfile
import time
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

SIGNIFICANT_REL_GLOBS = [
	"appearance.json",
	"core-plugins.json",
	"community-plugins.json",
	"hotkeys.json",
	"bookmarks.json",
	"snippets/",
	"themes/",
	"plugins/",
]

VOLATILE_REL_PATHS = {
	"workspace.json",
	"workspaces.json",
	"graph.json",
	"app.json",
}

MANIFEST_NAME = "manifest.json"
PAYLOAD_NAME = "payload.tar.gz"
LATEST_NAME = "LATEST"


def _sha256_file(path: Path) -> str:
	h = hashlib.sha256()
	with path.open("rb") as f:
		for chunk in iter(lambda: f.read(1024 * 1024), b""):
			h.update(chunk)
	return h.hexdigest()


def _should_include(rel_path: Path) -> bool:
	posix = rel_path.as_posix()
	if posix in VOLATILE_REL_PATHS:
		return False
	# very light matching: allow dir prefixes defined above
	for g in SIGNIFICANT_REL_GLOBS:
		if g.endswith("/"):
			if posix.startswith(g):
				return True
		elif posix == g:
			return True
	return False


def _build_manifest(obsidian_dir: Path) -> Dict:
	files: List[Dict] = []
	for p in obsidian_dir.rglob("*"):
		if p.is_file():
			rel = p.relative_to(obsidian_dir)
			if _should_include(rel):
				files.append({
					"rel": rel.as_posix(),
					"size": p.stat().st_size,
					"sha256": _sha256_file(p),
				})
	files.sort(key=lambda x: x["rel"])  # deterministic
	fp_hasher = hashlib.sha256()
	for f in files:
		fp_hasher.update(f["rel"].encode("utf-8"))
		fp_hasher.update(b"\0")
		fp_hasher.update(f["sha256"].encode("utf-8"))
		fp_hasher.update(b"\0")
		fp_hasher.update(str(f["size"]).encode("utf-8"))
		fp_hasher.update(b"\0")
	return {
		"generated_at_unix": int(time.time()),
		"files": files,
		"fingerprint": fp_hasher.hexdigest(),
	}


def _make_payload_tar(obsidian_dir: Path, manifest: Dict, out_path: Path) -> None:
	with tarfile.open(out_path, "w:gz") as tar:
		for entry in manifest["files"]:
			rel = Path(entry["rel"])
			src_path = obsidian_dir / rel
			arcname = Path(".obsidian") / rel
			tar.add(src_path, arcname=arcname.as_posix())


def _git_run(repo_root: Path, *args: str) -> None:
	# Disable interactive prompts to avoid hanging runs (use SSH keys or credential helper)
	env = os.environ.copy()
	env["GIT_TERMINAL_PROMPT"] = "0"
	# Unset askpass if provided by host IDE
	env.pop("GIT_ASKPASS", None)
	subprocess.run(args, cwd=repo_root, check=True, env=env)


def export_to_git_repo(vault_dir: str, repo_root: str, commit_message: Optional[str] = None) -> Optional[str]:
	"""
	Export the vault's .obsidian configuration snapshot to a separate git repository.

	Returns the version string if an export was performed, otherwise None if skipped.
	"""
	repo_path = Path(repo_root).resolve()
	vault_path = Path(vault_dir).resolve()
	obsidian_dir = vault_path / ".obsidian"
	if not obsidian_dir.exists():
		logger.warning(f".obsidian not found under vault: {vault_path}")
		return None
	if not (repo_path.exists() and (repo_path / ".git").exists()):
		logger.warning(f"Destination is not a git repo: {repo_path}")
		return None

	manifest = _build_manifest(obsidian_dir)
	version = f"{manifest['fingerprint'][:12]}-{int(time.time())}"
	base = repo_path / "obsidian-config"
	version_dir = base / version
	base.mkdir(parents=True, exist_ok=True)

	# Pull latest to minimize conflicts
	try:
		_git_run(repo_path, "git", "pull", "--rebase", "--autostash")
	except subprocess.CalledProcessError:
		pass

	latest_file = base / LATEST_NAME
	if latest_file.exists():
		try:
			latest_ver = latest_file.read_text().strip()
			latest_manifest_path = base / latest_ver / MANIFEST_NAME
			if latest_manifest_path.exists():
				latest_manifest = json.loads(latest_manifest_path.read_text())
				if latest_manifest.get("fingerprint") == manifest["fingerprint"]:
					logger.info("Obsidian config unchanged; export skipped.")
					return None
		except Exception:
			# ignore and proceed to write a new snapshot
			pass

	# Write new snapshot
	payload_tmp = repo_path / "_obs_payload_tmp.tar.gz"
	_make_payload_tar(obsidian_dir, manifest, payload_tmp)
	payload_bytes = payload_tmp.read_bytes()
	payload_tmp.unlink(missing_ok=True)

	version_dir.mkdir(parents=True, exist_ok=True)
	(version_dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2))
	(version_dir / PAYLOAD_NAME).write_bytes(payload_bytes)
	(base / LATEST_NAME).write_text(version)

	# Commit & push
	rel = os.path.relpath(base.as_posix(), repo_path.as_posix())
	try:
		_git_run(repo_path, "git", "add", rel)
		msg = commit_message or "Update Obsidian config snapshot"
		try:
			_git_run(repo_path, "git", "commit", "-m", msg)
		except subprocess.CalledProcessError:
			# likely no changes staged
			pass
		try:
			_git_run(repo_path, "git", "push")
		except subprocess.CalledProcessError:
			logger.warning("Git push failed (offline?). Changes remain local to the repo.")
	except subprocess.CalledProcessError as e:
		logger.error(f"Git command failed: {e}")
		return None

	logger.info(f"Exported Obsidian config snapshot: {version}")
	return version
