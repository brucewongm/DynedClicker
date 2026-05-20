"""
状态机：Master 控制 Slave，对齐 project_introdection.txt 流程
"""
import threading
import time
from enum import Enum
from typing import Callable, Optional

from core.protocol import MessageType


class MasterState(Enum):
    IDLE = "IDLE"
    WAIT_SLAVE = "WAIT_SLAVE"
    WAIT_SILENCE = "WAIT_SILENCE"
    WAIT_PLAY_DONE = "WAIT_PLAY_DONE"
    WAIT_DY_AUDIO_END = "WAIT_DY_AUDIO_END"
    CHECK_QUIZ = "CHECK_QUIZ"
    PAUSED_FOCUS = "PAUSED_FOCUS"
    PAUSED_TASK = "PAUSED_TASK"
    ERROR = "ERROR"
    STOPPED = "STOPPED"


class MasterCheckpoint(Enum):
    """失焦恢复时需重新执行的 Dy 按钮节点"""
    WAIT_SILENCE = "wait_silence"
    RECORD = "record"
    PLAY = "play"
    CONTINUE = "continue"
    QUIZ = "quiz"


class SlaveState(Enum):
    IDLE = "IDLE"
    WAIT_START = "WAIT_START"
    RECORDING = "RECORDING"
    WAIT_PROCESS = "WAIT_PROCESS"
    PROCESSING = "PROCESSING"
    PLAYING = "PLAYING"
    ERROR = "ERROR"
    STOPPED = "STOPPED"


class MasterStateMachine:
    """
    Master(A) 流程:
    START+ACK → 等 SILENCE_END → 点 record → PROCESS_RECORD
    → 等 PLAY_DONE → 点 play → 监测 Dy 播放结束 → 点 continue
    → 问答识别 → SYNC → 下一轮
    """

    def __init__(
        self,
        config,
        network,
        clicker,
        quiz_detector,
        master_monitor,
        logger,
        stop_event,
        pause_event=None,
        owns_network: bool = False,
    ):
        self.config = config
        self.network = network
        self.clicker = clicker
        self.quiz = quiz_detector
        self.master_monitor = master_monitor
        self.logger = logger
        self.stop_event = stop_event
        self.pause_event = pause_event or threading.Event()
        self.owns_network = owns_network

        self.current_state = MasterState.IDLE
        self._lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None
        self._ack_timeout = config.get("network.ack_timeout", 1.0)
        self._msg_timeout = config.get("network.message_timeout", 120.0)

        self.network.register_callback(MessageType.SILENCE_END, self._on_silence_end)
        self.network.register_callback(MessageType.PLAY_DONE, self._on_play_done)
        self.network.register_callback(MessageType.ACK, lambda d: None)
        self.network.register_callback(MessageType.RESET, self._on_reset)

        self._silence_event = threading.Event()
        self._play_done_event = threading.Event()
        self._dy_audio_end_event = threading.Event()

        self._focus_ready = threading.Event()
        self._focus_ready.set()
        self._pending_focus_resume = threading.Event()
        self._checkpoint = MasterCheckpoint.WAIT_SILENCE
        self._pause_on_focus_loss = config.get("focus.pause_on_focus_loss", True)

    def _set_state(self, state: MasterState):
        with self._lock:
            if self.current_state != state:
                self.logger.info("Master: %s → %s", self.current_state.value, state.value)
                self.current_state = state

    def start(self):
        """兼容旧接口：启动网络并执行任务"""
        if not self.network.start_persistent_server(self.stop_event):
            self._set_state(MasterState.ERROR)
            return False
        return self.start_task()

    def start_task(self):
        if self._worker and self._worker.is_alive():
            return True
        self._worker = threading.Thread(target=self._run_loop, daemon=True)
        self._worker.start()
        return True

    def _ensure_connected(self) -> bool:
        if self.network.connected:
            return True
        self._set_state(MasterState.WAIT_SLAVE)
        self.logger.info("等待 Slave 连接...")
        return self.network.wait_until_connected(self.stop_event)

    def _sync_node(self, phase: str, **extra):
        payload = {"phase": phase, "node": phase}
        payload.update(extra)
        if self.network.send_message(MessageType.SYNC, payload):
            self.logger.info("节点同步 → Slave: %s", phase)

    def _on_silence_end(self, data):
        self._silence_event.set()

    def _on_play_done(self, data):
        self._play_done_event.set()

    def _on_reset(self, data):
        self._silence_event.set()
        self._play_done_event.set()
        self._dy_audio_end_event.set()

    def _checkpoint_from_state(self) -> MasterCheckpoint:
        state = self.current_state
        if state == MasterState.WAIT_SILENCE:
            return MasterCheckpoint.WAIT_SILENCE
        if state == MasterState.WAIT_PLAY_DONE:
            return MasterCheckpoint.RECORD
        if state in (MasterState.WAIT_DY_AUDIO_END,):
            return MasterCheckpoint.PLAY
        if state == MasterState.CHECK_QUIZ:
            return MasterCheckpoint.QUIZ
        return MasterCheckpoint.CONTINUE

    def on_focus_lost(self):
        if not self._pause_on_focus_loss:
            self.stop_event.set()
            return
        self._checkpoint = self._checkpoint_from_state()
        self._focus_ready.clear()
        self._set_state(MasterState.PAUSED_FOCUS)
        self.master_monitor.stop()
        self.logger.warning(
            "已记录节点 [%s]，等待 Dy 恢复焦点后继续",
            self._checkpoint.value,
        )

    def on_focus_regained(self):
        self._focus_ready.set()
        self._pending_focus_resume.set()
        self.logger.info("将从节点 [%s] 继续（先 repeat 再执行对应按钮）", self._checkpoint.value)

    def _block_until_focused(self) -> bool:
        while not self._focus_ready.is_set() and not self.stop_event.is_set():
            time.sleep(0.1)
        return not self.stop_event.is_set()

    def _block_until_not_paused(self) -> bool:
        while self.pause_event.is_set() and not self.stop_event.is_set():
            time.sleep(0.1)
        return not self.stop_event.is_set()

    def _block_until_ready(self) -> bool:
        while not self.stop_event.is_set():
            if self.pause_event.is_set():
                time.sleep(0.1)
                continue
            if not self._focus_ready.is_set():
                time.sleep(0.1)
                continue
            return True
        return False

    def pause_task(self):
        if self.pause_event.is_set():
            return
        self.pause_event.set()
        self.master_monitor.stop()
        self._set_state(MasterState.PAUSED_TASK)
        self.network.send_message(MessageType.PAUSE, {})
        self.logger.info("任务已暂停：停止点击、Slave 录音与播放")

    def resume_task(self):
        if not self.pause_event.is_set():
            return
        self.pause_event.clear()
        self.network.send_message(MessageType.RESUME, {})
        self.logger.info("任务已继续")

    def _consume_focus_resume(self) -> bool:
        if self._pending_focus_resume.is_set():
            self._pending_focus_resume.clear()
            return True
        return False

    def _wait_event(self, event: threading.Event, timeout: float, label: str) -> bool:
        if self.stop_event.is_set():
            return False
        deadline = time.time() + timeout
        while time.time() < deadline and not self.stop_event.is_set():
            if not self._block_until_ready():
                return False
            if self._pending_focus_resume.is_set():
                return False
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            if event.wait(timeout=min(0.3, remaining)):
                event.clear()
                return True
        self.logger.error("等待 %s 超时 (%.1fs)", label, timeout)
        self._set_state(MasterState.ERROR)
        return False

    def _click_repeat_then(self, region: str) -> bool:
        if not self._click("repeat"):
            return False
        time.sleep(self.config.get("focus.resume_delay", 0.4))
        return self._click(region)

    def _resume_after_focus(self) -> bool:
        """失焦恢复后按检查点重新执行 repeat + 对应按钮"""
        cp = self._checkpoint
        self.logger.info("失焦恢复：执行 repeat → %s", cp.value)
        if cp == MasterCheckpoint.WAIT_SILENCE:
            return True
        if cp == MasterCheckpoint.RECORD:
            if not self._click_repeat_then("record"):
                return False
            return self.network.send_message(MessageType.PROCESS_RECORD)
        if cp == MasterCheckpoint.PLAY:
            return self._click_repeat_then("play")
        if cp == MasterCheckpoint.CONTINUE:
            return self._click_repeat_then("continue")
        if cp == MasterCheckpoint.QUIZ:
            return self._click_repeat_then("continue")
        return True

    def _click(self, region: str) -> bool:
        if not self._block_until_ready():
            return False
        if self.pause_event.is_set():
            return False
        if not self.clicker.click_region(region, self.config):
            self.logger.error("点击 %s 失败", region)
            self._set_state(MasterState.ERROR)
            return False
        return True

    def _phase_wait_silence(self) -> bool:
        self._sync_node("wait_silence")
        while not self.stop_event.is_set():
            if not self._ensure_connected():
                return False
            if not self._block_until_ready():
                return False
            if self._consume_focus_resume():
                continue
            if self._wait_event(self._silence_event, self._msg_timeout, "SILENCE_END"):
                return True
            if self._pending_focus_resume.is_set() or self._consume_focus_resume():
                continue
            return self.current_state != MasterState.ERROR
        return False

    def _phase_record_and_wait_play(self) -> bool:
        self._sync_node("record")
        while not self.stop_event.is_set():
            if not self._ensure_connected():
                return False
            if not self._block_until_ready():
                return False
            if self._consume_focus_resume():
                if not self._resume_after_focus():
                    return False
            if not self._click("record"):
                return False
            if not self.network.send_message(MessageType.PROCESS_RECORD):
                return False
            self._set_state(MasterState.WAIT_PLAY_DONE)
            self._checkpoint = MasterCheckpoint.RECORD
            if self._wait_event(self._play_done_event, self._msg_timeout, "PLAY_DONE"):
                return True
            if self._pending_focus_resume.is_set() or self._consume_focus_resume():
                continue
            return self.current_state != MasterState.ERROR
        return False

    def _phase_play_and_wait_audio(self) -> bool:
        self._sync_node("play")
        while not self.stop_event.is_set():
            if not self._ensure_connected():
                return False
            if not self._block_until_ready():
                return False
            if self._consume_focus_resume():
                if not self._resume_after_focus():
                    return False
            if not self._click("play"):
                return False
            self._set_state(MasterState.WAIT_DY_AUDIO_END)
            self._checkpoint = MasterCheckpoint.PLAY
            self.master_monitor.reset_detector()
            try:
                self.master_monitor.start(lambda: self._dy_audio_end_event.set())
                if self._wait_event(
                    self._dy_audio_end_event,
                    self._msg_timeout,
                    "Dy 音频结束",
                ):
                    return True
                if self._pending_focus_resume.is_set() or self._consume_focus_resume():
                    continue
                return self.current_state != MasterState.ERROR
            except Exception as e:
                self.logger.warning(
                    "Master 音频监测不可用 (%s)，%ss 后继续",
                    e,
                    self.config.get("audio.silence_duration", 1.0) + 1,
                )
                time.sleep(self.config.get("audio.silence_duration", 1.0) + 1)
                return True
            finally:
                self.master_monitor.stop()
        return False

    def _phase_continue(self) -> bool:
        self._checkpoint = MasterCheckpoint.CONTINUE
        self._sync_node("continue")
        while not self.stop_event.is_set():
            if not self._ensure_connected():
                return False
            if not self._block_until_ready():
                return False
            if self._consume_focus_resume():
                if not self._resume_after_focus():
                    return False
            if self._click("continue"):
                return True
            if self._pending_focus_resume.is_set() or self._consume_focus_resume():
                continue
            return self.current_state != MasterState.ERROR
        return False

    def _phase_quiz(self) -> bool:
        self._set_state(MasterState.CHECK_QUIZ)
        self._checkpoint = MasterCheckpoint.QUIZ
        self._sync_node("quiz")
        while not self.stop_event.is_set():
            if not self._ensure_connected():
                return False
            if not self._block_until_ready():
                return False
            if self._consume_focus_resume():
                if not self._resume_after_focus():
                    return False
            point = self.quiz.detect_click_point()
            if point:
                self.clicker.click_screen(point[0], point[1])
                time.sleep(self.config.get("quiz.scan_interval", 0.8))
                self.network.send_message(MessageType.SYNC, {"phase": "quiz_done"})
            return True
        return False

    def _send_start_with_retry(self) -> bool:
        while not self.stop_event.is_set():
            if not self._ensure_connected():
                return False
            self._sync_node("round_start")
            if not self.network.send_message(MessageType.START):
                time.sleep(self.network.reconnect_interval)
                continue
            ack = self.network.wait_for_message(
                MessageType.ACK, self._ack_timeout, self.stop_event
            )
            if ack is not None:
                return True
            self.logger.warning("未收到 ACK，将重试 START")
            time.sleep(0.5)
        return False

    def _run_loop(self):
        try:
            while not self.stop_event.is_set():
                try:
                    self._silence_event.clear()
                    self._play_done_event.clear()
                    self._dy_audio_end_event.clear()

                    if not self._send_start_with_retry():
                        break

                    self._set_state(MasterState.WAIT_SILENCE)
                    self._checkpoint = MasterCheckpoint.WAIT_SILENCE
                    if not self._phase_wait_silence():
                        if self.stop_event.is_set():
                            break
                        time.sleep(1.0)
                        continue
                    if not self._phase_record_and_wait_play():
                        if self.stop_event.is_set():
                            break
                        time.sleep(1.0)
                        continue
                    if not self._phase_play_and_wait_audio():
                        if self.stop_event.is_set():
                            break
                        time.sleep(1.0)
                        continue
                    if not self._phase_continue():
                        if self.stop_event.is_set():
                            break
                        time.sleep(1.0)
                        continue
                    if not self._phase_quiz():
                        if self.stop_event.is_set():
                            break
                        time.sleep(1.0)
                        continue

                    self._sync_node("round_complete")
                    self.network.send_message(MessageType.ROUND_COMPLETE)
                    self.logger.info("本轮完成，开始下一轮（保持连接）")
                except Exception as e:
                    self.logger.exception("Master 单轮异常: %s", e)
                    self._set_state(MasterState.ERROR)
                    time.sleep(2.0)
        finally:
            if self.stop_event.is_set():
                self._set_state(MasterState.STOPPED)

    def stop_task(self):
        self.stop_event.set()
        self.master_monitor.stop()

    def stop(self):
        self.stop_task()
        if self.owns_network:
            self.network.shutdown()


class SlaveStateMachine:
    """
    Slave(B): 收 START → ACK → 录音至静音 → 等 PROCESS_RECORD
    → 变调播放 → PLAY_DONE → 等 ROUND_COMPLETE/START
    """

    def __init__(
        self,
        config,
        network,
        recorder,
        detector,
        processor,
        player,
        logger,
        stop_event,
        pause_event=None,
        owns_network: bool = False,
    ):
        self.config = config
        self.network = network
        self.recorder = recorder
        self.detector = detector
        self.processor = processor
        self.player = player
        self.logger = logger
        self.stop_event = stop_event
        self.pause_event = pause_event or threading.Event()
        self.owns_network = owns_network
        self._task_enabled = False

        self.current_state = SlaveState.IDLE
        self._lock = threading.Lock()
        self._recorded = None
        self._finishing = threading.Lock()

        self.network.register_callback(MessageType.START, self._on_start)
        self.network.register_callback(MessageType.PROCESS_RECORD, self._on_process_record)
        self.network.register_callback(MessageType.RESET, self._on_reset)
        self.network.register_callback(MessageType.SYNC, self._on_sync)
        self.network.register_callback(MessageType.ROUND_COMPLETE, self._on_round_complete)
        self.network.register_callback(MessageType.PAUSE, self._on_pause)
        self.network.register_callback(MessageType.RESUME, self._on_resume)
        self._synced_node = "idle"

    def _set_state(self, state: SlaveState):
        with self._lock:
            if self.current_state != state:
                self.logger.info("Slave: %s → %s", self.current_state.value, state.value)
                self.current_state = state

    def start(self):
        if not self.network.start_persistent_client(self.stop_event):
            self.logger.error("Slave 网络线程启动失败")
            return False
        return self.start_task()

    def start_task(self):
        self._task_enabled = True
        self._set_state(SlaveState.WAIT_START)
        self.logger.info("Slave 任务已就绪，等待 Master 指令")
        return True

    def _on_sync(self, data):
        node = data.get("node") or data.get("phase") or "unknown"
        self._synced_node = node
        self.logger.info("节点同步 ← Master: %s (本地状态 %s)", node, self.current_state.value)

    def _on_round_complete(self, data):
        self.logger.info("本轮结束，等待下一轮 START (保持连接)")
        self._synced_node = "round_complete"
        if self.current_state == SlaveState.PLAYING:
            return
        self._set_state(SlaveState.WAIT_START)

    def _abort_slave_ops(self):
        try:
            self.recorder.stop_recording()
        except Exception:
            pass
        self.player.stop_playback()
        self._set_state(SlaveState.WAIT_START)

    def _on_pause(self, data):
        self.pause_event.set()
        self._abort_slave_ops()
        self.logger.info("Slave 已暂停：录音与播放已停止")

    def _on_resume(self, data):
        self.pause_event.clear()
        self.logger.info("Slave 已继续，等待 Master 指令")

    def pause_task(self):
        self._on_pause({})

    def resume_task(self):
        self._on_resume({})

    def _on_start(self, data):
        if not self._task_enabled or self.stop_event.is_set() or self.pause_event.is_set():
            return
        if not self.network.connected:
            self.logger.warning("收到 START 但未连接，忽略")
            return
        self.network.send_message(MessageType.ACK)
        self._synced_node = "recording"
        self._begin_recording()

    def _begin_recording(self):
        self._set_state(SlaveState.RECORDING)
        self.detector.reset()
        self.recorder.clear_session_buffer()
        self.logger.info("开始录音，等待 1 秒以上停顿...")

        def on_chunk(chunk):
            if self.pause_event.is_set() or self.current_state != SlaveState.RECORDING:
                return
            if self.detector.process_chunk(chunk):
                threading.Thread(target=self._finish_recording, daemon=True).start()

        self.recorder.start_recording(callback=on_chunk)

    def _finish_recording(self):
        if not self._finishing.acquire(blocking=False):
            return
        try:
            if self.current_state != SlaveState.RECORDING:
                return
            self._recorded = self.recorder.stop_recording()
        finally:
            self._finishing.release()
        self._set_state(SlaveState.WAIT_PROCESS)
        samples = len(self._recorded) if self._recorded is not None else 0
        self.logger.info("录音结束，样本数 %s", samples)
        self._synced_node = "silence_end"
        self.network.send_message(MessageType.SILENCE_END, {"samples": samples})

    def _on_process_record(self, data):
        if self.current_state not in (SlaveState.WAIT_PROCESS, SlaveState.RECORDING):
            self.logger.warning("忽略 PROCESS_RECORD，当前状态 %s", self.current_state.value)
            return
        if self.current_state == SlaveState.RECORDING:
            self._finish_recording()
        threading.Thread(target=self._process_and_play, daemon=True).start()

    def _process_and_play(self):
        if self.pause_event.is_set():
            return
        self._synced_node = "processing"
        self._set_state(SlaveState.PROCESSING)
        audio = self._recorded
        if audio is None or len(audio) == 0:
            self.logger.error("无录音数据")
            self._set_state(SlaveState.ERROR)
            return

        processed = self.processor.quick_process(audio)
        self._set_state(SlaveState.PLAYING)

        def on_done():
            self.logger.info("变调播放完成")
            self._synced_node = "play_done"
            self.network.send_message(MessageType.PLAY_DONE)
            self._set_state(SlaveState.WAIT_START)

        self.player.play_audio(processed, on_finish=on_done)

    def _on_reset(self, data):
        self.detector.reset()
        try:
            self.recorder.stop_recording()
        except Exception:
            pass
        self._set_state(SlaveState.WAIT_START)

    def stop_task(self):
        self._task_enabled = False
        self.stop_event.set()
        self._abort_slave_ops()

    def stop(self):
        self.stop_task()
        if self.owns_network:
            self.network.shutdown()
