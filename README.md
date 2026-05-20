# Dy 音频自动化工具 (audioauto)

跨电脑协同工具：Master(A) 控制 Dy 界面与流程，Slave(B) 通过麦克风录音、变调播放，实现人机对话自动化。

## 功能概览

| 功能 | 说明 |
|------|------|
| A/B 双模式 | Master / Slave，局域网 TCP 通信 |
| Master 控制 | 发 START、等 ACK(1s)、驱动 record/play/continue |
| Slave 录音 | 监听至 1 秒以上静音后停止，变调播放 |
| 后台点击 | PostMessage，不抢 Dy 焦点 |
| 焦点监测 | Master 失焦暂停并恢复；可配置为失焦停止 |
| 问答识别 | 截图 + OCR（需安装 Tesseract） |
| 日志 | `logs/automation_master.log` / `automation_slave.log` |
| GUI | `python main.py`（默认图形界面） |

## 安装

```bat
setup.bat
```

或手动：

```bat
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

问答 OCR（可选）：

1. 安装 [Tesseract-OCR](https://github.com/tesseract-ocr/tesseract)
2. 确保 `tesseract` 在系统 PATH 中

## 使用

### 1. 区域矫正（两台电脑各执行一次）

在 GUI 中点击「区域矫正」，或开发调试时使用项目内校准流程。

记录：continue、repeat、record、play 四个按钮及 Dy 窗口。

### 2. 配置网络

编辑 `config/config.yaml`：

- Slave 电脑：`network.master_ip` 设为 Master 的局域网 IP
- Master 电脑：`network.bind_ip` 一般为 `0.0.0.0`

### 3. 启动顺序

Master / Slave **任意先后**均可；TCP 连接断开后会自动重连，整轮流程中**不主动断开**（仅点「停止」时关闭）。

```bat
# 两台电脑均运行（打开图形界面后选择模式并点「启动」）
python main.py
```

无黑窗口启动（Windows）：`pythonw main.py`

## 交互流程

```
Master                         Slave
  | START ---------------------->|
  |<--------------------------- ACK (1s 内)
  |                              | 录音至静音
  |<-------------------- SILENCE_END
  | 点击 record                  |
  | PROCESS_RECORD ------------->|
  |                              | 变调 + 播放
  |<----------------------- PLAY_DONE
  | 点击 play                    |
  | (监测 Dy 音频结束)            |
  | 点击 continue                |
  | (问答 OCR 点击)              |
  | ROUND_COMPLETE ------------->|
  | 下一轮 START ...（同一连接）  |
```

各阶段 Master 会发送 `SYNC`（含 `node` 字段）与 Slave 同步节点。

## 测试

```bat
pytest tests/test_protocol.py tests/test_config.py -q
```

音频/鼠标相关测试需人工与硬件，见 `tests/test_audio_chain.py`、`tests/test_mouse_background.py`。

## 项目结构

```
audio_automation/
├── main.py              # 入口（默认 GUI）
├── gui/app.py           # 图形界面
├── config/              # YAML 配置
├── core/
│   ├── protocol.py      # 消息帧
│   ├── communication.py # TCP
│   ├── state_machine.py # Master/Slave 状态机
│   ├── logging_setup.py
│   ├── focus_monitor.py
│   ├── audio/           # 录音/播放/监测/处理
│   ├── mouse/           # 窗口与后台点击
│   └── vision/          # 问答 OCR
└── tests/
```

## 常见问题

- **1 秒内无 ACK**：检查防火墙、IP、是否先启动 Slave。
- **点击无效**：重新 calibrate；确认 Dy 窗口标题已写入配置。
- **问答不识别**：安装 Tesseract；或在配置中设 `quiz.enabled: false`。
