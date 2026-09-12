"""PySide6 Windows 桌面宠物：哥伦比娅。

运行前请先执行 prepare_assets.py 生成示例素材，或把自己的透明 GIF 放入
assets 目录。素材文件名和窗口参数均可在 config.json 中修改。
"""

from __future__ import annotations

import ctypes
import json
import random
import sys
from datetime import datetime
from enum import Enum, auto
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QIcon, QMovie, QPixmap, QTransform
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
    QWidget,
)


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"


class PetState(Enum):
    """宠物当前行为状态。"""

    IDLE = auto()
    WALKING = auto()
    ACTION = auto()
    DRAGGING = auto()


def load_config() -> dict:
    """读取配置，并把相对素材路径转换为绝对路径。"""

    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        config = json.load(file)

    config["assets"] = {
        name: BASE_DIR / relative_path
        for name, relative_path in config["assets"].items()
    }
    return config


class DesktopPet(QWidget):
    """无边框、透明、置顶的桌面宠物窗口。"""

    def __init__(self, config: dict) -> None:
        super().__init__()
        self.config = config
        self.state = PetState.IDLE
        self.facing_right = True

        # 拖拽相关数据。按下时记录鼠标和窗口起点，移动超过阈值才算拖拽。
        self.press_global_pos = QPoint()
        self.press_window_pos = QPoint()
        self.dragging = False
        self.suppress_next_release = False

        # QMovie 必须由对象持续持有，否则局部变量被回收后 GIF 会停止。
        self.movie: QMovie | None = None
        self.current_asset_name = ""
        self.voice_enabled = bool(config["voice_enabled"])
        self.auto_greeting_enabled = bool(config["auto_greeting_enabled"])
        self.last_voice_file: dict[str, str] = {}
        self.voice_manifest = self._load_voice_manifest()
        self.ctrl_was_down = False

        self._setup_window()
        self._setup_label()
        self._setup_audio()
        self._setup_timers()
        self._restore_or_place_position()
        self.play_animation("idle")
        self.schedule_next_greeting()

    def _setup_window(self) -> None:
        """设置透明窗口最关键的窗口标志和属性。"""

        self.setWindowTitle(self.config["pet_name"])
        self.setFixedSize(
            self.config["window_width"], self.config["window_height"]
        )

        # FramelessWindowHint：去掉标题栏和边框。
        # WindowStaysOnTopHint：始终位于普通窗口上方。
        # Tool：不在 Windows 任务栏创建单独按钮。
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        # 允许窗口背景使用 alpha 通道；未绘制区域会完全透明。
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

    def _setup_label(self) -> None:
        """QLabel 负责显示 QMovie 的每一帧。"""

        self.image_label = QLabel(self)
        self.image_label.setGeometry(self.rect())
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )

        # 英文台词会短暂显示在角色上方；标签本身不拦截鼠标拖拽。
        self.subtitle_label = QLabel(self)
        self.subtitle_label.setGeometry(18, 8, self.width() - 36, 74)
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self.subtitle_label.setStyleSheet(
            "QLabel { color: #fffafc; background: rgba(35, 25, 43, 205); "
            "border: 1px solid rgba(235, 203, 224, 210); border-radius: 6px; "
            "padding: 8px; font-size: 13px; }"
        )
        self.subtitle_label.hide()

    def _load_voice_manifest(self) -> dict[str, list[dict[str, str]]]:
        """读取语音清单；文件缺失时返回空分组，桌宠仍可正常运行。"""

        manifest_path = self.asset_path("voice_manifest")
        if not manifest_path.exists():
            return {"click": [], "greeting": []}
        try:
            with manifest_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
            return {
                "click": list(data.get("click", [])),
                "greeting": list(data.get("greeting", [])),
            }
        except (OSError, json.JSONDecodeError, TypeError):
            return {"click": [], "greeting": []}

    def _setup_audio(self) -> None:
        """建立 Qt 多媒体播放器；支持 WAV、MP3 等系统可解码格式。"""

        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(float(self.config["voice_volume"]))
        self.voice_player = QMediaPlayer(self)
        self.voice_player.setAudioOutput(self.audio_output)

        self.music_audio_output = QAudioOutput(self)
        self.music_audio_output.setVolume(float(self.config["music_volume"]))
        self.music_player = QMediaPlayer(self)
        self.music_player.setAudioOutput(self.music_audio_output)
        self.music_player.setLoops(QMediaPlayer.Loops.Infinite)
        self.music_lock = False

    def _setup_timers(self) -> None:
        """创建移动、随机行为和点击动作三个计时器。"""

        self.move_timer = QTimer(self)
        self.move_timer.setInterval(self.config["move_interval_ms"])
        self.move_timer.timeout.connect(self.move_one_step)

        self.behavior_timer = QTimer(self)
        self.behavior_timer.setSingleShot(True)
        self.behavior_timer.timeout.connect(self.choose_random_behavior)

        self.walk_timer = QTimer(self)
        self.walk_timer.setSingleShot(True)
        self.walk_timer.timeout.connect(self.stop_walking_then_schedule)

        self.action_timer = QTimer(self)
        self.action_timer.setSingleShot(True)
        self.action_timer.timeout.connect(self.finish_action)

        self.single_click_timer = QTimer(self)
        self.single_click_timer.setSingleShot(True)
        self.single_click_timer.timeout.connect(self.trigger_click_action)

        self.greeting_timer = QTimer(self)
        self.greeting_timer.setSingleShot(True)
        self.greeting_timer.timeout.connect(self.auto_greet)

        self.subtitle_timer = QTimer(self)
        self.subtitle_timer.setSingleShot(True)
        self.subtitle_timer.timeout.connect(self.subtitle_label.hide)

        # Poll the Windows key state so Ctrl works even when the pet is not focused.
        self.ctrl_key_timer = QTimer(self)
        self.ctrl_key_timer.setInterval(40)
        self.ctrl_key_timer.timeout.connect(self.check_ctrl_key)
        self.ctrl_key_timer.start()

    def check_ctrl_key(self) -> None:
        """Toggle background music once when either Ctrl key is pressed."""

        ctrl_down = bool(ctypes.windll.user32.GetAsyncKeyState(0x11) & 0x8000)
        if ctrl_down and not self.ctrl_was_down:
            self.toggle_background_music()
        self.ctrl_was_down = ctrl_down

    def toggle_background_music(self) -> None:
        """Start or stop the configured looping background music."""

        if self.music_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.music_player.stop()
            self.music_lock = False
            return

        music_path = self.asset_path("background_music")
        if not music_path.is_file():
            self.show_subtitle("Add background_music.mp3 to the assets folder.")
            return

        self.music_player.setSource(QUrl.fromLocalFile(str(music_path)))
        self.music_lock = True
        self.music_player.play()

    def toggle_lullaby_song(self) -> None:
        """右键切换播放《新月的摇篮曲（其一）：伴月同眠》。"""

        if self.music_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.music_player.stop()
            self.music_lock = False
            return

        song_path = self.asset_path("lullaby_song")
        if not song_path.is_file():
            return

        # 音乐播放期间进入静音锁定：停止当前语音、动作和待处理的单击。
        self.voice_player.stop()
        self.action_timer.stop()
        self.single_click_timer.stop()
        self.subtitle_timer.stop()
        self.subtitle_label.hide()
        self.start_idle()
        self.music_player.setSource(QUrl.fromLocalFile(str(song_path)))
        self.music_player.setLoops(QMediaPlayer.Loops.Infinite)
        self.music_lock = True
        self.music_player.play()

    def music_is_playing(self) -> bool:
        """判断右键歌曲是否正在播放。"""

        return self.music_lock or (
            self.music_player.playbackState()
            == QMediaPlayer.PlaybackState.PlayingState
        )

    def asset_path(self, asset_name: str) -> Path:
        return self.config["assets"][asset_name]

    def activity_zone(self) -> QRect:
        """返回当前屏幕右下角允许宠物活动的矩形区域。"""

        screen = QApplication.screenAt(self.frameGeometry().center())
        if screen is None:
            screen = QApplication.primaryScreen()
        area = screen.availableGeometry()
        right_margin = self.config["activity_zone_right_margin"]
        bottom_margin = self.config["activity_zone_bottom_margin"]
        usable_width = max(1, area.width() - right_margin)
        usable_height = max(1, area.height() - bottom_margin)
        zone_width = min(self.config["activity_zone_width"], usable_width)
        zone_height = min(self.config["activity_zone_height"], usable_height)
        return QRect(
            area.right() - zone_width - right_margin + 1,
            area.bottom() - zone_height - bottom_margin + 1,
            zone_width,
            zone_height,
        )

    def clamp_to_activity_zone(self, position: QPoint) -> QPoint:
        """把窗口左上角限制在右下活动区内，避免角色走出屏幕。"""

        zone = self.activity_zone()
        min_x = zone.left()
        max_x = max(min_x, zone.right() - self.width() + 1)
        min_y = zone.top()
        max_y = max(min_y, zone.bottom() - self.height() + 1)
        return QPoint(
            min(max(position.x(), min_x), max_x),
            min(max(position.y(), min_y), max_y),
        )

    def play_animation(self, asset_name: str) -> None:
        """加载 GIF；若缺失或无效，则显示备用 PNG。"""

        asset_path = self.asset_path(asset_name)
        self.current_asset_name = asset_name

        if self.movie is not None:
            self.movie.stop()
            self.movie.frameChanged.disconnect(self.update_movie_frame)
            self.movie.deleteLater()
            self.movie = None

        if asset_path.exists():
            movie = QMovie(str(asset_path))
            movie.setCacheMode(QMovie.CacheMode.CacheAll)
            movie.setScaledSize(QSize(self.width(), self.height()))
            if movie.isValid():
                self.movie = movie
                movie.frameChanged.connect(self.update_movie_frame)
                movie.start()
                return

        fallback = self.asset_path("fallback")
        if fallback.exists():
            pixmap = QPixmap(str(fallback)).scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.image_label.setPixmap(pixmap)
        else:
            self.image_label.setText(
                "未找到角色素材\n请先运行 prepare_assets.py"
            )
            self.image_label.setStyleSheet(
                "color: white; background: rgba(45, 36, 58, 190); "
                "padding: 14px; border-radius: 6px;"
            )

    def update_movie_frame(self) -> None:
        """逐帧显示 GIF，并根据行走方向水平镜像。"""

        if self.movie is None:
            return
        pixmap = self.movie.currentPixmap()
        if not self.facing_right:
            pixmap = pixmap.transformed(
                QTransform().scale(-1, 1),
                Qt.TransformationMode.SmoothTransformation,
            )
        self.image_label.setPixmap(pixmap)

    def schedule_next_behavior(self) -> None:
        """随机等待一段时间，再决定继续待机还是走动。"""

        delay = random.randint(
            self.config["behavior_delay_min_ms"],
            self.config["behavior_delay_max_ms"],
        )
        self.behavior_timer.start(delay)

    def choose_random_behavior(self) -> None:
        """约 65% 概率开始走路，其余时间继续待机。"""

        if self.state in (PetState.DRAGGING, PetState.ACTION):
            self.schedule_next_behavior()
            return

        if random.random() < 0.65:
            self.start_walking()
        else:
            self.start_idle()
            self.schedule_next_behavior()

    def start_idle(self) -> None:
        self.state = PetState.IDLE
        self.move_timer.stop()
        self.walk_timer.stop()
        self.play_animation("idle")

    def start_walking(self) -> None:
        """随机选择左右方向，并在随机时长后回到待机。"""

        self.state = PetState.WALKING
        self.behavior_timer.stop()
        self.facing_right = random.choice((True, False))
        self.play_animation("walk")
        self.move_timer.start()

        duration = random.randint(
            self.config["walk_duration_min_ms"],
            self.config["walk_duration_max_ms"],
        )
        self.walk_timer.start(duration)

    def stop_walking_then_schedule(self) -> None:
        """结束行走并安排下一次随机行为。"""

        self.start_idle()
        self.schedule_next_behavior()

    def move_one_step(self) -> None:
        """沿右下活动区横向移动，到达左右边缘后自动转身。"""

        if self.state is not PetState.WALKING:
            return

        zone = self.activity_zone()
        direction = 1 if self.facing_right else -1
        next_x = round(self.x() + direction * self.config["walk_speed"])
        min_x = zone.left()
        max_x = max(min_x, zone.right() - self.width() + 1)

        if next_x <= min_x:
            next_x = min_x
            self.facing_right = True
        elif next_x >= max_x:
            next_x = max_x
            self.facing_right = False

        # 自动行走固定在活动区底边，视觉上像在任务栏上方散步。
        floor_y = zone.bottom() - self.height() + 1
        self.move(next_x, floor_y)

    def trigger_click_action(self) -> None:
        """左键播放动作，并在点击语音与当前时段问候之间随机选择。"""

        if self.music_is_playing():
            return
        voice_group = random.choice(("click", "greeting"))
        if voice_group == "greeting":
            self.trigger_action("greeting", preferred_file=self.current_greeting_file())
        else:
            self.trigger_action("click")

    def current_greeting_file(self) -> str | None:
        """按照本地时间返回对应的问候文件名。"""

        hour = datetime.now().hour
        if 5 <= hour < 12:
            return "早上好.m4a"
        if 12 <= hour < 18:
            return "中午好.m4a"
        if 18 <= hour < 22:
            return "晚上好.m4a"
        return "晚安.m4a"

    def trigger_action(
        self,
        voice_group: str | None = None,
        preferred_file: str | None = None,
    ) -> None:
        """统一处理点击和自动问候触发的角色动作。"""

        if self.music_is_playing():
            return
        self.behavior_timer.stop()
        self.walk_timer.stop()
        self.move_timer.stop()
        self.state = PetState.ACTION
        self.play_animation("action")
        self.action_timer.start(self.config["click_action_duration_ms"])
        if voice_group is not None:
            self.play_random_voice(voice_group, preferred_file=preferred_file)

    def play_random_voice(
        self, group: str, preferred_file: str | None = None
    ) -> bool:
        """随机播放语音，尽量避免连续两次选择同一个文件。"""

        if not self.voice_enabled:
            return False

        manifest_path = self.asset_path("voice_manifest")
        voice_dir = manifest_path.parent
        candidates = []
        for entry in self.voice_manifest.get(group, []):
            voice_path = voice_dir / entry.get("file", "")
            if entry.get("subtitle_only") or voice_path.is_file():
                candidates.append((entry, voice_path))

        if not candidates:
            return False

        if preferred_file is not None:
            preferred = [
                item for item in candidates
                if Path(item[1]).name == preferred_file
            ]
            if preferred:
                entry, voice_path = preferred[0]
                self.last_voice_file[group] = str(voice_path)
                self.voice_player.setSource(QUrl.fromLocalFile(str(voice_path)))
                self.voice_player.play()
                self.show_subtitle(entry.get("text", ""))
                return True

        previous = self.last_voice_file.get(group)
        choices = [item for item in candidates if str(item[1]) != previous]
        entry, voice_path = random.choice(choices or candidates)
        self.last_voice_file[group] = str(voice_path) if voice_path else "<subtitle-only>"

        if entry.get("subtitle_only"):
            self.voice_player.stop()
        else:
            self.voice_player.setSource(QUrl.fromLocalFile(str(voice_path)))
            self.voice_player.play()
        self.show_subtitle(entry.get("text", ""))
        return True

    def show_subtitle(self, text: str) -> None:
        """在角色上方短暂显示英文语音对应台词。"""

        if not text:
            return
        self.subtitle_label.setText(text)
        self.subtitle_label.show()
        self.subtitle_label.raise_()
        self.subtitle_timer.start(self.config["subtitle_duration_ms"])

    def schedule_next_greeting(self) -> None:
        """在配置的随机区间内安排下一次自动英文问候。"""

        if not self.auto_greeting_enabled:
            self.greeting_timer.stop()
            return
        delay = random.randint(
            self.config["greeting_interval_min_ms"],
            self.config["greeting_interval_max_ms"],
        )
        self.greeting_timer.start(delay)

    def auto_greet(self) -> None:
        """保留问候计时器，但语音只允许由左键单击触发。"""

        # 自动问候不再播放声音或字幕，避免任何非左键操作触发对话。
        self.schedule_next_greeting()

    def set_voice_enabled(self, enabled: bool) -> None:
        self.voice_enabled = enabled
        if not enabled:
            self.voice_player.stop()
            self.subtitle_label.hide()

    def set_auto_greeting_enabled(self, enabled: bool) -> None:
        self.auto_greeting_enabled = enabled
        self.schedule_next_greeting()

    def finish_action(self) -> None:
        self.start_idle()

    def _restore_or_place_position(self) -> None:
        """恢复上次位置，并强制限制到右下角活动区域。"""

        settings = QSettings("ColumbinaPet", "DesktopPet")
        saved_position = settings.value("position")
        if isinstance(saved_position, QPoint):
            self.move(self.clamp_to_activity_zone(saved_position))
            return

        zone = self.activity_zone()
        self.move(zone.right() - self.width() + 1, zone.bottom() - self.height() + 1)

    def save_position(self) -> None:
        QSettings("ColumbinaPet", "DesktopPet").setValue("position", self.pos())

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.button() == Qt.MouseButton.RightButton:
            self.toggle_lullaby_song()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.press_global_pos = event.globalPosition().toPoint()
            self.press_window_pos = self.pos()
            self.dragging = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.buttons() & Qt.MouseButton.LeftButton:
            current = event.globalPosition().toPoint()
            delta = current - self.press_global_pos
            if delta.manhattanLength() >= self.config["drag_threshold_px"]:
                if not self.dragging:
                    self.behavior_timer.stop()
                    self.walk_timer.stop()
                    self.move_timer.stop()
                    self.action_timer.stop()
                    self.state = PetState.DRAGGING
                    self.dragging = True
                self.move(self.clamp_to_activity_zone(self.press_window_pos + delta))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.button() == Qt.MouseButton.LeftButton:
            if self.dragging:
                self.save_position()
                self.start_idle()
            elif self.suppress_next_release:
                # 双击事件已经启动行走，第二次 release 不再当成单击。
                self.suppress_next_release = False
            else:
                # 延迟少量时间，给 Qt 留出识别双击的机会。
                self.single_click_timer.start(260)
            self.dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        """双击启动一次行走；不会触发点击语音。"""

        if event.button() == Qt.MouseButton.LeftButton:
            self.single_click_timer.stop()
            self.suppress_next_release = True
            self.start_walking()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class TrayController:
    """管理 Windows 右下角系统托盘图标及菜单。"""

    def __init__(self, app: QApplication, pet: DesktopPet, config: dict) -> None:
        self.app = app
        self.pet = pet

        icon_path = config["assets"]["tray_icon"]
        icon = QIcon(str(icon_path)) if icon_path.exists() else app.windowIcon()
        self.tray = QSystemTrayIcon(icon, app)
        self.tray.setToolTip(f'{config["pet_name"]}桌面宠物')

        self.show_action = QAction("显示宠物", self.tray)
        self.show_action.triggered.connect(self.show_pet)

        self.hide_action = QAction("隐藏宠物", self.tray)
        self.hide_action.triggered.connect(self.pet.hide)

        self.voice_action = QAction("英文语音", self.tray)
        self.voice_action.setCheckable(True)
        self.voice_action.setChecked(self.pet.voice_enabled)
        self.voice_action.toggled.connect(self.pet.set_voice_enabled)

        self.greeting_action = QAction("自动打招呼", self.tray)
        self.greeting_action.setCheckable(True)
        self.greeting_action.setChecked(self.pet.auto_greeting_enabled)
        self.greeting_action.toggled.connect(
            self.pet.set_auto_greeting_enabled
        )

        self.exit_action = QAction("退出", self.tray)
        self.exit_action.triggered.connect(self.exit_app)

        menu = QMenu()
        menu.addAction(self.show_action)
        menu.addAction(self.hide_action)
        menu.addSeparator()
        menu.addAction(self.voice_action)
        menu.addAction(self.greeting_action)
        menu.addSeparator()
        menu.addAction(self.exit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.show()

    def show_pet(self) -> None:
        self.pet.show()
        self.pet.raise_()
        self.pet.activateWindow()

    def on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """双击托盘图标可快速显示或隐藏。"""

        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            if self.pet.isVisible():
                self.pet.hide()
            else:
                self.show_pet()

    def exit_app(self) -> None:
        self.pet.save_position()
        self.tray.hide()
        self.app.quit()


def main() -> int:
    app = QApplication(sys.argv)
    # 关闭宠物窗口不等于退出；应用由系统托盘继续管理。
    app.setQuitOnLastWindowClosed(False)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "无法启动", "当前系统不支持系统托盘。")
        return 1

    config = load_config()
    icon_path = config["assets"]["tray_icon"]
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    pet = DesktopPet(config)
    tray_controller = TrayController(app, pet, config)
    # 保留引用，避免 Python 垃圾回收导致托盘控制器提前消失。
    app.pet = pet  # type: ignore[attr-defined]
    app.tray_controller = tray_controller  # type: ignore[attr-defined]
    pet.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
