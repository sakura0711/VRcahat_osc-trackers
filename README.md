# VRChat Track：單手機姿勢追蹤

目標：一支 Android 手機辨識人體姿勢，經私人 Wi-Fi 傳到 Windows，再透過 VRChat 原生 OSC Trackers 與 FBT／IK 驅動**未修改的購買 Humanoid Avatar**，讓私人房間的其他玩家看見。現階段使用 AnyaDance 提供虛擬 HMD 與雙控制器；不修改 VRChat client 或 Avatar。

## 文件導覽

- **[目前狀態](docs/STATUS.md)** — 各項目「已證實 / 待驗證」的單一來源。
- **[OSC Tracker 計畫](docs/PLAN.md)** — 主線、Phase 定義與完成條件。
- **操作指南**
  - [Windows 接收端](windows/README.md)、[Android App](android/README.md)
  - [Phase 0 探針](windows/TRACKER_PHASE0.md)、[ZIP 回放](windows/TRACKER_REPLAY_GUIDE.md)、[影像對照](windows/IMAGE_PAIR_GUIDE.md)
  - [即時 tracker 安全與平滑計畫](windows/LIVE_TRACKER_SAFETY_PLAN.md)
- **參考**
  - [AnyaDance 操作](reference/anyadance-controls.md)、[SteamVR -202 與環境](reference/steamvr-202.md)
- **紀錄**（有日期的調查與測試）：[docs/logs/](docs/logs/)
- **交接 prompt**：[NEXT_SESSION_PROMPT.md](NEXT_SESSION_PROMPT.md)

文件規範（放什麼、不放什麼）見 [docs/README.md](docs/README.md)。

## 啟動（即時 tracker 輸出）

在 `windows` 目錄執行（會送 OSC）。`<PC_IP>` 換成電腦熱點 IPv4、`<PHONE_IP>` 換成手機 IP；角色 ID、髖高、鏡像／前向等須依**當次 FBT 校正**設定，ID 3／4 可能對調，送 OSC 前先確認映射。

~~~powershell
python -B -u pose_receiver.py --bind <PC_IP> --port 8765 --allow-sender <PHONE_IP> --output trackers --tracker-hip-id 1 --tracker-left-foot-id 3 --tracker-right-foot-id 4 --tracker-hip-height 0.90 --tracker-mirror yes --tracker-swap-left-right yes --tracker-forward-sign -1 --tracker-yaw 0 --duration 300 --report-interval 5 --color auto
~~~

## 測試

Windows 自動測試在 `windows` 目錄執行：

~~~powershell
python -B -m unittest discover -v
~~~
