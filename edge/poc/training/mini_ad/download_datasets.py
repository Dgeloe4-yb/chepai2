"""Dataset catalog + download helpers for mini_ad (小广告/非法张贴) detection."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

# Primary: Roboflow illegal banner (~5k, CC BY 4.0, auto-download with free API key).
# Supplement: GitHub building facades (signboard/win_ad), FIRC 张贴小广告 (manual, China).
DATASET_CATALOG = [
    {
        "id": "roboflow_illegal_banner",
        "priority": 1,
        "name": "Roboflow Illegal Banner（首选，可脚本下载）",
        "images": 4999,
        "format": "YOLOv8",
        "class": "banner / illegal banner",
        "license": "CC BY 4.0",
        "note": "违规横幅/张贴物，体量最大，国外网络可直接下",
        "url": "https://universe.roboflow.com/illegalbannerdetection/banner-iw81k",
        "roboflow": ("illegalbannerdetection", "banner-iw81k", 1),
        "extract_to": "raw/roboflow_illegal_banner",
        "auto": True,
    },
    {
        "id": "roboflow_visual_pollution",
        "priority": 2,
        "name": "Roboflow Visual Pollution（补充 graffiti/billboard）",
        "images": "~1k+",
        "format": "YOLOv8",
        "class": "GRAFFITI, BAD_BILLBOARD, ...",
        "license": "check Roboflow page",
        "note": "prepare 脚本只保留 GRAFFITI / BAD_BILLBOARD / BROKEN_SIGNAGE 等广告相关类",
        "url": "https://universe.roboflow.com/smartathon-c7dt2/visual-pollution-fccjf",
        "roboflow": ("smartathon-c7dt2", "visual-pollution-fccjf", 1),
        "extract_to": "raw/roboflow_visual_pollution",
        "auto": True,
    },
    {
        "id": "github_building_facades",
        "priority": 3,
        "name": "Building Facades Advertising（GitHub 免费）",
        "images": 600,
        "format": "YOLOv5",
        "class": "signboard, win_ad",
        "license": "see repo LICENSE",
        "note": "建筑立面广告，prepare 只取 signboard / win_ad 两类",
        "url": "https://github.com/Urban-Research-Lab/building-facades-advertising-dataset",
        "git": "https://github.com/Urban-Research-Lab/building-facades-advertising-dataset.git",
        "extract_to": "raw/github_building_facades",
        "auto": True,
    },
    {
        "id": "firc_sticker_adv",
        "priority": 4,
        "name": "FIRC 张贴小广告（国内场景最佳，需手动购买）",
        "images": 1725,
        "format": "VOC (jpg + xml)",
        "class": "adv",
        "license": "FIRC 收费",
        "note": "墙面/电线杆小广告贴纸，与业务最贴近",
        "url": "https://blog.csdn.net/FL1623863129/article/details/126294457",
        "extract_to": "raw/firc_sticker_adv",
        "auto": False,
    },
    {
        "id": "roboflow_ads_tlv",
        "priority": 5,
        "name": "Roboflow ADS Detection TLV（补充）",
        "images": 408,
        "format": "YOLOv11",
        "class": "ads",
        "license": "check Roboflow page",
        "note": "数字/屏幕类广告，可作多样性补充",
        "url": "https://universe.roboflow.com/tlv/ads-detection-jx1us",
        "roboflow": ("tlv", "ads-detection-jx1us", 5),
        "extract_to": "raw/roboflow_ads_tlv",
        "auto": True,
    },
]

FACADES_REPO = "https://github.com/Urban-Research-Lab/building-facades-advertising-dataset.git"
FACADES_ZIP = "https://github.com/Urban-Research-Lab/building-facades-advertising-dataset/archive/refs/heads/master.zip"


def print_catalog() -> None:
    print("=" * 72)
    print("mini_ad 小广告检测 — 数据集目录（国外网络可自动下载前 3 项）")
    print("=" * 72)
    for ds in sorted(DATASET_CATALOG, key=lambda x: x["priority"]):
        auto = "自动" if ds.get("auto") else "手动"
        print(f"\n[{ds['priority']}] {ds['name']}  ({auto})")
        print(f"    规模: ~{ds['images']} 张  格式: {ds['format']}  类别: {ds['class']}")
        print(f"    许可: {ds.get('license', '?')}  说明: {ds['note']}")
        print(f"    链接: {ds['url']}")
        print(f"    目录: D:/chepai2_train/mini_ad/{ds['extract_to']}/")
    print("\n" + "=" * 72)
    print("自动下载需要 Roboflow 免费 API Key:")
    print("  1. 注册 https://app.roboflow.com/")
    print("  2. Settings → Roboflow API → 复制 Private API Key")
    print("  3. set ROBOFLOW_API_KEY=你的key")
    print("\n推荐命令:")
    print("  download_mini_ad.bat --all")
    print("  prepare_mini_ad.bat")
    print("  train_mini_ad.bat")
    print("=" * 72)


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def download_roboflow(
    workspace: str,
    project: str,
    version: int,
    location: Path,
    api_key: str,
) -> Path:
    try:
        import roboflow
    except ImportError as exc:
        raise SystemExit(
            "缺少 roboflow 包，请运行: .venv\\Scripts\\pip install roboflow"
        ) from exc

    if location.is_dir() and any(location.rglob("*.jpg")):
        print(f"skip roboflow (exists): {location}")
        return location

    location.parent.mkdir(parents=True, exist_ok=True)
    rf = roboflow.Roboflow(api_key=api_key)
    ds = rf.workspace(workspace).project(project).version(version).download(
        "yolov8",
        location=str(location),
        overwrite=False,
    )
    out = Path(ds.location)
    print(f"roboflow downloaded -> {out}")
    return out


def download_building_facades(raw_root: Path) -> Path | None:
    target = raw_root / "github_building_facades"
    converted = target / "FacadeDatasetConverted"
    if converted.is_dir() and (converted / "images").is_dir():
        print(f"skip facades (exists): {converted}")
        return converted

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_dir():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    try:
        _run(["git", "clone", "--depth", "1", FACADES_REPO, str(target)])
    except subprocess.CalledProcessError:
        print("[warn] git clone failed, trying GitHub zip ...", file=sys.stderr)
        import urllib.request

        zip_path = target.parent / "building_facades.zip"
        urllib.request.urlretrieve(FACADES_ZIP, zip_path)  # noqa: S310
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(target.parent)
        zip_path.unlink(missing_ok=True)
        extracted = target.parent / "building-facades-advertising-dataset-master"
        if extracted.is_dir():
            for child in extracted.iterdir():
                shutil.move(str(child), str(target / child.name))
            shutil.rmtree(extracted)

    if not converted.is_dir():
        print(f"[warn] facades dataset missing {converted}", file=sys.stderr)
        return None
    return converted


def extract_archives(downloads_dir: Path, raw_root: Path) -> int:
    extracted = 0
    for archive in sorted(downloads_dir.glob("*")):
        if not archive.is_file():
            continue
        suffix = archive.suffix.lower()
        name = archive.stem.lower()
        target_name = "firc_sticker_adv"
        if "street" in name or "guanggao" in name:
            target_name = "firc_street_sign"
        elif "chengguan" in name or "huwai" in name:
            target_name = "firc_chengguan"
        elif "banner" in name or "roboflow" in name:
            target_name = "roboflow_illegal_banner"
        target = raw_root / target_name
        target.mkdir(parents=True, exist_ok=True)
        try:
            if suffix == ".zip":
                with zipfile.ZipFile(archive, "r") as zf:
                    zf.extractall(target)
                extracted += 1
                print(f"extracted {archive.name} -> {target}")
            elif suffix in {".tar", ".gz", ".tgz", ".bz2", ".xz"} or name.endswith(".tar.gz"):
                shutil.unpack_archive(str(archive), str(target))
                extracted += 1
                print(f"extracted {archive.name} -> {target}")
        except Exception as exc:  # noqa: BLE001
            print(f"skip {archive.name}: {exc}", file=sys.stderr)
    return extracted


def check_raw(raw_root: Path) -> None:
    if not raw_root.is_dir():
        print(f"[missing] {raw_root}")
        return
    img_count = sum(1 for p in raw_root.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    xml_count = len(list(raw_root.rglob("*.xml")))
    txt_count = len(list(raw_root.rglob("*.txt"))) - len(list(raw_root.rglob("classes.txt")))
    print(f"raw_root={raw_root}")
    print(f"  images~={img_count}  voc_xml~={xml_count}  yolo_txt~={txt_count}")
    for sub in sorted(raw_root.iterdir()):
        if sub.is_dir():
            n_img = sum(1 for p in sub.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
            n_xml = len(list(sub.rglob("*.xml")))
            n_lbl = len(list(sub.rglob("labels/*.txt"))) if (sub / "labels").is_dir() else 0
            print(f"  {sub.name}: images~={n_img} xml~={n_xml} yolo_labels~={n_lbl}")


def download_all(work_root: Path, api_key: str | None, skip_roboflow: bool) -> None:
    raw_root = work_root / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)

    try:
        download_building_facades(raw_root)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] building facades download failed: {exc}", file=sys.stderr)

    if skip_roboflow:
        print("skip roboflow (--skip-roboflow)")
        return

    key = api_key or os.environ.get("ROBOFLOW_API_KEY", "").strip()
    if not key:
        print(
            "\n[warn] 未设置 ROBOFLOW_API_KEY，跳过 Roboflow 自动下载（~5k 主数据集）。\n"
            "       仍可使用 GitHub facades；或设置 key 后重新运行 download_mini_ad.bat --all\n"
        )
        return

    for ds in DATASET_CATALOG:
        rf = ds.get("roboflow")
        if not rf or not ds.get("auto"):
            continue
        workspace, project, version = rf
        dest = work_root / ds["extract_to"]
        try:
            download_roboflow(workspace, project, version, dest, key)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] roboflow {project} failed: {exc}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="小广告数据集：目录说明 + 自动下载")
    parser.add_argument("--work-root", type=Path, default=Path("D:/chepai2_train/mini_ad"))
    parser.add_argument("--list", action="store_true", help="打印数据集目录")
    parser.add_argument("--check", action="store_true", help="检查 raw 目录")
    parser.add_argument("--extract", action="store_true", help="解压 downloads/ 下的压缩包")
    parser.add_argument("--all", action="store_true", help="自动下载 GitHub + Roboflow")
    parser.add_argument("--skip-roboflow", action="store_true")
    parser.add_argument("--roboflow-key", type=str, default="", help="或设环境变量 ROBOFLOW_API_KEY")
    args = parser.parse_args()

    work_root = args.work_root.resolve()
    downloads = work_root / "downloads"
    raw_root = work_root / "raw"
    downloads.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)

    print_catalog()

    if args.all:
        download_all(work_root, args.roboflow_key or None, args.skip_roboflow)

    if args.extract:
        n = extract_archives(downloads, raw_root)
        print(f"extracted {n} archive(s)")

    if args.check or args.all or args.extract:
        print()
        check_raw(raw_root)


if __name__ == "__main__":
    main()
