# 原生 OSC Tracker MVP 計畫

目前各項「已證實 / 待驗證」狀態見 [docs/STATUS.md](STATUS.md)；詳細實驗數據見 [docs/logs/](logs/)。本頁只保留主線、邊界、OSC 契約、程式模組與 Phase 定義，不重複實驗紀錄。

## 目標與邊界

一支 Android 手機拍攝人體姿勢，在手機上以 MediaPipe 取得 landmarks，經私人 Wi-Fi UDP 傳給 Windows。Windows 將可信姿勢換算為 VRChat 原生 OSC Tracker 的公尺位置與 Euler 旋轉，由 VRChat FBT／IK 驅動未修改的購買 Humanoid Avatar，並在私人房間讓其他玩家看見。

不修改或注入 VRChat client，也不要求修改購買 Avatar。虛擬 HMD 提供頭與雙手，OSC 先送髖與雙腳。單鏡頭的房間深度、遮擋與腳部朝向仍是待解問題。

## 已證實：Phase 0

2026-11-05，在 AnyaDance 自帶 SteamVR trackers 設為 `enable_trackers=false` 的情況下，合成 OSC 髖與雙腳在虛擬 HMD 的 VR 模式完成 FBT 校正、本機腳部動作與私人房間遠端盲測。這證實**合成 OSC tracker 在此 VR 模式能驅動 IK 並遠端同步**，但不證明手機姿勢端到端、純 Desktop FBT 或長時間穩定性。

- 完整日誌映射與時間：[2026-11-05 Phase 0 驗收](logs/2026-11-05-phase0.md)
- 重做步驟：[探針操作](../windows/TRACKER_PHASE0.md)
- SteamVR `-202` 與環境：[reference/steamvr-202.md](../reference/steamvr-202.md)

## OSC 契約

一般 tracker 使用 `/tracking/trackers/{1..8}/position` 與 `/tracking/trackers/{1..8}/rotation`，各帶三個 OSC float。位置為 Unity 左手系公尺；旋轉為 Euler 度。VRChat 不保證 ID 3、4 固定對應左／右腳，因此必須以**當次 FBT 校正映射**設定角色到 ID 的關係。[VRChat 官方 OSC Trackers 文件](https://docs.vrchat.com/docs/osc-trackers)。

## 目前程式模組

- `windows/tracker_output.py`：Vector3 編碼與只送本機的 `TrackerOutput`；呼叫端明填髖／左腳／右腳 ID 和已校正 transform，無效批次不送出。`tracker_probe.py` 共用編碼器。
- `windows/tracker_pose.py`：**離線**手機姿勢轉換基礎。以站姿樣本建右／上／前軸與尺度，輸出髖與雙腳位置及 yaw；校正前、低信心或缺點不產生 transform，失追超過 250 ms 清除校正。合成影格測試涵蓋站姿、抬腳、蹲下、轉身、鏡像、yaw 與失追，**不是手機或 VRChat 實測**。
- `windows/tracker_preview.py`：不送 OSC 的手機 UDP 離線預覽，可選 `--record` 保存 landmarks 與高度診斷。
- `pose_receiver.py --output none|trackers`：預設 `none` 不送 OSC。`trackers` 經 `tracker_bridge.py` 使用離線校正器與 `TrackerOutput`，要求明填角色 ID、髖高、鏡像、左右標籤、前向與 yaw；`T`（失追）預設 250 ms，`H`（短暫保持）獨立預設 0。
- `tracker_replay.py --osc`：已存 ZIP 的原生 tracker 回放，與 receiver 分離。

本機手機即時 OSC 與 Avatar 動作已由使用者確認；公尺精度、腳部 yaw、HMD 對齊與遠端效果的量測結果見 [docs/logs/](logs/)。

## 接下來的階段

| 階段 | 工作與驗收 |
| --- | --- |
| Phase 1：輸出整合 | 已建立 `--output none|trackers`，預設不送 OSC。只有座標校正完成且當次角色 ID 已明填才允許 tracker 輸出；停止、超時及 loopback 自動測試已完成。本機手機即時動作已初驗，遠端與品質驗收待完成。 |
| Phase 2：單手機姿勢 | 將 MediaPipe world landmarks 以身高、地面、相機面向／鏡像和初始 yaw 校正為髖與雙腳的 VRChat 座標；處理低信心、遮擋與失追。先驗證站立、抬腳、蹲下與轉身。 |
| Phase 3：自然度 | 測量腳部抖動與延遲，再選擇濾波及是否增加胸、肘、膝等點。只加入品質足以改善 IK 的 tracker。 |
| Phase 4：實機驗收 | 以單手機在未修改的購買 Avatar 上完成本機與遠端盲測，並記錄 10 分鐘 FPS、封包、姿勢有效率、漂移及延遲。 |

## 實驗與調查紀錄

目前主要未解問題是**高度幅度低估**（抬 20 cm 箱面只估出約 5–7 cm），已定位到來源 3D 幾何，但未分離 2D 定位與三維估計誤差。詳細紀錄都在 [docs/logs/](logs/)：

- [2026-11-06 FBT 收到數值但不動排查](logs/2026-11-06-fbt-diagnostic.md)
- [2026-11-06 高度低估離線調查](logs/2026-11-06-height-investigation.md)
- [2026-11-06 真手機影像調查](logs/2026-11-06-image-pair-review.md)
- [2026-11-06 固定影像模型比較](logs/2026-11-06-offline-model-comparison.md)
- [Windows 測試紀錄（滾動）](logs/windows-tests.md)、[Android 測試](logs/android-tests.md)

## 後續待量化

公尺／角度精度、腳部 yaw／地面偏移、HMD 絕對對齊及失追／停止行為。可沿用 CPU IMAGE 比對設計隔離實驗，不例行重做左右方向或 Phase 0。VIDEO 不能用稀疏照片當成原始串流。獨立腳點真值、相機內參／俯仰與腳部深度仍缺少；後鏡頭與超廣角尚未實作，切換後須獨立驗證。需要更新 App 或真人配合前先語音通知。
