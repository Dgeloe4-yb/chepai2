"""Generate alert wav files with Windows Chinese TTS (Microsoft Huihui)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "agent" / "voice"
PHRASES = {
    "dual_slot": "请注意，车辆占用两个车位，请规范停放",
    "car_in_bus_slot": "请注意，轿车停入公交车位，请立即驶离",
    "bad_park": "请注意，车辆未停正，请调整车位",
    "mini_ad": "请注意，检测到违规小广告",
    "non_sedan": "请注意，非轿车进入限制区域",
    "oil_car": "请注意，燃油车进入新能源区域",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ps = r"""
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SelectVoice('Microsoft Huihui Desktop')
$synth.Rate = -1
$synth.Volume = 100
$pairs = @{
"""
    for k, v in PHRASES.items():
        wav = OUT / f"{k}.wav"
        # escape for powershell single-quoted path/text carefully
        ps += f"  '{k}' = @('{wav.as_posix().replace('/', '\\')}', '{v}');\n"
    ps += r"""
}
foreach ($k in $pairs.Keys) {
  $path = $pairs[$k][0]
  $text = $pairs[$k][1]
  Write-Host "gen $k -> $path"
  $synth.SetOutputToWaveFile($path)
  $synth.Speak($text)
  $synth.SetOutputToNull()
}
$synth.Dispose()
Write-Host DONE
"""
    tmp = OUT / "_gen_voice.ps1"
    tmp.write_text(ps, encoding="utf-8-sig")
    print(f"writing wavs to {OUT}", flush=True)
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(tmp)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    print(r.stdout)
    if r.stderr.strip():
        print(r.stderr, file=sys.stderr)
    if r.returncode != 0:
        raise SystemExit(r.returncode)
    for name in PHRASES:
        p = OUT / f"{name}.wav"
        if not p.is_file() or p.stat().st_size < 1000:
            raise SystemExit(f"missing/bad wav: {p}")
        print(f"  ok {p.name} {p.stat().st_size} bytes")
    tmp.unlink(missing_ok=True)
    print("all wav ready")


if __name__ == "__main__":
    main()
