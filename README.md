# 哥伦比娅桌面宠物

一个基于 **PySide6** 的 Windows 桌面宠物。角色采用 Q 版哥伦比娅与月亮形象，支持透明窗口、眨眼、月亮锚点摆动、鼠标交互、英文语音、自动问候和右键音乐播放。

> 适用于 Windows 10/11。项目中的角色图片、音乐和相关素材请仅在你拥有使用权的前提下使用，并遵守原作者与版权方的相关规则。

## 功能

- 无边框、背景透明、窗口置顶
- 300 × 279 的小尺寸桌宠窗口
- 左键拖动，位置自动保存
- 左键单击：动作动画、英文点击语音和字幕
- 左键双击：开始一次左右行走，结束后停在原地
- 仅在桌面右下角活动区域内行走
- 待机、行走、点击动画包含眨眼效果
- 月亮最高点固定，整体围绕锚点左右摆动约 10°
- 保留自动问候计时器，但语音只由左键单击触发
- 右键播放/停止《新月的摇篮曲（其一）：伴月同眠》
- 音乐播放期间自动静音，点击语音和自动问候暂停
- Windows 系统托盘菜单：显示、隐藏、语音开关、自动问候开关、退出

## 项目结构

```text
哥伦比娅桌宠/
├─ main.py                         # 桌宠主程序
├─ config.json                     # 尺寸、行为、音量和素材路径
├─ prepare_assets.py               # 从源图生成透明 GIF 和眨眼动画
├─ prepare_voice_pack.py           # 使用 Windows TTS 生成示例英文语音
├─ requirements.txt                # 运行主程序所需依赖
├─ requirements-assets.txt         # 重新抠图时的额外依赖
├─ start_pet.bat                  # Windows 双击启动脚本
└─ assets/
   ├─ idle.gif                    # 待机动画
   ├─ walk.gif                    # 行走动画
   ├─ action.gif                  # 点击动作动画
   ├─ columbina.png               # 静态备用图
   ├─ tray_icon.png               # 托盘图标
   ├─ music/
   │  └─ lullaby_of_the_new_moon_somnias_a_luna.mp3
   ├─ voices/
   │  ├─ manifest.json            # 音频文件与字幕清单
   │  ├─ click/*.wav              # 点击语音
   │  └─ greeting/*.wav           # 自动问候语音
   └─ source/
      └─ columbina_source.jpg     # 源图片
```

## 安装

建议使用 Python 3.10 或更高版本：

```powershell
cd "D:\python\哥伦比娅桌宠"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
```

主程序依赖：

- `PySide6`：窗口、动画、定时器、托盘和音频播放
- `Pillow`：重新生成图片素材时使用

## 启动

```powershell
python main.py
```

也可以直接双击 `start_pet.bat`。

## 操作方式

| 操作 | 功能 |
| --- | --- |
| 左键拖动 | 在右下活动区内移动角色 |
| 左键单击 | 播放动作，并从点击语音或当前时段问候中选择一条；唯一的语音触发方式 |
| 左键双击 | 开始一次左右行走 |
| 右键单击 | 播放或停止新月摇篮曲 |
| 双击托盘图标 | 显示/隐藏宠物 |
| 托盘菜单 | 显示、隐藏、语音开关、自动问候开关、退出 |
| `Ctrl` | 切换可选循环背景音乐 |

音乐播放时会进入静音锁定：不会触发点击语音，也不会自动打招呼。再次右键停止音乐后，左键点击即可恢复角色对话。

## 音乐文件

右键歌曲默认路径：

```text
assets/music/lullaby_of_the_new_moon_somnias_a_luna.mp3
```

如果替换歌曲，可以放入其他 MP3 文件，并在 `config.json` 的 `assets` 中修改 `lullaby_song` 路径。MP3 通常具有较好的 Windows/Qt 兼容性。

## 英文语音

项目包含 3 条点击语音和 4 条问候语音。左键点击时会在普通点击语音和当前时段问候之间选择：05:00–11:59 为“早上好”，12:00–17:59 为“中午好”，18:00–21:59 为“晚上好”，22:00–04:59 为“晚安”。自动问候计时器不会主动播放声音。

重新生成：

```powershell
python prepare_voice_pack.py
```

替换自己的合法音频时，将 WAV/MP3 放入 `assets/voices/click` 或 `assets/voices/greeting`，然后同步修改 `assets/voices/manifest.json` 中的 `file` 和 `text` 字段。

## 重新生成角色动画

如果替换了源图片，先安装额外依赖：

```powershell
pip install -r requirements-assets.txt
```

然后运行：

```powershell
python prepare_assets.py "D:\图片\角色.png"
```

生成器使用动漫分割模型移除棋盘背景，关闭 alpha matting，不对头发使用高斯模糊。眨眼区域、月亮锚点和摆动角度可以在 `prepare_assets.py` 中调整。

## 配置

编辑 `config.json` 可调整：

- `window_width`、`window_height`：桌宠显示尺寸
- `walk_speed`：行走速度
- `activity_zone_width`、`activity_zone_height`：右下活动范围
- `voice_volume`、`music_volume`：语音和音乐音量
- `greeting_interval_min_ms`、`greeting_interval_max_ms`：自动问候间隔
- `voice_enabled`、`auto_greeting_enabled`：默认开关状态

## 打包 EXE

```powershell
pip install pyinstaller
pyinstaller --noconfirm --windowed --name ColumbinaPet `
  --add-data "config.json;." --add-data "assets;assets" main.py
```

结果位于 `dist\ColumbinaPet\ColumbinaPet.exe`。建议使用目录模式，后续替换 GIF、语音和音乐更方便。

## 常见问题

### 右键没有声音

确认文件存在于 `assets/music/lullaby_of_the_new_moon_somnias_a_luna.mp3`，并检查 Windows 音量混合器和默认输出设备。

### 点击没有语音

确认托盘菜单中的“英文语音”处于勾选状态，并检查 `assets/voices/manifest.json` 中的路径与实际文件名一致。

### 想让角色更大或更小

修改 `config.json` 中的 `window_width` 和 `window_height`，保持两者比例接近 `560:520`，然后重新启动程序。

## 许可证与素材声明

本项目代码可作为个人学习和桌面工具示例使用。角色形象、音乐、语音及图片素材可能属于其原作者或版权方；发布到 GitHub 前，请确认你有权公开分发这些文件。若没有分发授权，建议仅上传代码和空的素材目录说明，不要提交受版权保护的音频或图片。
