# Self-Awareness Module (自感知模块) 完整设计

## 核心理念

```
框架层：定义感知大类（抽象接口）
    ↓
插件层：实现具体感知器（硬件/API封装）
    ↓
决策层：感知分类 + 意图识别 + 优先级判断
```

**设计原则**：
- 感知器类似人体器官（眼耳鼻口手等）
- 框架定义大类：音频/视频/文字/图片/传感器/事件
- 插件实现具体：麦克风/摄像头/邮件/文件监听等
- 触发模式由插件决定：轮询/事件驱动/混合
- 生命周期按需启动：由插件决定
- 多模态处理由插件负责：不强制转换方式
- 感知决策系统：去重+分类+意图识别+优先级+合并

---

## 1. 框架层：感知器基类定义

```python
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, AsyncIterator, Callable, Dict, Any
import asyncio
import time

class PerceptionType(Enum):
    """感知类型 - 框架定义的大类"""
    AUDIO = "audio"          # 音频输入
    VIDEO = "video"          # 视频输入
    TEXT = "text"            # 文字输入
    IMAGE = "image"          # 图片输入
    SENSOR_DATA = "sensor"   # 传感器数据
    EVENT = "event"          # 事件触发


class TriggerMode(Enum):
    """触发模式"""
    POLL = "poll"            # 轮询模式
    EVENT_DRIVEN = "event"   # 事件驱动模式
    HYBRID = "hybrid"        # 混合模式


class Sensor(ABC):
    """感知器基类 - 框架定义"""

    @property
    @abstractmethod
    def name(self) -> str:
        """感知器名称"""
        pass

    @property
    @abstractmethod
    def perception_type(self) -> PerceptionType:
        """感知类型（框架定义的大类）"""
        pass

    @property
    @abstractmethod
    def trigger_mode(self) -> TriggerMode:
        """触发模式（由插件决定）"""
        pass

    @property
    def priority(self) -> int:
        """默认优先级（0-5）"""
        return 0

    @property
    def enabled(self) -> bool:
        """是否启用（由插件按需决定）"""
        return True

    # ========== 生命周期 ==========

    async def start(self):
        """启动感知器（由插件决定何时调用）"""
        pass

    async def stop(self):
        """停止感知器"""
        pass

    async def is_available(self) -> bool:
        """检查感知器是否可用（硬件/API是否就绪）"""
        return True

    # ========== 感知数据获取 ==========

    async def sense(self) -> Optional['Perception']:
        """执行一次感知（轮询模式）"""
        return None

    async def listen(self, callback: Callable[['Perception'], None]):
        """监听感知输入（事件驱动模式）"""
        pass

    # ========== 元数据 ==========

    @property
    def description(self) -> str:
        """感知器描述"""
        return ""

    @property
    def config_schema(self) -> dict:
        """配置参数schema（用于UI配置）"""
        return {}
```

---

## 2. 插件层：具体感知器实现

### 2.1 音频感知器

```python
class AudioSensor(Sensor):
    """音频感知器 - 框架基类"""
    @property
    def perception_type(self) -> PerceptionType:
        return PerceptionType.AUDIO


# 插件实现1：麦克风感知器
class MicrophoneSensor(AudioSensor):
    """麦克风感知器 - 插件实现"""

    name = "microphone"
    perception_type = PerceptionType.AUDIO
    trigger_mode = TriggerMode.HYBRID  # 混合模式

    def __init__(self, config: dict, perception_manager):
        self.config = config
        self.perception_manager = perception_manager
        self.sample_rate = config.get("sample_rate", 16000)
        self.channels = config.get("channels", 1)
        self.audio_queue = asyncio.Queue()

    @property
    def enabled(self) -> bool:
        """按需决定：只有在配置中启用才启动"""
        return self.config.get("enabled", False)

    async def start(self):
        """启动麦克风监听"""
        if not await self.is_available():
            logger.error("麦克风不可用")
            return

        # 启动后台监听线程
        asyncio.create_task(self._listen_loop())

    async def _listen_loop(self):
        """后台监听循环"""
        try:
            import pyaudio

            p = pyaudio.PyAudio()
            stream = p.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=1024
            )

            while self.enabled:
                try:
                    # 读取音频数据
                    data = stream.read(1024, exception_on_overflow=False)

                    # 转为感知输入（由插件决定处理方式）
                    perception = await self._process_audio(data)

                    if perception:
                        # 推送到感知管理器
                        await self.perception_manager.receive(perception)

                except Exception as e:
                    logger.error(f"麦克风监听异常: {e}")

            stream.stop_stream()
            stream.close()
            p.terminate()

        except ImportError:
            logger.warning("pyaudio未安装，麦克风感知器不可用")

    async def _process_audio(self, audio_data: bytes) -> Optional['Perception']:
        """处理音频数据（插件决定转换方式）"""

        # 方案A：转文字（语音识别）
        if self.config.get("transcribe", True):
            text = await self._speech_to_text(audio_data)
            if text:
                from perception import Perception
                return Perception(
                    type=PerceptionType.AUDIO,
                    source="microphone",
                    data={
                        "text": text,
                        "audio_bytes": audio_data,  # 保留原始数据
                        "transcription": True
                    },
                    timestamp=time.time(),
                    priority=self._detect_priority(text)
                )

        # 方案B：保持原始音频
        from perception import Perception
        return Perception(
            type=PerceptionType.AUDIO,
            source="microphone",
            data={"audio_bytes": audio_data},
            timestamp=time.time()
        )

    async def _speech_to_text(self, audio_data: bytes) -> Optional[str]:
        """语音转文字"""
        # 调用ASR模型/API
        # 例如：Whisper、Google Speech-to-Text
        pass

    def _detect_priority(self, text: str) -> int:
        """检测优先级"""
        # 紧急关键词
        urgent_keywords = ["紧急", "救命", "报警", "help"]
        if any(kw in text for kw in urgent_keywords):
            return 5
        return 0

    @property
    def description(self) -> str:
        return "麦克风音频输入，支持语音识别"

    @property
    def config_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "enabled": {
                    "type": "boolean",
                    "description": "是否启用麦克风",
                    "default": False
                },
                "sample_rate": {
                    "type": "integer",
                    "description": "采样率",
                    "default": 16000
                },
                "transcribe": {
                    "type": "boolean",
                    "description": "是否转换为文字",
                    "default": True
                }
            }
        }


# 插件实现2：音频文件监听
class AudioFileSensor(AudioSensor):
    """音频文件监听器 - 插件实现"""

    name = "audio_file"
    perception_type = PerceptionType.AUDIO
    trigger_mode = TriggerMode.EVENT  # 事件驱动

    def __init__(self, config: dict, perception_manager):
        self.config = config
        self.perception_manager = perception_manager
        self.watch_dir = config["watch_dir"]

    async def start(self):
        """启动文件监听"""
        asyncio.create_task(self._watch_files())

    async def _watch_files(self):
        """监听音频文件"""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            class AudioFileHandler(FileSystemEventHandler):
                def __init__(self, sensor):
                    self.sensor = sensor

                def on_created(self, event):
                    if not event.is_directory and event.src_path.endswith(('.mp3', '.wav', '.m4a')):
                        asyncio.create_task(
                            self.sensor._process_file(event.src_path)
                        )

            observer = Observer()
            observer.schedule(AudioFileHandler(self), self.watch_dir, recursive=True)
            observer.start()

            while self.enabled:
                await asyncio.sleep(1)

            observer.stop()

        except ImportError:
            logger.warning("watchdog未安装，音频文件监听不可用")

    async def _process_file(self, file_path: str):
        """处理音频文件"""
        with open(file_path, 'rb') as f:
            audio_data = f.read()

        from perception import Perception
        perception = Perception(
            type=PerceptionType.AUDIO,
            source="audio_file",
            data={"file_path": file_path, "audio_bytes": audio_data},
            timestamp=time.time()
        )

        await self.perception_manager.receive(perception)
```

### 2.2 视频感知器

```python
class VideoSensor(Sensor):
    """视频感知器 - 框架基类"""
    @property
    def perception_type(self) -> PerceptionType:
        return PerceptionType.VIDEO


# 插件实现：摄像头感知器
class CameraSensor(VideoSensor):
    """摄像头感知器 - 插件实现"""

    name = "camera"
    perception_type = PerceptionType.VIDEO
    trigger_mode = TriggerMode.POLL  # 轮询模式

    def __init__(self, config: dict):
        self.config = config
        self.device_id = config.get("device_id", 0)
        self.fps = config.get("fps", 15)

    @property
    def enabled(self) -> bool:
        return self.config.get("enabled", False)

    async def sense(self) -> Optional['Perception']:
        """获取一帧画面"""
        if not self.enabled:
            return None

        try:
            import cv2

            cap = cv2.VideoCapture(self.device_id)
            ret, frame = cap.read()
            cap.release()

            if not ret:
                return None

            # 插件决定如何处理视频帧
            return await self._process_frame(frame)

        except ImportError:
            logger.warning("opencv-python未安装，摄像头感知器不可用")
            return None

    async def _process_frame(self, frame: np.ndarray) -> 'Perception':
        """处理视频帧（插件决定）"""

        # 方案A：提取视觉描述
        if self.config.get("describe", True):
            description = await self._describe_frame(frame)
            objects = await self._detect_objects(frame)

            from perception import Perception
            return Perception(
                type=PerceptionType.VIDEO,
                source="camera",
                data={
                    "description": description,
                    "objects": objects,
                    "frame_bytes": self._encode_frame(frame)
                },
                timestamp=time.time(),
                priority=self._detect_priority(objects)
            )

        # 方案B：保持原始帧
        from perception import Perception
        return Perception(
            type=PerceptionType.VIDEO,
            source="camera",
            data={"frame_bytes": self._encode_frame(frame)},
            timestamp=time.time()
        )

    def _encode_frame(self, frame: np.ndarray) -> bytes:
        """编码视频帧为JPEG"""
        import cv2
        return cv2.imencode('.jpg', frame)[1].tobytes()

    async def _describe_frame(self, frame: np.ndarray) -> str:
        """描述画面内容"""
        # 调用视觉LLM（如GPT-4V、LLaVA）
        # prompt = "请描述这个画面..."
        pass

    async def _detect_objects(self, frame: np.ndarray) -> list:
        """检测物体"""
        # 调用物体检测模型（如YOLO）
        pass

    def _detect_priority(self, objects: list) -> int:
        """检测优先级"""
        # 检测到危险物品
        dangerous_objects = ["knife", "gun", "fire"]
        if any(obj in objects for obj in dangerous_objects):
            return 5
        return 0


# 插件实现：视频流监听
class VideoStreamSensor(VideoSensor):
    """视频流监听器（RTSP等）- 插件实现"""

    name = "video_stream"
    perception_type = PerceptionType.VIDEO
    trigger_mode = TriggerMode.EVENT  # 事件驱动

    def __init__(self, config: dict, perception_manager):
        self.config = config
        self.perception_manager = perception_manager
        self.stream_url = config["stream_url"]
        self.fps = config.get("fps", 15)

    async def start(self):
        """启动流监听"""
        if not self.enabled:
            return

        asyncio.create_task(self._stream_loop())

    async def _stream_loop(self):
        """流监听循环"""
        try:
            import cv2

            cap = cv2.VideoCapture(self.stream_url)

            while self.enabled:
                ret, frame = cap.read()
                if not ret:
                    break

                perception = await self._process_frame(frame)
                if perception:
                    await self.perception_manager.receive(perception)

                # 控制帧率
                await asyncio.sleep(1 / self.fps)

            cap.release()

        except Exception as e:
            logger.error(f"视频流异常: {e}")
```

### 2.3 文字感知器

```python
class TextSensor(Sensor):
    """文字感知器 - 框架基类"""
    @property
    def perception_type(self) -> PerceptionType:
        return PerceptionType.TEXT


# 插件实现1：用户消息感知器
class UserMessageSensor(TextSensor):
    """用户消息感知器 - 插件实现"""

    name = "user_message"
    perception_type = PerceptionType.TEXT
    trigger_mode = TriggerMode.EVENT  # 事件驱动

    def __init__(self, config: dict, perception_manager):
        self.config = config
        self.perception_manager = perception_manager
        self.message_source = config["source"]  # "websocket", "cli", "api"

    async def start(self):
        """启动监听"""
        if self.message_source == "websocket":
            asyncio.create_task(self._listen_websocket())
        elif self.message_source == "cli":
            asyncio.create_task(self._listen_cli())

    async def _listen_websocket(self):
        """监听WebSocket消息"""
        async for message in self.websocket_connection:
            from perception import Perception
            perception = Perception(
                type=PerceptionType.TEXT,
                source="websocket",
                data={
                    "text": message,
                    "user_id": message.user_id
                },
                timestamp=time.time(),
                priority=0  # 普通优先级
            )
            await self.perception_manager.receive(perception)

    async def _listen_cli(self):
        """监听CLI输入"""
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.create_subprocess(
            sys.stdin,
            stdin=reader,
            stdout=asyncio.subprocess.PIPE
        )

        async for line in reader:
            from perception import Perception
            perception = Perception(
                type=PerceptionType.TEXT,
                source="cli",
                data={"text": line.decode().strip()},
                timestamp=time.time()
            )
            await self.perception_manager.receive(perception)


# 插件实现2：邮件感知器
class EmailSensor(TextSensor):
    """邮件感知器 - 插件实现"""

    name = "email"
    perception_type = PerceptionType.TEXT
    trigger_mode = TriggerMode.POLL  # 轮询模式

    def __init__(self, config: dict):
        self.config = config
        self.imap_server = config["imap_server"]
        self.username = config["username"]
        self.password = config["password"]
        self.important_senders = config.get("important_senders", [])
        self.check_interval = config.get("check_interval", 60)  # 秒

    async def sense(self) -> Optional['Perception']:
        """检查新邮件"""
        try:
            import imaplib
            from email import email_from_string

            imap = imaplib.IMAP4_SSL(self.imap_server)
            imap.login(self.username, self.password)
            imap.select('INBOX')

            # 搜索未读邮件
            status, messages = imap.search(None, 'UNSEEN')

            if messages[0]:
                # 获取第一封未读邮件
                msg_id = messages[0].split()[0]
                status, msg_data = imap.fetch(msg_id, '(RFC822)')
                email_content = msg_data[0][1]

                # 解析邮件
                email_msg = email_from_string(email_content)

                from perception import Perception
                perception = Perception(
                    type=PerceptionType.TEXT,
                    source="email",
                    data={
                        "from": email_msg['From'],
                        "subject": email_msg['Subject'],
                        "body": email_msg.get_payload(),
                        "email_id": msg_id
                    },
                    timestamp=time.time(),
                    priority=self._detect_priority(email_msg)
                )

                imap.close()
                return perception

            imap.close()
            return None

        except Exception as e:
            logger.error(f"邮件检查失败: {e}")
            return None

    def _detect_priority(self, email_msg) -> int:
        """检测邮件优先级"""
        subject = (email_msg.get('Subject') or "").lower()

        # 紧急邮件
        if any(kw in subject for kw in ['urgent', '紧急', 'asap', '重要']):
            return 4

        # 重要发件人
        sender = email_msg.get('From', '')
        if any(important in sender for important in self.important_senders):
            return 3

        return 0


# 插件实现3：文件变化感知器
class FileMonitorSensor(TextSensor):
    """文件变化感知器 - 插件实现"""

    name = "file_monitor"
    perception_type = PerceptionType.TEXT
    trigger_mode = TriggerMode.EVENT

    def __init__(self, config: dict, perception_manager):
        self.config = config
        self.perception_manager = perception_manager
        self.watch_paths = config["watch_paths"]

    async def start(self):
        """启动文件监听"""
        asyncio.create_task(self._watch_files())

    async def _watch_files(self):
        """监听文件变化"""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            class FileHandler(FileSystemEventHandler):
                def __init__(self, sensor):
                    self.sensor = sensor

                def on_modified(self, event):
                    if not event.is_directory:
                        asyncio.create_task(
                            self.sensor._process_file(event.src_path)
                        )

            observer = Observer()
            for path in self.watch_paths:
                observer.schedule(FileHandler(self), path, recursive=True)

            observer.start()

            while self.enabled:
                await asyncio.sleep(1)

            observer.stop()

        except ImportError:
            logger.warning("watchdog未安装，文件监听不可用")

    async def _process_file(self, file_path: str):
        """处理文件变化"""
        with open(file_path, 'r') as f:
            content = f.read()

        from perception import Perception
        perception = Perception(
            type=PerceptionType.TEXT,
            source="file_monitor",
            data={
                "file_path": file_path,
                "content": content,
                "event": "modified"
            },
            timestamp=time.time(),
            priority=0
        )

        await self.perception_manager.receive(perception)
```

---

## 3. 决策层：感知决策系统

```python
@dataclass
class ProcessedPerception:
    """处理后的感知"""
    original: 'Perception'           # 原始感知
    type: PerceptionType             # 感知类型
    intent: 'Intent'                 # 意图
    priority: int                    # 优先级（0-5）
    merged_with: List['Perception']   # 合并的相关感知


@dataclass
class Intent:
    """感知意图"""
    category: str        # 意图类别（query/command/notification/urgent）
    action: str          # 具体动作
    confidence: float     # 置信度

    @classmethod
    def parse(cls, data: dict) -> 'Intent':
        return cls(**data)


class PerceptionDecisionSystem:
    """感知决策系统 - 类似工具决策"""

    def __init__(self, llm: 'LLMAdapter', perception_history: 'PerceptionHistory'):
        self.llm = llm
        self.perception_history = perception_history

    async def process(self, raw_perception: 'Perception') -> Optional[ProcessedPerception]:
        """处理感知输入（5步流程）"""

        # 1. 去重检查
        if await self.is_duplicate(raw_perception):
            logger.debug(f"感知输入重复，忽略: {raw_perception.id}")
            return None

        # 2. 感知分类（已经由Sensor定义，但可细化）
        perception_type = raw_perception.type

        # 3. 意图识别
        intent = await self.recognize_intent(raw_perception)

        # 4. 优先级判断
        priority = await self.assess_priority(raw_perception, intent)

        # 5. 合并相关感知
        merged = await self.merge_related(raw_perception)

        return ProcessedPerception(
            original=raw_perception,
            type=perception_type,
            intent=intent,
            priority=priority,
            merged_with=merged
        )

    async def recognize_intent(self, perception: 'Perception') -> Intent:
        """识别感知意图"""

        prompt = f"""
        感知输入类型：{perception.type}
        感知数据：{perception.data}

        请识别感知意图：
        1. 主要意图类别（query/command/notification/urgent）
        2. 具体动作（如：搜索信息、发送消息、查看状态）
        3. 置信度（0-1）

        格式：JSON
        {{
            "category": "query",
            "action": "搜索最新AI新闻",
            "confidence": 0.95
        }}
        """

        try:
            intent_data = await self.llm.generate(prompt)
            return Intent.parse(json.loads(intent_data))
        except Exception as e:
            logger.error(f"意图识别失败: {e}")
            # 返回默认意图
            return Intent(
                category="unknown",
                action="未知",
                confidence=0.5
            )

    async def assess_priority(
        self,
        perception: 'Perception',
        intent: Intent
    ) -> int:
        """评估优先级（0-5）"""

        # 感知器已提供基础优先级
        base_priority = perception.priority

        # 根据意图调整
        intent_multiplier = {
            "urgent": 2.0,
            "command": 1.5,
            "query": 1.0,
            "notification": 0.8
        }

        adjusted = base_priority * intent_multiplier.get(
            intent.category, 1.0
        )

        # 置信度影响
        adjusted *= (0.5 + 0.5 * intent.confidence)

        return min(int(adjusted), 5)

    async def merge_related(self, perception: 'Perception') -> List['Perception']:
        """合并相关感知（时间窗口内）"""

        # 从感知历史中查找相关感知
        time_window = self.config.get("merge_time_window", 5)  # 5秒内
        cutoff = time.time() - time_window

        related = await self.perception_history.find_related(
            perception,
            since=cutoff
        )

        return related

    async def is_duplicate(self, perception: 'Perception') -> bool:
        """去重检查"""

        # 基于内容hash去重
        import hashlib
        import json

        content_hash = hashlib.md5(
            json.dumps(perception.data, sort_keys=True).encode()
        ).hexdigest()

        # 检查最近是否处理过
        recently_seen = await self.perception_history.exists(content_hash)

        return recently_seen
```

---

## 4. 感知管理器

```python
class PerceptionManager:
    """感知管理器"""

    def __init__(self, config: dict):
        self.config = config
        self.sensors: Dict[str, Sensor] = {}
        self.decision_system = PerceptionDecisionSystem(llm, history)
        self.perception_queue = asyncio.PriorityityQueue()
        self.perception_history = PerceptionHistory()

    async def register_sensor(self, sensor: Sensor):
        """注册感知器"""
        self.sensors[sensor.name] = sensor

        # 按需启动（由插件决定）
        if sensor.enabled:
            await sensor.start()
            logger.info(f"感知器已启动: {sensor.name}")
        else:
            logger.info(f"感知器已注册但未启用: {sensor.name}")

    async def unregister_sensor(self, sensor_name: str):
        """注销感知器"""
        sensor = self.sensors.get(sensor_name)
        if sensor and sensor.enabled:
            await sensor.stop()
            del self.sensors[sensor_name]
            logger.info(f"感知器已停止: {sensor_name}")

    async def receive(self, raw_perception: 'Perception'):
        """接收感知输入（由感知器调用）"""

        # 通过决策系统处理
        processed = await self.decision_system.process(raw_perception)

        if processed is None:
            return  # 重复或被过滤

        # 加入优先级队列
        await self.perception_queue.put((
            -processed.priority,  # 负数让高优先级先出队
            processed.original.timestamp,
            processed
        ))

        # 存入历史
        await self.perception_history.add(processed)

    async def perceive(self) -> List[ProcessedPerception]:
        """获取感知输入（供Agent调用）"""

        # 1. 处理轮询模式感知器
        for sensor in self.sensors.values():
            if sensor.trigger_mode in [TriggerMode.POLL, TriggerMode.HYBRID]:
                if sensor.enabled:
                    try:
                        perception = await sensor.sense()
                        if perception:
                            await self.receive(perception)
                    except Exception as e:
                        logger.error(f"感知器 {sensor.name} 异常: {e}")

        # 2. 从队列获取所有待处理感知
        perceptions = []

        while not self.perception_queue.empty():
            priority, timestamp, perception = await self.perception_queue.get()
            perceptions.append(perception)

        return perceptions

    def list_sensors(self) -> List[Sensor]:
        """列出所有感知器"""
        return list(self.sensors.values())

    def get_sensor_stats(self) -> Dict[str, Dict]:
        """获取感知器统计"""
        stats = {}
        for name, sensor in self.sensors.items():
            stats[name] = {
                "enabled": sensor.enabled,
                "type": sensor.perception_type.value,
                "trigger_mode": sensor.trigger_mode.value
            }
        return stats
```

---

## 5. 感知数据结构

```python
from dataclasses import dataclass, field
from typing import Any, Dict
import time
import uuid

@dataclass
class Perception:
    """感知输入"""
    type: PerceptionType           # 感知类型
    source: str                    # 感知源标识
    data: Any                      # 感知数据
    timestamp: float               # 时间戳
    priority: int = 0              # 优先级（0-5）
    metadata: Dict = field(default_factory=dict)  # 额外元数据

    @property
    def id(self) -> str:
        """唯一ID"""
        if 'id' not in self.metadata:
            self.metadata['id'] = str(uuid.uuid4())
        return self.metadata['id']

    def to_dict(self) -> Dict:
        """序列化为字典"""
        return {
            "id": self.id,
            "type": self.type.value if isinstance(self.type, PerceptionType) else self.type,
            "source": self.source,
            "data": self.data,
            "timestamp": self.timestamp,
            "priority": self.priority,
            "metadata": self.metadata
        }
```

---

## 6. 感知历史（去重）

```python
class PerceptionHistory:
    """感知历史 - 用于去重和关联"""

    def __init__(self, max_size: int = 10000):
        self.max_size = max_size
        self.perceptions: Dict[str, ProcessedPerception] = {}
        self.content_hash_index: Dict[str, str] = {}  # hash -> perception_id
        self.time_index: List[str] = []  # 按时间排序的ID列表

    async def add(self, perception: ProcessedPerception):
        """添加感知记录"""

        # 限制大小
        if len(self.time_index) >= self.max_size:
            oldest_id = self.time_index.pop(0)
            oldest = self.perceptions.pop(oldest_id, None)
            if oldest:
                # 清理内容hash索引
                content_hash = self._compute_content_hash(perception.original)
                self.content_hash_index.pop(content_hash, None)

        # 存储
        self.perceptions[perception.original.id] = perception
        self.time_index.append(perception.original.id)

        # 建立内容hash索引
        content_hash = self._compute_content_hash(perception.original)
        self.content_hash_index[content_hash] = perception.original.id

    async def exists(self, content_hash: str) -> bool:
        """检查内容是否已存在"""
        # 检查最近5分钟内的hash
        cutoff = time.time() - 300

        if content_hash in self.content_hash_index:
            perception_id = self.content_hash_index[content_hash]
            perception = self.perceptions.get(perception_id)

            if perception and perception.original.timestamp > cutoff:
                return True

        return False

    async def find_related(
        self,
        perception: Perception,
        since: float
    ) -> List[Perception]:
        """查找相关感知"""

        related = []

        for pid in self.time_index:
            p = self.perceptions.get(pid)
            if not p:
                continue

            if p.original.timestamp < since:
                break  # 时间索引是有序的

            # 简单的相关性判断
            if self._is_related(p.original, perception):
                related.append(p.original)

        return related[:5]  # 最多返回5个

    def _compute_content_hash(self, perception: Perception) -> str:
        """计算内容hash"""
        import hashlib
        import json

        content_str = json.dumps(perception.data, sort_keys=True)
        return hashlib.md5(content_str.encode()).hexdigest()

    def _is_related(self, p1: Perception, p2: Perception) -> bool:
        """判断两个感知是否相关"""
        # 相同类型
        if p1.type != p2.type:
            return False

        # 相同来源
        if p1.source == p2.source:
            return True

        # 时间窗口内
        if abs(p1.timestamp - p2.timestamp) < 1.0:
            return True

        return False
```

---

## 7. 目录结构

```
magi/backend/src/magi/awareness/
├── __init__.py
├── perception.py              # 感知数据结构
├── base.py                    # 感知器基类（框架定义）
├── manager.py                 # 感知管理器
├── decision.py                 # 感知决策系统
├── history.py                  # 感知历史（去重）
│
├── builtin/                   # 内置感知器（插件实现）
│   ├── audio/
│   │   ├── __init__.py
│   │   ├── microphone.py      # 麦克风
│   │   └── audio_file.py      # 音频文件
│   │
│   ├── video/
│   │   ├── __init__.py
│   │   ├── camera.py          # 摄像头
│   │   └── video_stream.py    # 视频流
│   │
│   ├── text/
│   │   ├── __init__.py
│   │   ├── user_message.py    # 用户消息
│   │   ├── email.py           # 邮件
│   │   └── file_monitor.py    # 文件变化
│   │
│   └── sensor_data/
│       ├── __init__.py
│       └── sensor.py          # 传感器数据
│
└── custom/                    # 自定义感知器
    └── README.md               # 开发指南
```

---

## 8. 配置示例

```yaml
# config/perception.yaml
sensors:
  # 麦克风感知器
  microphone:
    enabled: false              # 是否启用
    sample_rate: 16000
    channels: 1
    transcribe: true             # 是否转文字

  # 摄像头感知器
  camera:
    enabled: false
    device_id: 0
    fps: 15
    describe: true               # 是否描述画面

  # 邮件感知器
  email:
    enabled: true
    imap_server: "imap.gmail.com"
    username: "${EMAIL_ADDRESS}"
    password: "${EMAIL_PASSWORD}"
    important_senders:
      - "boss@company.com"
      - "important@client.com"
    check_interval: 60           # 检查间隔（秒）

  # 文件监听感知器
  file_monitor:
    enabled: true
    watch_paths:
      - "/path/to/watch"
      - "/path/to/documents"

# 感知决策配置
decision:
  merge_time_window: 5          # 合并时间窗口（秒）
  priority_threshold: 3         # 高优先级阈值
```

---

## 9. 核心特性总结

### 框架层
- ✅ 定义感知大类（Audio/Video/Text/Image/Sensor/Event）
- ✅ 提供统一抽象接口
- ✅ 支持多种触发模式
- ✅ 按需启动机制

### 插件层
- ✅ 具体硬件/API封装
- ✅ 自主决定触发模式
- ✅ 自主决定数据处理方式
- ✅ 自主决定部署位置

### 决策层
- ✅ 感知去重
- ✅ 意图识别
- ✅ 优先级判断
- ✅ 感知合并

### 技术栈
- **核心**: Python 3.10+
- **音频**: pyaudio（可选）
- **视频**: opencv-python（可选）
- **监听**: watchdog（可选）
- **邮件**: imaplib（内置）
- **决策**: LLM（OpenAI/Anthropic等）
