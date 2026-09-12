"""使用 Windows 自带英文语音合成器生成示例 WAV 语音包。

生成的台词来自 assets/voices/manifest.json，属于本项目原创示例台词，
不是《原神》官方角色录音。脚本仅适用于 Windows，无需额外 pip 依赖。
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
VOICE_DIR = BASE_DIR / "assets" / "voices"
MANIFEST_PATH = VOICE_DIR / "manifest.json"

# PowerShell 使用 System.Speech 查找英文女性语音；若本机没有，则使用默认语音。
POWERSHELL_SCRIPT = r"""
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voices = $synth.GetInstalledVoices() | Where-Object { $_.Enabled }
$selected = $voices | Where-Object {
    $_.VoiceInfo.Culture.Name -like 'en-*' -and
    $_.VoiceInfo.Gender -eq [System.Speech.Synthesis.VoiceGender]::Female
} | Select-Object -First 1
if (-not $selected) {
    $selected = $voices | Where-Object {
        $_.VoiceInfo.Culture.Name -like 'en-*'
    } | Select-Object -First 1
}
if ($selected) {
    $synth.SelectVoice($selected.VoiceInfo.Name)
}
$synth.Rate = -1
$synth.Volume = 92
$synth.SetOutputToWaveFile($env:COLUMBINA_VOICE_OUTPUT)
$synth.Speak($env:COLUMBINA_VOICE_TEXT)
$synth.Dispose()
"""


def main() -> None:
    if os.name != "nt":
        raise SystemExit("prepare_voice_pack.py 只支持 Windows。")

    with MANIFEST_PATH.open("r", encoding="utf-8") as file:
        manifest = json.load(file)

    entries = [
        entry
        for group in ("click", "greeting")
        for entry in manifest.get(group, [])
    ]
    windows_dir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    powershell = (
        windows_dir
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    if not powershell.exists():
        raise FileNotFoundError("没有找到 Windows PowerShell，无法生成系统 TTS 语音。")

    for entry in entries:
        output_path = (VOICE_DIR / entry["file"]).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["COLUMBINA_VOICE_OUTPUT"] = str(output_path)
        env["COLUMBINA_VOICE_TEXT"] = entry["text"]
        subprocess.run(
            [
                str(powershell),
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                POWERSHELL_SCRIPT,
            ],
            check=True,
            env=env,
        )
        print(f"已生成：{output_path.name}")

    print(f"英文语音包已生成到：{VOICE_DIR}")


if __name__ == "__main__":
    main()
