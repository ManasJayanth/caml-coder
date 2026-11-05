"""Public subprocess E2Es for bounded, pinned Bonito tokenizer assets."""
import hashlib
import json
from pathlib import Path
import shutil

from tokenizers import AddedToken, Tokenizer, models, pre_tokenizers


SPECIAL_TOKENS = {"<unk>": 0, "<s>": 1, "</s>": 2}
PROTOCOL = {"<|tasktype|>": [3], "<|context|>": [4], "<|task|>": [5]}
PROBES = ["<|tasktype|> question answering without choices\n<|context|> OCaml λ 42\n<|task|>",
          "A small Unicode probe: café → OCaml"]
BONITO_REPOSITORY = "BatsResearch/bonito-v1"
BONITO_REVISION = "0b70064ffa8956ab6bec867b87fc85762dd26d81"
BONITO_PROTOCOL_TOKENS = {
    "<|tasktype|>": [523, 28766, 5553, 1123, 28766, 28767],
    "<|context|>": [523, 28766, 2714, 28766, 28767],
    "<|task|>": [523, 28766, 5553, 28766, 28767],
}
BONITO_SPECIAL_TOKENS = {"<unk>": 0, "<s>": 1, "</s>": 2}


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _fixture(t, label):
    source_dir = t.temporary / f"fixture-{label}"
    source_dir.mkdir(parents=True)
    vocab = {"<unk>": 0, "<s>": 1, "</s>": 2, "<|tasktype|>": 3, "<|context|>": 4,
             "<|task|>": 5, "question": 6, "answering": 7, "without": 8, "choices": 9,
             "OCaml": 10, "42": 11, "A": 12, "small": 13, "Unicode": 14, "probe:": 15,
             "café": 16, "→": 17}
    tokenizer = Tokenizer(models.WordLevel(vocab, unk_token="<unk>"))
    tokenizer.pre_tokenizer = pre_tokenizers.WhitespaceSplit()
    tokenizer.add_special_tokens([AddedToken(text, special=True) for text in SPECIAL_TOKENS])
    paths = {}
    paths["tokenizer.json"] = source_dir / "tokenizer.json"
    paths["tokenizer.json"].write_text(tokenizer.to_str(), encoding="utf-8")
    paths["tokenizer_config.json"] = _write_json(source_dir / "tokenizer_config.json", {
        "added_tokens_decoder": {str(token_id): {"content": token, "special": True}
                                 for token, token_id in SPECIAL_TOKENS.items()},
        "bos_token": "<s>", "eos_token": "</s>", "unk_token": "<unk>"})
    paths["special_tokens_map.json"] = _write_json(source_dir / "special_tokens_map.json", {
        "bos_token": "<s>", "eos_token": "</s>", "unk_token": "<unk>"})
    paths["added_tokens.json"] = _write_json(source_dir / "added_tokens.json", SPECIAL_TOKENS)
    paths["config.json"] = _write_json(source_dir / "config.json", {"model_type": "fixture-tokenizer"})
    assets = []
    for name, path in paths.items():
        raw = path.read_bytes()
        assets.append({"path": name, "sha256": hashlib.sha256(raw).hexdigest(),
                       "max_bytes": max(len(raw) + 32, 1024), "fixture_path": str(path)})
    config = {"schema_version": 1, "stage": "model_assets", "kind": "fixture",
              "repo_id": "fixture/bonito", "revision": "a" * 40, "files": assets,
              "special_tokens": SPECIAL_TOKENS, "protocol_tokens": PROTOCOL, "probe_texts": PROBES}
    return config, paths


def _invoke(t, label, config, run_id, expected=0):
    root = t.temporary / f"project-{label}"
    root.mkdir(exist_ok=True)
    config_path = _write_json(t.temporary / f"{label}.json", config)
    return t.cli("prepare", "--config", config_path, "--run-id", run_id, root=root, expected=expected), root


def test_tokenizer(t):
    config, paths = _fixture(t, "success")
    result, root = _invoke(t, "success", config, "bonito-tokenizer")
    output = root / "artifacts/models/tokenizers/bonito-tokenizer"
    manifest_path = output / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    t.check(result["exit_code"] == 0 and manifest["repo_id"] == "fixture/bonito" and
            manifest["revision"] == "a" * 40, "fixture acquisition commits exact repository and immutable revision")
    t.check({record["path"] for record in manifest["files"]} == set(paths) and
            not any(Path(record["path"]).suffix in {".bin", ".safetensors", ".py"} for record in manifest["files"]),
            "manifest contains only explicitly pinned tokenizer/config assets, never weights or repository code")
    t.check(manifest["special_tokens"] == SPECIAL_TOKENS and manifest["protocol_tokens"] == PROTOCOL and
            len(manifest["probes"]) == len(PROBES) and all(p["token_count"] > 0 for p in manifest["probes"]),
            "actual tokenizer validates special-token IDs, protocol sequences, and deterministic encode/decode probes")
    t.cli("prepare", "--config", _write_json(t.temporary / "success-retry.json", config),
          "--run-id", "bonito-tokenizer", root=root)
    t.check(manifest_path.read_bytes() == manifest_bytes, "identical retry preserves immutable manifest bytes")

    # Same run ID cannot silently bind a different pinned tokenizer identity.
    altered = json.loads(json.dumps(config))
    altered["revision"] = "b" * 40
    t.cli("prepare", "--config", _write_json(t.temporary / "changed-revision.json", altered),
          "--run-id", "bonito-tokenizer", root=root, expected=2)

    # Corruption is detected on retry and never repaired in place.
    target = output / "files/tokenizer_config.json"
    original = target.read_bytes()
    target.write_bytes(original + b" ")
    t.cli("prepare", "--config", _write_json(t.temporary / "corrupt-retry.json", config),
          "--run-id", "bonito-tokenizer", root=root, expected=2)
    t.check(target.read_bytes() == original + b" ", "corrupt committed tokenizer bytes are rejected without rewriting them")


def test_tokenizer_rejects_unpinned_and_unsafe(t):
    config, _ = _fixture(t, "reject")
    floating = json.loads(json.dumps(config))
    floating["revision"] = "main"
    _, root = _invoke(t, "floating", floating, "floating", expected=2)
    t.check(not (root / "artifacts/models/tokenizers/floating/manifest.json").exists(),
            "floating model revision fails before creating committed assets")

    traversal = json.loads(json.dumps(config))
    traversal["files"][0]["path"] = "../tokenizer.json"
    _, root = _invoke(t, "traversal", traversal, "traversal", expected=2)
    t.check(not (root / "artifacts/models/tokenizers/traversal").exists(),
            "unsafe and unapproved asset paths fail before creating output")

    weights = json.loads(json.dumps(config))
    weights["files"][0]["path"] = "pytorch_model.bin"
    _, root = _invoke(t, "weights", weights, "weights", expected=2)
    t.check(not (root / "artifacts/models/tokenizers/weights").exists(),
            "weight files are outside the tokenizer-only acquisition scope")

    wrong_hash = json.loads(json.dumps(config))
    wrong_hash["files"][0]["sha256"] = "0" * 64
    _, root = _invoke(t, "wrong-hash", wrong_hash, "wrong-hash", expected=2)
    t.check(not (root / "artifacts/models/tokenizers/wrong-hash/manifest.json").exists(),
            "asset hash mismatch leaves no committed manifest")

    unapproved_repo = json.loads(json.dumps(config))
    unapproved_repo["kind"] = "official"
    unapproved_repo["repo_id"] = "untrusted/bonito"
    for item in unapproved_repo["files"]:
        item.pop("fixture_path", None)
    _, root = _invoke(t, "unapproved-repo", unapproved_repo, "unapproved-repo", expected=2)
    t.check(not (root / "artifacts/models/tokenizers/unapproved-repo/manifest.json").exists(),
            "official downloads are restricted to the approved Bonito repository")


def test_tokenizer_protocol_and_filesystem_integrity(t):
    config, paths = _fixture(t, "integrity")
    wrong_protocol = json.loads(json.dumps(config))
    wrong_protocol["protocol_tokens"]["<|task|>"] = [999]
    _, root = _invoke(t, "wrong-protocol", wrong_protocol, "wrong-protocol", expected=2)
    t.check(not (root / "artifacts/models/tokenizers/wrong-protocol/manifest.json").exists(),
            "mismatched protocol token ID sequences block commitment")

    symlink_config = json.loads(json.dumps(config))
    external = t.temporary / "external-tokenizer.json"
    shutil.copyfile(paths["tokenizer.json"], external)
    linked = paths["tokenizer.json"].parent / "linked-tokenizer.json"
    linked.symlink_to(external)
    symlink_config["files"][0]["fixture_path"] = str(linked)
    _, root = _invoke(t, "symlink", symlink_config, "symlink", expected=2)
    t.check(not (root / "artifacts/models/tokenizers/symlink/manifest.json").exists(),
            "fixture symlink is rejected without committing assets")

    partial_root = t.temporary / "project-partial"
    partial_dir = partial_root / "artifacts/models/tokenizers/partial/files"
    partial_dir.mkdir(parents=True)
    (partial_dir / "orphan.json").write_text("{}", encoding="utf-8")
    config_path = _write_json(t.temporary / "partial.json", config)
    t.cli("prepare", "--config", config_path, "--run-id", "partial", root=partial_root, expected=2)
    t.check(not (partial_root / "artifacts/models/tokenizers/partial/manifest.json").exists(),
            "uncommitted partial output directory is rejected, never completed in place")


def test_actual_bonito_tokenizer(t):
    """Load the already-resolved upstream tokenizer locally, without network access."""
    source_dir = t.root / "artifacts/model-assets-resolution/bonito-tokenizer-001"
    resolution = json.loads((source_dir / "resolution.json").read_text(encoding="utf-8"))
    t.check(resolution["repo_id"] == BONITO_REPOSITORY and resolution["revision"] == BONITO_REVISION,
            "local Bonito asset resolution is bound to the selected repository and full commit")
    assets = []
    for record in resolution["files"]:
        path = source_dir / record["path"]
        assets.append({"path": record["path"], "sha256": record["sha256"],
                       "max_bytes": record["max_bytes"], "fixture_path": str(path)})
    config = {"schema_version": 1, "stage": "model_assets", "kind": "fixture",
              "repo_id": BONITO_REPOSITORY, "revision": BONITO_REVISION, "files": assets,
              "special_tokens": BONITO_SPECIAL_TOKENS,
              "protocol_tokens": BONITO_PROTOCOL_TOKENS,
              "probe_texts": ["<|tasktype|>\nquestion answering without choices\n<|context|>\nOCaml λ\n<|task|>\n",
                              "<|tasktype|>\nsummarization\n<|context|>\nUnicode café\n<|task|>\n"]}
    _, root = _invoke(t, "actual-bonito", config, "bonito-pinned-local")
    manifest = json.loads((root / "artifacts/models/tokenizers/bonito-pinned-local/manifest.json").read_text(encoding="utf-8"))
    t.check(manifest["repo_id"] == BONITO_REPOSITORY and manifest["revision"] == BONITO_REVISION and
            len(manifest["files"]) == len(assets) and all(p["token_count"] > 0 for p in manifest["probes"]),
            "actual Bonito tokenizer and exact pinned config files load and tokenize full assembled prompts locally")


SCENARIOS = {"tokenizer": test_tokenizer,
             "tokenizer-rejections": test_tokenizer_rejects_unpinned_and_unsafe,
             "tokenizer-integrity": test_tokenizer_protocol_and_filesystem_integrity,
             "bonito-actual-tokenizer": test_actual_bonito_tokenizer}
