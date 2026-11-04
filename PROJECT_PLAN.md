# VRChat 定點全身傀儡控制：單手機 MVP 計畫書

**狀態：第 4 階段遊戲內診斷通過，第 5 / 5 階段待實測 — 六個 OSC 參數與 WASD 共存已在 VRChat 本機驗證；手機到遊戲完整流程及長時間測試尚未驗證。**  
**更新日期：2026-11-04（Asia/Taipei）**  
**核可狀態：MVP v0.2 已核可；持續依核可範圍實作。**

## 1. MVP 的目的與範圍

本 MVP 只驗證「一支 Android 手機是否能成為 VRChat 定點姿勢傀儡控制的可靠輸入」。玩家仍在 VRChat Desktop 模式用鍵盤 WASD 移動；手機資料只控制 Avatar 局部骨頭旋轉，絕不控制 Avatar Root 的世界位置或世界旋轉。

~~~text
人體動作
  → Android 手機相機
  → CameraX + MediaPipe Pose Landmarker（手機本機辨識）
  → Wi-Fi 區網 UDP（只送 landmark，不送影像）
  → Windows receiver（完整性、抖動、延遲指標）
  → VRChat OSC Avatar Parameters
  → 可編輯的 Avatar 3.0 測試 Avatar（局部骨頭旋轉）
~~~

### 本次包含

1. Android 原生環境部署與實機安裝。
2. Pose Landmarker 擷取、可信度篩選、校正與平滑。
3. 手機到 Windows 的 Wi-Fi LAN 傳輸與 ACK 量測。
4. Windows 到 VRChat 的 OSC 參數測試。
5. 資料完整度、延遲指標與全流程可重做性測試。

### 本次不包含

- 不做第二支手機、雙視角三角定位或鏡頭融合。
- 不承諾完整 18 軸全身控制；先用 6 個局部姿勢參數驗證全鏈路。
- 不傳輸手機影像到 PC；辨識全部在手機端完成。
- 不宣稱這是 VRChat 原生 FBT，也不使用虛擬 HMD。
- 不以未驗證的遠端平滑度作為既成事實。

## 2. MVP 完成定義

1. Android App 在一支實體手機能從相機即時得到 Pose Landmarker 的 33 點資料。
2. Windows 持續接收有序號的封包，並輸出遺失率、到達間隔、jitter、解析失敗與 application RTT。
3. VRChat 在本機正確接收 6 個 OSC Avatar Parameters，驅動測試 Avatar 的局部姿勢，且 WASD locomotion 正常。
4. 從安裝、部署、連線、receiver 到 VRChat 測試都有可重跑的步驟與測試紀錄。
5. 若有另一名測試者，再於私人房間檢驗遠端可見性；沒有測試者時結果必須寫明「遠端同步尚未驗證」。

## 3. 已確認的環境與硬體

### Windows 主機

| 類別 | 配置 |
| --- | --- |
| 作業系統 | Windows 10 家用版，64 位元，版本 10.0.19045（Build 19045） |
| CPU | Intel Core i7-9750H，6 核心／12 執行緒，2.60 GHz |
| GPU | NVIDIA GeForce RTX 2060；Windows 回報 4.0 GiB Adapter RAM |
| 系統記憶體 | 24.0 GiB |
| 專案磁碟 | E:，可用空間約 461.9 GiB |
| Python | 3.12.6 |
| Node.js / npm | 24.22.0 / 11.19.1 |
| Git | 2.46.2.windows.1 |
| VS Code | 1.144.1 |

### Android 開發環境現況

| 項目 | 實際狀態 | MVP 判斷 |
| --- | --- | --- |
| Android Studio | 2025.1，E:/AndroidStudio | 已確認可用 |
| Android SDK | C:/Users/user/AppData/Local/Android/Sdk | 已存在 |
| 已安裝 SDK Platform | API 26、31、34、35、36 | 足夠建立 MVP |
| 已安裝 Build Tools | 34.0.0、35.0.0、36.1.0 | 足夠建立 MVP |
| JDK | Java 編譯目標 17；近期 build 使用 JBR 21.0.11 | 已通過目前 AGP 8.11.1／Gradle 8.13 編譯 |
| ADB / sdkmanager | 已可使用 | 可部署至實體手機 |
| Gradle 全域命令 | 未安裝 | 核可後以 Android Studio / Gradle Wrapper 處理 |

### 第 1 階段實施紀錄

- 已建立 E:/10_DevCode/VRchat-track/android 的原生 Kotlin 專案。
- 已固定 AGP 8.11.1、Gradle Wrapper 8.13、Java 編譯目標 17、compileSdk 36、minSdk 24 與 CameraX 1.6.2；實機 build 使用 JBR 21。
- 已成功執行 app:assembleDebug 與 app:lintDebug；debug APK 已產生。
- 已在 Pixel 6 / API 35 Android Emulator 完成安裝、啟動、CAMERA 權限與前鏡頭預覽驗證。
- 已加入 MediaPipe Tasks Vision 1.0.0、Lite 模型、LIVE_STREAM 與 ImageAnalysis；Samsung SM-A5360 已安裝並取得人體 33 點結果。
- 實機已完成 CPU／GPU 分段比較，GPU 為預設、失敗時回退 CPU；已完成手機到 Windows 熱點的 UDP／ACK 初測，詳細結果見 android/TEST_RESULTS.md。

### 開始前仍須具備

| 項目 | 所需條件 |
| --- | --- |
| Android 手機 | Android API 24 以上、相機可用、可授予相機權限 |
| 部署 | 開發人員選項 + USB 偵錯，或已設定的同網段無線 ADB |
| 網路 | 手機與 PC 位於同一私人 LAN；建議 5 GHz Wi-Fi |
| 取景 | 手機可固定並完整拍到頭、軀幹、手與腿；光線穩定 |
| Avatar | 可編輯的 Humanoid Avatar 3.0 專案，或最小 Humanoid 測試 Avatar |
| 遠端測試 | 一名可進入私人房間的測試者（可選，但原始目標需要） |

## 4. 技術設計

### 4.1 Android 原生擷取

- 使用 Kotlin、Android Studio 與實體 Android 裝置；最低版本為 minSdk 24。
- 使用 CameraX ImageAnalysis，採 STRATEGY_KEEP_ONLY_LATEST，避免辨識落後時累積過期影格。
- 使用 MediaPipe Pose Landmarker 的 LIVE_STREAM 模式。
- 先採 CPU + 較輕量模型建立穩定基線；GPU delegate 僅在有量測結果後比較。
- 每個人最多一組 33 個 pose landmarks；保留 normalized landmarks（畫面座標）與 world landmarks（公尺、以髖部中點為原點）供校正與除錯。
- 實體手機是效能測試依據；Android 模擬器不作為相機與推論效能結論。

### 4.2 landmark 篩選、校正與姿勢轉換

1. 每個 frame 帶有 seq、手機單調時鐘的擷取／送出時間、inference 耗時與 landmark 可見度。
2. 肩、肘、髖、膝等核心關節的 visibility 或 presence 低於 0.50 時，標示為低可信度，不用它瞬間覆寫目前姿勢。
3. 以站立 T-pose 進行至少 3 秒校正，後續骨向量轉成相對校正姿勢的局部角度。
4. MVP 使用 EMA 或 One Euro filter、角度範圍限制與短暫遺失保持；所有濾波參數寫入測試紀錄。
5. 單鏡頭 world landmarks 是身體相對資料，不當作可靠的房間世界座標或精準前後深度。第二鏡頭是後續改善遮擋與深度歧義的階段，不是 MVP 前提。

T 字校正對應參數 0；沒有追蹤輸入的待機值則讓左右上臂為 -1（放下），其餘四個關節為 0。關節超過保持時間後回到各自待機值。

### 4.3 Wi-Fi LAN 與 Windows receiver

第一版採 UDP + UTF-8 JSON，以可讀性與除錯速度優先。封包只能在私人 LAN 使用，接收埠不得暴露到網際網路。

~~~json
{
  "version": 1,
  "session": "session-id",
  "seq": 1234,
  "captureMonotonicNs": 0,
  "captureTimestampSource": "camera-device-unspecified",
  "analysisStartMonotonicNs": 0,
  "sendMonotonicNs": 0,
  "inferenceMs": 0.0,
  "personDetected": true,
  "landmarks": [{"x": 0.0, "y": 0.0, "z": 0.0, "visibility": 1.0, "presence": 1.0}],
  "worldLandmarks": [{"x": 0.0, "y": 0.0, "z": 0.0, "visibility": 1.0, "presence": 1.0}]
}
~~~

Windows receiver 必須：

- 驗證 schema、版本、seq 遞增與 landmark 數量；拒絕異常或過大的封包。
- 記錄封包到達率、序號缺口、解析失敗、到達間隔、jitter 與最後有效姿勢。
- 回覆包含 seq 的 ACK；Android 使用自己的單調時鐘記錄 application RTT。
- 不將 Android 與 Windows 的不同時鐘相減後誤報為單程延遲或完整 pose-to-photon 延遲。
- 相機原始時間戳的時間基準尚未驗證，不能直接與手機 elapsedRealtime 或 Windows 時鐘相減。使用方式及安全範圍見 windows/README.md。

### 4.4 VRChat OSC 與測試 Avatar

MVP 只建立 6 個 Float Parameters。它們每個只映射 Avatar 的局部骨頭，不動畫化 Root。

| 參數 | 視覺效果 |
| --- | --- |
| Puppet/LeftArmRaise | 左上臂相對校正姿勢的抬舉 |
| Puppet/RightArmRaise | 右上臂相對校正姿勢的抬舉 |
| Puppet/LeftElbowFlex | 左手肘彎曲 |
| Puppet/RightElbowFlex | 右手肘彎曲 |
| Puppet/LeftKneeFlex | 左膝彎曲 |
| Puppet/RightKneeFlex | 右膝彎曲 |

- Windows receiver 將濾波後的值發至 VRChat OSC /avatar/parameters/參數名稱。
- 測試 Avatar 使用只改局部骨頭的 Animator layer，保留 VRChat Desktop 的原生 locomotion／WASD。
- 6 個 Float 先設為同步參數並確認 Expression Parameters 預算；約使用 48-bit，低於 VRChat 的 256-bit 自訂同步參數總預算。
- 本機收到 OSC 與其他人看到平滑姿勢是不同問題。Playable 同步通常約為每秒 1–10 次，遠端動態姿勢可能不夠平滑，必須在私人房間實測。

## 5. 執行順序與時間估計

| 階段 | 工作內容 | 產出／完成條件 | 預估 |
| --- | --- | --- | --- |
| 1 | 部署 Android 原生環境 | Android Studio、SDK、JDK／Gradle Wrapper 與實機 build／install 成功 | 1–1.5 小時 |
| 2 | 擷取與過濾 landmark | CameraX + Pose Landmarker、33 點除錯畫面、校正、可見度門檻與濾波記錄 | 2–3 小時 |
| 3 | Wi-Fi LAN receiver | 手機傳 landmark、Windows 記錄／ACK、封包統計報告 | 1.5–2 小時 |
| 4 | VRChat OSC + 測試 Avatar | 6 個參數、Animator 映射、本機 VRChat 驗證、WASD 共存 | 1–2 小時 |
| 5 | 端到端與可重做性測試 | 10 分鐘壓力測試、延遲／完整度報告、部署與啟動說明 | 1.5–2.5 小時 |

**總預估：7–11 小時**，不含 Android Studio／Unity／VRChat SDK 首次下載、手機未知問題，以及建立或取得可編輯 Avatar 的時間。

## 6. 驗收門檻與量測

| 類別 | 最低驗收門檻 | 紀錄方式 |
| --- | --- | --- |
| 手機辨識 | 連續 10 分鐘；完整入鏡與良好光線下，目標至少 15 FPS | FPS、inference p50/p95、溫度／降頻、偵測遺失次數 |
| landmark 完整度 | 正常偵測時 33 點齊全；核心關節 visibility/presence >= 0.50 才採用 | frame／關節有效率與拒絕原因 |
| LAN 完整度 | 10 分鐘內 JSON schema 解析錯誤為 0；UDP seq 遺失率目標 < 1% | seq 缺口、封包數、封包大小、到達間隔、jitter |
| 網路時間 | 回報 Android 量得的 ACK RTT p50/p95；另列 inference 與 receiver 處理時間 | 不將未同步時鐘的數據誤報為單程延遲 |
| VRChat 本機 | 六個參數方向與範圍正確；抬手／彎肘／彎膝都驅動對應局部骨頭；WASD 正常 | 參數測試表與錄影／截圖 |
| 遠端可見性 | 有測試者時，在私人房間逐項確認；無測試者時列未驗證 | 可見性、更新感受、卡頓與可接受性 |
| 流程可重做 | 新一次啟動可依文件完成安裝、IP 設定、App、receiver 與 VRChat 測試 | README／測試紀錄與固定版本 |

### 視覺端到端延遲的正確測法

ACK RTT 只證明 App ↔ receiver 的往返時間，不包含相機曝光、推論排程、OSC、VRChat Animator 與螢幕顯示。若要聲稱人體動作到 Avatar 顯示的延遲，需要另一台錄影設備同時拍到動作事件與 VRChat 畫面，再逐格計算。若沒有額外錄影設備，報告僅分開列 inference、網路與 receiver 指標。

## 7. 主要風險與決策規則

| 風險 | 事先處理方式 | 決策規則 |
| --- | --- | --- |
| 手機過熱或 FPS 太低 | 先低複雜度模型、CPU 基線、固定手機與穩定光源 | 10 分鐘無法穩定時，先降解析度／模型，再比較 GPU delegate |
| Wi-Fi 抖動或封包遺失 | 同一私人 LAN、優先 5 GHz；只傳 landmark | 遺失率 >= 1% 時先檢查 AP、頻段、距離與背景流量 |
| 單鏡頭遮擋／深度歧義 | 低可信度保留、平滑、角度限制 | 核心動作仍不穩時，再排入第二手機 |
| locomotion 覆寫姿勢 | Animator 只處理局部骨頭，絕不寫 Root | WASD 受影響時先修 Avatar layer，再調 landmark |
| 遠端同步不夠平滑 | 先做本機正確性，再私人房間實測 | 顯著跳動時列為 MVP 限制，不假定提高資料率即可解決 |
| Avatar 不可編輯 | 先確認 Avatar 3.0 專案或最小測試 Avatar | 僅能完成 OSC receiver，不能宣稱 VRChat 驗收完成 |

## 8. 最初核可後的第一輪工作界線（已完成）

第一輪先做第 1 階段與必要最小準備，這些項目目前已完成：

1. 安裝／確認 Android Studio 與實機 ADB 部署。
2. 建立最小 Kotlin Android App，確認相機權限與單一預覽。
3. 固定 MediaPipe、Gradle 與 Android SDK 的實際版本。
4. 建立可重跑的環境紀錄。

雙手機、骨架融合與完整 18 軸仍不在本 MVP 範圍；VRChat 遠端同步尚未驗證。

## 9. 依據與來源（2026-11-03 審核）

- [MediaPipe Pose Landmarker for Android](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker/android)：Android 支援、33 個 pose landmarks、LIVE_STREAM 與模型資產使用方式。
- [MediaPipe Android setup guide](https://developers.google.com/edge/mediapipe/solutions/setup_android)：Android 最低 API 24、實體裝置與 CPU/GPU delegate 指引。
- [CameraX ImageAnalysis](https://developer.android.com/media/camera/camerax/analyze)：STRATEGY_KEEP_ONLY_LATEST 的丟棄舊影格策略。
- [MediaPipe Pose Landmarker world coordinates](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker/python)：world landmarks 的公尺單位與髖部中點原點定義。
- [VRChat Animator Parameters](https://creators.vrchat.com/avatars/animator-parameters/)：256-bit 自訂同步參數預算、Float 位元量與 Playable sync 更新率注意事項。
- [Android Studio system requirements](https://developer.android.com/studio/install.html) 與 [AGP 9.4 release notes](https://developer.android.com/build/releases/agp-9-4-0-release-notes)：Windows／JDK 17 相容性依據。

## 10. 核可紀錄與下一個外部條件

- MVP v0.2 已於 2026-11-03 核可。
- 2026-11-04：實體手機 USB 偵錯、相機權限、人體辨識、CPU／GPU 比較與短時間 Wi-Fi 收發已完成。
- Windows 接收端已實作六個關節角度的校正、低信心處理、平滑、本機 OSC 輸出，以及 Windows 收包至送出 OSC 的分段計時。自動測試包含模擬姿勢封包到 OSC；另以診斷工具確認 VRChat 收到六個 OSC 參數，但手機經 receiver 到遊戲的完整流程尚未驗證。
- 使用者選擇 VRChat SDK 官方測試 Avatar。Creator Companion、Unity Hub、VPM 和 Unity Editor 2022.3.22f1 已安裝在 `E:\UnityTools`；官方 Avatar 範本專案已建立並還原 VRChat SDK 3.10.6。Unity Hub 登入／授權及 Editor 開啟已確認。
- 官方 Robot PC 場景已另存至 `Assets/VRChatTrackRobot.unity`，六參數 Animator 已在 Unity 通過實際骨骼測試、反方向與同時作用檢查；SDK 本機 Build & Test 已成功產出測試 Avatar。VRChat Desktop 已回傳六個 OSC 測試參數，使用者確認上半身、彎膝與 WASD 共存正常；先前彎膝時走路滑行已修正，遊戲內重測通過。詳見 `VRChatTrackAvatar/TEST_RESULTS.md`。依 VRChat 的原始碼管理指引，SDK 本身由 VPM 還原，不加入 Git；保留 VPM Resolver。
- 10 分鐘 LAN 壓力測試、完整端到端視覺延遲與遠端同步仍待驗證。單一鏡頭的六個單軸參數不等同完整 3D 骨架追蹤。
- 因使用者指出零值待機呈 T 字平舉，已將無追蹤時的雙臂預設改為 -1；T 字校正仍為 0。Unity 骨骼測試及 SDK 本機建置通過，使用者重新套用後也確認遊戲內雙臂自然放下。
- Windows 接收端已補強過大 UDP 封包、Windows UDP 重設與校正樣本過期的處理，新增實機統計及合成 loopback 壓力工具。Android 新增辨識回呼頻率日誌、拒絕過期／重複回呼，並提供離線彙整；新版 APK 已建置與 lint，但尚未安裝至實機。操作與量測限制見 `windows/README.md`、`android/README.md`。
- Git 修改待使用者手動檢查，未經後續明確要求不提交。
- Android Emulator 已驗證 App 啟動與權限流程，但不作為相機 FPS、真實人體影像或 MediaPipe 推論效能的結論。

