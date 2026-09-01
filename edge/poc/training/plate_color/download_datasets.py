"""Download / extract CCPD public datasets for plate color training."""

from __future__ import annotations

import argparse
import shutil
import zipfile
from pathlib import Path

# Official links from detectRecog/CCPD
CCPD_GREEN_GDRIVE_ID = "1m8w1kFxnCEiqz_-t2vTcgrgqNIv986PR"
CCPD2019_GDRIVE_ID = "1rdEsCUcIUaYOVRkx5IMTRNA7PcGMmSgc"  # official CCPD2019.tar.xz
CCPD2019_HF_REPO = "JorgeLlorente/CCPD-Dataset"
CCPD2019_HF_FILE = "CCPD2019.tar.xz"


def ensure_gdown() -> None:
    try:
        import gdown  # noqa: F401
    except ImportError as exc:
        raise SystemExit("请先安装 gdown: .venv\\Scripts\\pip install gdown") from exc


def download_google_file(file_id: str, dst: Path) -> None:
    import gdown

    dst.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://drive.google.com/uc?id={file_id}"
    gdown.download(url, str(dst), quiet=False)


def download_ccpd2019_hf(dst: Path) -> Path:
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise SystemExit("请先安装 huggingface_hub: .venv\\Scripts\\pip install huggingface_hub") from exc

    dst.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading CCPD2019 from HuggingFace ({CCPD2019_HF_REPO}) ...")
    downloaded = hf_hub_download(
        CCPD2019_HF_REPO,
        CCPD2019_HF_FILE,
        repo_type="dataset",
        local_dir=str(dst.parent),
    )
    archive = Path(downloaded)
    if archive != dst and archive.exists():
        shutil.copy2(archive, dst)
    return dst


def extract_archive(archive: Path, dst_root: Path) -> None:
    dst_root.mkdir(parents=True, exist_ok=True)
    if archive.suffix.lower() == ".zip":
        with zipfile.ZipFile(archive, "r") as zf:
            zf.extractall(dst_root)
        return
    if archive.suffix.lower() in {".tar", ".gz", ".tgz", ".bz2", ".xz"} or archive.name.endswith(".tar.gz"):
        shutil.unpack_archive(str(archive), str(dst_root))
        return
    raise SystemExit(f"不支持的压缩包: {archive}")


def find_and_move_ccpd2019(extracted_root: Path, target_root: Path) -> None:
    target_root.mkdir(parents=True, exist_ok=True)
    for subset in (
        "ccpd_base",
        "ccpd_blur",
        "ccpd_challenge",
        "ccpd_db",
        "ccpd_fn",
        "ccpd_rotate",
        "ccpd_tilt",
        "ccpd_weather",
    ):
        matches = list(extracted_root.rglob(subset))
        for match in matches:
            if match.is_dir() and match.name == subset:
                dst = target_root / subset
                if dst.exists():
                    continue
                shutil.move(str(match), str(dst))
                print(f"moved {match} -> {dst}")


def find_and_move_ccpd_green(extracted_root: Path, target_root: Path) -> None:
    dst = target_root / "ccpd_green"
    if dst.exists():
        print(f"already exists: {dst}")
        return
    matches = list(extracted_root.rglob("ccpd_green"))
    for match in matches:
        if match.is_dir():
            shutil.move(str(match), str(dst))
            print(f"moved {match} -> {dst}")
            return
    if any((extracted_root / s).exists() for s in ("train", "test", "val")):
        dst.mkdir(parents=True, exist_ok=True)
        shutil.move(str(extracted_root), str(dst / "_flat"))
        print(f"moved flat green dataset -> {dst / '_flat'}")


def ensure_ccpd2019(download_dir: Path, ccpd2019_root: Path) -> None:
    archive = download_dir / CCPD2019_HF_FILE
    if not archive.exists():
        alt = download_dir / "ccpd2019.zip"
        if alt.exists():
            archive = alt
    if not archive.exists():
        print("Downloading CCPD2019 (large, may take long) ...")
        try:
            download_google_file(CCPD2019_GDRIVE_ID, download_dir / "ccpd2019.zip")
            archive = download_dir / "ccpd2019.zip"
        except Exception as exc:
            print(f"Google Drive download failed: {exc}")
            try:
                archive = download_ccpd2019_hf(download_dir / CCPD2019_HF_FILE)
            except Exception as hf_exc:
                print(f"HuggingFace download failed: {hf_exc}")
                print("请手动从 https://github.com/detectRecog/CCPD 下载 CCPD2019 并解压到:")
                print(f"  {ccpd2019_root}")
                return
    if archive.exists() and not (ccpd2019_root / "ccpd_base").exists():
        extract_root = download_dir / "extract2019"
        if not extract_root.exists() or not any(extract_root.iterdir()):
            print(f"Extracting {archive.name} ...")
            extract_archive(archive, extract_root)
        find_and_move_ccpd2019(extract_root, ccpd2019_root)


def main() -> None:
    parser = argparse.ArgumentParser(description="下载 CCPD 蓝牌/绿牌公开数据集")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument("--download-dir", type=Path, default=Path(__file__).resolve().parents[4] / "data" / "downloads")
    parser.add_argument("--only-green", action="store_true", help="只下载 CCPD-Green（体积较小）")
    parser.add_argument("--skip-download", action="store_true", help="只解压已有压缩包")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    download_dir = args.download_dir.resolve()
    ccpd2019_root = repo_root / "data" / "CCPD2019"
    ccpd2020_root = repo_root / "data" / "CCPD2020"

    green_zip = download_dir / "ccpd_green.zip"
    if green_zip.exists() and not (ccpd2020_root / "ccpd_green").exists():
        extract_archive(green_zip, download_dir / "extract_green")
        find_and_move_ccpd_green(download_dir / "extract_green", ccpd2020_root)

    if not args.skip_download:
        if not green_zip.exists():
            ensure_gdown()
            print("Downloading CCPD-Green ...")
            download_google_file(CCPD_GREEN_GDRIVE_ID, green_zip)
        extract_archive(green_zip, download_dir / "extract_green")
        find_and_move_ccpd_green(download_dir / "extract_green", ccpd2020_root)

        if not args.only_green:
            ensure_ccpd2019(download_dir, ccpd2019_root)
    elif not args.only_green:
        ensure_ccpd2019(download_dir, ccpd2019_root)

    print("\nExpected layout:")
    print(f"  {ccpd2019_root}/ccpd_base/*.jpg")
    print(f"  {ccpd2020_root}/ccpd_green/train|test|val/*.jpg")


if __name__ == "__main__":
    main()
