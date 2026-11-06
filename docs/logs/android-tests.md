# 第 1 階段驗證結果

## 2026-11-06：選用的同影格影像對照工具（App 0.2.0）

- `app:assembleDebug`、`app:lintDebug`：通過；lint **0 errors、28 warnings**。使用本機 Microsoft JDK 17；先前以目前 Android Studio JBR 25.0.4 啟動時，既有 Gradle／Kotlin 工具鏈在配置階段失敗，未變更專案版本來迴避。
- 獨立 `DiagnosticCaptureCheck.kt`：通過。涵蓋預設關閉、取樣間隔／張數／期限、單張影像所有權、停止及舊批次不可發布、時鐘倒退、原子成對檔案、PNG SHA-256、失敗／超量寫入清理、不可覆寫、空的新批次不遮蔽舊的完整批次，以及 ZIP 匯出。
- 使用正式 `DiagnosticPairStore` 產生 JVM 合成 PNG／landmarks ZIP，Windows `inspect_pose_pairs.py` 成功驗證並產生檢視頁。這驗證儲存／交換格式，沒有驗證真手機 Bitmap 編碼、GPU 回呼或觸控匯出。
- 產物：package `com.vrchattrack.singlephone`、versionCode **2**、versionName **0.2.0**。APK SHA-256：`2a7f37489d0062783cbd3fa74d7fe5acbdcd0fa64ba72860c41f4efdad63f8f9`。目前建置完成，手機更新與實機影像擷取仍待確認。
- 本機配對與 UDP 共用來源序列化，新增影格／方向／模型資訊，保持協定 version 1 與座標四位小數。影像對照預設關閉，不會因啟動 App、開始 LAN 或重啟而自動啟用；照片不透過 UDP 傳送。保存於 App 私有 no-backup 目錄，使用者明確選擇才匯出 ZIP。

操作與限制見 [同影格工具](../../windows/IMAGE_PAIR_GUIDE.md)。Windows 最新 **69 項自動測試通過**；新檢視工具不開 socket／不送 OSC。手機端實際影像與點位對齊、保存負載、背景停止與匯出仍待驗證；不得據此宣稱高度精度、手機 FBT 或 Unity smoke test 已通過。

驗證日期：2026-11-03  
目標：確認 Android 原生基線的型別、虛擬裝置啟動與 CAMERA 權限流程。

## 工具鏈

| 項目 | 固定版本／結果 |
| --- | --- |
| Android Studio | 2025.1，E:/AndroidStudio |
| JDK | 17（Android Studio bundled runtime） |
| Android Gradle Plugin | 8.11.1 |
| Gradle Wrapper | 8.13 |
| compileSdk / targetSdk | 36 / 36 |
| minSdk | 24 |
| CameraX | 1.6.2 |
| MediaPipe Tasks Vision | 1.0.0 |
| Pose 模型 | pose_landmarker_lite.task（官方 Lite 模型） |

## 靜態與型別檢查

- app:assembleDebug：成功。
- app:lintDebug：成功。
- APK package：com.vrchattrack.singlephone。
- APK manifest：宣告 android.permission.CAMERA。
- APK SDK 設定：minSdk 24、targetSdk 36。

## 虛擬裝置執行

| 項目 | 結果 |
| --- | --- |
| AVD | Pixel 6 / API 35 / Google Play x86_64 |
| Hypervisor | Windows Hypervisor Platform 可用 |
| APK 安裝 | 成功 |
| 啟動 | 成功，前景為 MainActivity |
| 初始 CAMERA 狀態 | granted=false |
| 系統權限提示 | 顯示「Allow VRChat Track MVP to take pictures and record video?」 |
| 授權選項 | While using the app / Only this time / Don’t allow |
| 選擇 While using 後 | granted=true |
| CameraX 結果 | 前鏡頭 Camera ID 1 由 com.vrchattrack.singlephone 取得 |
| UI 狀態 | 「前鏡頭已啟動：第 1 階段預覽完成。」 |

## 已知限制

這台 AVD 預設設定為前鏡頭 none；需要以 emulator 的 camera-front emulated 選項啟動。此驗證只覆蓋 App 流程，不覆蓋真實手機相機、人體影像、MediaPipe 推論、網路延遲或 VRChat。

## 第 2 階段的目前驗證

- MediaPipe Tasks Vision 1.0.0、Lite 模型、LIVE_STREAM、CameraX ImageAnalysis 與 landmark 型別已通過 Kotlin 編譯。
- 更新 APK 已在相同 AVD 安裝與啟動；Camera service 顯示此 App 的前鏡頭有兩條 stream（Preview 與 ImageAnalysis）。
- AVD 的 emulated 鏡頭沒有真人，因此尚不能以它宣稱 33 個 landmark、可見度篩選、FPS 或資料完整度已驗證。

## 2026-11-04：實機 CPU／GPU 延遲初測

- 裝置：Samsung SM-A5360；Pose Landmarker Lite、LIVE_STREAM、前鏡頭。
- 每模式先預熱 3 秒，再量測 20 秒；只採計 pose=true 且計時可用的結果。p50、p95 由逐筆結果計算。

| 模式 | 人體樣本 | 無人體結果 | 準備 p50 | MediaPipe p50 | 擷取 p50 | 合計 p50 | 合計 p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| CPU | 156 | 16 | 12.27 ms | 152.94 ms | 0.47 ms | 169.75 ms | 286.92 ms |
| GPU | 304 | 1 | 10.92 ms | 93.34 ms | 0.58 ms | 106.80 ms | 181.20 ms |

GPU 合計 p50 較 CPU 低 62.95 ms（約 37.1%）。多次觀察到關鍵點信心偏低，兩階段無人體結果數不同；這是初步比較，不能推論長時間穩定性或 VRChat 完整延遲。MediaPipe 時間包括框架排程與回呼等待，並非純模型 kernel 時間；各分段 p50 獨立計算，不一定與合計 p50 相加相等。

## 2026-11-04：手機到 Windows Wi-Fi 初測

- 實機 APK 已安裝，啟動後 Logcat 確認預設 GPU；CAMERA、INTERNET、ACCESS_NETWORK_STATE 均已授權。
- 手機連至 Windows 熱點，Android 發送 UDP JSON，Windows 驗證 33 個 normalized 與 33 個 world landmarks 並回 ACK。
- 人體傳輸階段約 30 秒，手機日誌在第 371 個送出封包時顯示 ACK 370、RTT p50 15.01 ms／p95 37.24 ms；最後一筆仍可能在途中，不能據此視為遺失。Windows 整次初測包含兩個發送 session：收到並接受 1570 個封包，其中 611 筆人體、959 筆空姿勢；格式錯誤、序號缺口與亂序皆為 0。此非 10 分鐘壓力測試。
- 完整人體 JSON 封包約 5.2 KB，高於測試 Wi-Fi 介面的 1500-byte MTU，可能發生 IP 分片；後續需觀察長時間丟包及是否值得精簡格式。
- 發現本機 Windows Python 的 monotonic 時鐘解析度不足後，接收端改用 perf_counter_ns。修正後以空姿勢封包測試 15 秒：349 個均有效、格式錯誤及序號缺口為 0；Windows 接收／驗證／回 ACK 時間 p50 0.216 ms、p95 0.342 ms。這是空姿勢結果，不可套用到完整人體封包。

RTT 在手機同一個單調時鐘內計算，包含最終 JSON 編碼、往返網路與 Windows 處理；不是單程延遲，也不包含相機曝光、VRChat 與螢幕顯示。相機原始時間戳來源尚未驗證，不直接與其他時鐘相減。

## 2026-11-04：長時間測試紀錄準備

- 新增以實際 MediaPipe 結果回呼計數的 `POSE_RATE` 日誌；使用獨立 Kotlin 檢查涵蓋多視窗、結果中斷及計時重置。傳輸端也會依持續記錄的時間戳拒絕重複或較舊的回呼；獨立 Kotlin 檢查通過。
- JBR 21 與本機 Gradle 快取執行 `app:assembleDebug`、`app:lintDebug`：通過。新的 debug APK 尚未安裝到 Samsung 實機。
- 專案的 API 35 虛擬裝置以唯讀、無視窗模式安裝並啟動新 APK；模擬器輸出 CPU 模式的 `POSE_RATE`，Windows 彙整工具成功解析連續視窗。最終 APK 透過模擬器虛擬網路送出無人體封包到 Windows，receiver 接受 29 筆、格式與序號缺口為 0，模擬器紀錄 ACK 29 筆。receiver 結束後 App 又繼續送出，因而出現預期的後續 ACK 逾時；不將這段逾時當成連線期間的丟包。測試後模擬器及專用 ADB server 已關閉。
- 模擬器沒有真人、GPU 情況也不同；其結果不代表 Samsung 的辨識頻率、溫度、Wi-Fi 品質或完整流程。10 分鐘實機測試仍待使用者在場完成。

