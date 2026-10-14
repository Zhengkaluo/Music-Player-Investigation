"""Recover verified SongBase documents from a preserved Git tree, without touching audio."""
import ast
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "SongBase"
TREE = "1bd730dc7d00aad977e080d8c69271b6519363cb"
TEXT = {".json", ".md", ".html", ".py", ".cjs", ".csv"}
MODEL_STASH = "ba181963fb15bbec2af68d9667f6739a7cd89c43"
MODEL_FILES = (
    "Flowset-个人审美打标-Demo/build_transition_relationship_report.py",
    "Flowset-个人审美打标-Demo/flowset_transition_relationship_report.html",
    "Flowset-个人审美打标-Demo/transition_report_build_2026-10-09.json",
    "Flowset-个人审美打标-Demo/用户风格衔接偏好报告_2026-10-09.md",
    "ZMPD-模型预测开发/build_training_manifest.py",
    "ZMPD-模型预测开发/features/seventh-extraction/compact-v3-analysis.json",
    "ZMPD-模型预测开发/features/seventh-extraction/personal-features-v2.json",
    "ZMPD-模型预测开发/features/seventh-extraction/progress.json",
    "ZMPD-模型预测开发/features/seventh-extraction/track-checkpoints.ndjson",
    "ZMPD-模型预测开发/features/sixth-extraction/compact-v3-analysis.json",
    "ZMPD-模型预测开发/features/sixth-extraction/personal-features-v2.json",
    "ZMPD-模型预测开发/features/sixth-extraction/progress.json",
    "ZMPD-模型预测开发/features/sixth-extraction/track-checkpoints.ndjson",
    "ZMPD-模型预测开发/features/source/personal-features-v2.json",
    "ZMPD-模型预测开发/features/training/Flowset-个人审美样本-郑卡罗-2026-07-16/personal-features-v2.json",
    "ZMPD-模型预测开发/features/training/Flowset-个人审美样本-郑卡罗-2026-07-22/personal-features-v2.json",
    "ZMPD-模型预测开发/features/training/Flowset-个人审美样本-郑卡罗-2026-07-28/personal-features-v2.json",
    "ZMPD-模型预测开发/features/training/Flowset-个人审美样本-郑卡罗-2026-09-25/personal-features-v2.json",
    "ZMPD-模型预测开发/features/training/Flowset-个人审美样本·第七波闭环补标100首-郑卡罗-2026-10-05/personal-features-v2.json",
    "ZMPD-模型预测开发/features/training/Flowset-个人审美样本·第五波高价值补标-anonymous-2026-09-26/personal-features-v2.json",
    "ZMPD-模型预测开发/features/training/Flowset-个人审美样本·第六波均衡补标100首-郑卡罗-2026-10-03/personal-features-v2.json",
    "ZMPD-模型预测开发/reports/cross-batch-evaluation.html",
    "ZMPD-模型预测开发/reports/cross-batch-evaluation.json",
    "ZMPD-模型预测开发/reports/cross-batch-evaluation.md",
    "ZMPD-模型预测开发/run_cross_batch_evaluation.py",
    "ZMPD-模型预测开发/模型训练与预测需求表.md",
)
DEPENDENCIES = {
    "ZMPD-模型预测开发/manifests/training-manifest.json": "58f967e6e010b648ce75e1f9804de411b4420267",
    "Flowset-个人审美打标-Demo/Flowset-个人审美样本·Tag-ZMPD联合标注14首-郑卡罗-2026-10-09.json": "b1206f745dc0d850740478468d2e412163f1adad",
    "Flowset-个人审美打标-Demo/Flowset-个人审美样本·Tag-ZMPD联合标注50首-郑卡罗-2026-10-10.json": "bd7ccf10a984e07a0240e380e74e9a03879232e0",
    "Flowset-个人审美打标-Demo/flowset_transition_analysis_rows.csv": "91afbd290824cfaac809b95edac0d805ed6ef4bd",
    "Flowset-个人审美打标-Demo/第七波测试清单.csv": "cf0d94a3ed1d75a6d012fe4624db1e96c74b829d",
    "Flowset-个人审美打标-Demo/第六波测试清单.csv": "860f44f6a411914bde3531781377acdb966268b5",
}

def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)

def digest(data):
    return hashlib.sha256(data).hexdigest()

def inventory():
    rows = []
    for record in git("ls-tree", "-rz", TREE).split(b"\0"):
        if not record:
            continue
        header, name = record.split(b"\t", 1)
        mode, kind, oid = header.decode().split()
        relative = Path(name.decode())
        assert not relative.is_absolute() and ".." not in relative.parts
        if kind == "blob" and relative.suffix in TEXT:
            content = git("cat-file", "blob", oid)
            if relative.suffix == ".json":
                json.loads(content)
            rows.append((relative, content, oid))
    return rows

def recover_models():
    assert len(MODEL_FILES) == len(set(MODEL_FILES)) == 26
    assert git("rev-parse", "stash@{0}").decode().strip() == MODEL_STASH
    sources = []
    for name in MODEL_FILES:
        content = git("show", MODEL_STASH + ":" + name)
        if name.endswith(".json"):
            json.loads(content)
        elif name.endswith(".ndjson"):
            for line in content.splitlines():
                if line.strip():
                    json.loads(line)
        elif name.endswith(".py"):
            ast.parse(content.decode(), filename=name)
        sources.append((name, content))
    print(json.dumps({"stash": MODEL_STASH, "flowset_files": 4, "zmpd_files": 22}))
    if "--apply" not in sys.argv:
        return
    protected = (".gitignore", "SongBase/song_base_by_artist.json", "SongBase/song_tags.json",
                 "SongBase/song_tags_browser.html", "SongBase/song_manual_tagging.html",
                 "SongBase/song_combined_annotation.html",
                 "ZMPD-模型预测开发/manifests/training-manifest.json")
    protected_hashes = {name: digest((ROOT / name).read_bytes()) for name in protected}
    backup = BASE / "archive/snapshots/recovery" / (
        datetime.now().strftime("%Y%m%d-%H%M%S") + "-before-Flowset-ZMPD-restore")
    backup.mkdir(parents=True, exist_ok=False)
    records = []
    for name, content in sources:
        path = ROOT / name
        previous = path.read_bytes() if path.is_file() else None
        if previous is not None:
            saved = backup / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, saved)
        records.append({"path": name, "before_sha256": digest(previous) if previous else None,
                        "stash_sha256": digest(content)})
        path.parent.mkdir(parents=True, exist_ok=True)
    # Exact, explicitly authorized Git restoration; leave the index and stash untouched.
    git("restore", "--source=" + MODEL_STASH, "--worktree", "--", *MODEL_FILES)
    for name, content in sources:
        assert (ROOT / name).read_bytes() == content, name
    for name, expected in protected_hashes.items():
        assert digest((ROOT / name).read_bytes()) == expected, name
    assert git("rev-parse", "stash@{0}").decode().strip() == MODEL_STASH
    audit = {"schema_version": "songbase.related-stash-recovery/v1",
             "restored_at": datetime.now().astimezone().isoformat(), "stash": MODEL_STASH,
             "flowset_files": 4, "zmpd_files": 22, "backup_directory": str(backup),
             "files": records, "protected_files": protected_hashes,
             "stash_preserved": True, "audio_files_modified": 0,
             "model_training_executed": False, "local_service_started": False}
    (BASE / "imports/2026-10-13-Flowset-ZMPD-stash恢复.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"restored": len(records), "backup": str(backup),
                      "stash_preserved": True}, ensure_ascii=False))

def main():
    if "--models" in sys.argv:
        recover_models()
        return
    if "--mirror" in sys.argv:
        mirror = Path("/Users/kaluozheng/Desktop/SongBase 歌曲标签库")
        target = BASE / "imports/2026-10-13-曲库版本恢复.json"
        audit = json.loads(target.read_text())
        backup = Path(audit["backup_directory"]) / "_desktop_mirror"
        pairs = [(name, "数据/" + name) for name in
                 ("song_base_by_artist.json", "song_tags.json", "song_tag_candidates.json", "song_tag_mapping.json")]
        pairs += [(name, "报告/" + name) for name in
                  ("song_base_by_artist.md", "song_tag_candidate_report.md", "曲库风格与语种报告.md")]
        pairs += [(name, "工具/" + name) for name in
                  ("song_base_browser.html", "song_tags_browser.html", "song_manual_tagging.html",
                   "song_combined_annotation.html", "song_tag_mapping_editor.html")]
        records = []
        for source_name, name in pairs:
            content = (BASE / source_name).read_bytes()
            destination = mirror / name
            previous = destination.read_bytes() if destination.is_file() else None
            if previous == content:
                continue
            if previous is not None:
                saved = backup / name
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, saved)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(BASE / source_name, destination)
            assert destination.read_bytes() == content
            records.append({"path": name, "sha256": digest(content)})
        links = {"SongResources": BASE / "SongResources"}
        links.update({n: mirror / "数据" / n for n in
                      ("song_tags.json", "song_tag_candidates.json", "song_tag_mapping.json")})
        for name, source in links.items():
            link = mirror / "工具" / name
            if link.is_symlink():
                assert link.resolve() == source.resolve(), str(link)
            elif link.exists():
                raise ValueError("桌面连接目标已存在，未覆盖：" + str(link))
            else:
                link.symlink_to(source, target_is_directory=source.is_dir())
        audit["desktop_mirror_updated"] = records
        target.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"desktop_documents_updated": len(records), "audio_copies_created": 0}))
        return
    if "--dependencies" in sys.argv:
        target = BASE / "imports/2026-10-13-曲库版本恢复.json"
        audit = json.loads(target.read_text())
        backup = Path(audit["backup_directory"]) / "_related_data"
        records = []
        for name, oid in DEPENDENCIES.items():
            content = git("cat-file", "blob", oid)
            if name.endswith(".json"):
                json.loads(content)
            destination = ROOT / name
            previous = destination.read_bytes() if destination.is_file() else None
            if previous == content:
                continue
            if previous is not None:
                saved = backup / name
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, saved)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
            assert destination.read_bytes() == content
            records.append({"path": name, "git_blob": oid,
                            "before_sha256": digest(previous) if previous else None,
                            "after_sha256": digest(content)})
        audit["related_data_restored"] = records
        target.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"related_data_restored": len(records)}))
        return
    rows = inventory()
    source = {str(p): data for p, data, _ in rows}
    catalog = json.loads(source["song_base_by_artist.json"])
    tags = json.loads(source["song_tags.json"])
    assert catalog["total_unique_songs"] == 1553
    assert len(tags["tracks"]) == 1215
    changes = [(p, data, oid) for p, data, oid in rows
               if not (BASE / p).is_file() or (BASE / p).read_bytes() != data]
    print(json.dumps({"source_tree": TREE, "documents": len(rows),
                      "changed": len(changes), "catalog": 1553, "formal_tags": 1215}))
    if "--apply" not in sys.argv:
        return
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = BASE / "archive/snapshots/recovery" / (stamp + "-before-restore")
    backup.mkdir(parents=True, exist_ok=False)
    audit = []
    # Bulk mechanical restoration: copy original bytes, not inferred metadata.
    for relative, content, oid in changes:
        destination = BASE / relative
        previous = destination.read_bytes() if destination.is_file() else None
        if previous is not None:
            saved = backup / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, saved)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        assert destination.read_bytes() == content
        audit.append({"path": str(relative), "git_blob": oid,
                      "before_sha256": digest(previous) if previous is not None else None,
                      "after_sha256": digest(content)})
    result = {"schema_version": "songbase.recovery/v1", "source_tree": TREE,
              "restored_at": datetime.now().astimezone().isoformat(),
              "backup_directory": str(backup), "audio_files_modified": 0,
              "library_tracks": 1553, "formal_tags": 1215, "restored_files": audit}
    target = BASE / "imports/2026-10-13-曲库版本恢复.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"restored": len(changes), "backup": str(backup),
                      "audit": str(target), "audio_files_modified": 0}, ensure_ascii=False))

if __name__ == "__main__":
    main()
