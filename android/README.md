# VRChat Track — Android 單手機 MVP

目前已實作手機前鏡頭、MediaPipe Pose Landmarker、關鍵點疊加、CPU／GPU 分段計時與手機到 Windows 的 Wi-Fi UDP 傳輸。**手機姿勢尚未轉成 VRChat 原生 OSC Tracker 輸出。** 虛擬 HMD 的合成 OSC Tracker Phase 0 已通過本機及遠端驗收；請以 [主計畫](../OSC_TRACKER_MVP_PLAN.md) 的狀態為準。手機經 receiver 到 VRChat 的完整流程仍待驗證。

## 已固定的基線

- AGP 8.11.1
- Gradle 8.13
- Java 編譯目標 17；本次實機 build 使用 JBR 21
- compileSdk / targetSdk 36
- minSdk 24
- CameraX 1.6.2
- MediaPipe Tasks Vision 1.0.0、Pose Landmarker Lite

## 本機建置

1. 在 Android Studio 開啟 android 資料夾。
2. 確認 SDK 路徑指向 C:/Users/user/AppData/Local/Android/Sdk。
3. 等待 Gradle 同步，再連接已開啟 USB 偵錯的 Android 手機。
4. 執行 app；允許相機權限後，應看到前鏡頭預覽、姿勢狀態與分段計時。預設使用 GPU；若 GPU 初始化或執行失敗則回到 CPU。

## CPU／GPU 延遲比較

固定手機並讓人體完整入鏡，按「比較 CPU / GPU（約 1 分鐘）」。每個模式預熱 3 秒，再量測 20 秒；僅統計偵測到人體且取得計時的結果。結果顯示各段中位數、合計 p50／p95、有效樣本數及 CPU／GPU 差距。也可用切換按鈕手動切換；重新啟動預設 GPU。

- 準備：CameraX 影格進入分析後，到 Bitmap 旋轉與 MediaPipe 輸入準備完成。
- MediaPipe：提交到收到結果回呼，包含框架排程、處理與回呼等待，不等同純模型 kernel 時間。
- 擷取：回呼後讀取 landmark 與可用性，直到結果整理完成。
- 合計：上述三段，不包含相機曝光、畫面、網路、VRChat 動畫與顯示；各段 p50 獨立計算，不能相加當作合計 p50。

## Wi-Fi 傳輸

先在 Windows 啟動接收端；在手機輸入電腦的私人 IPv4 和 UDP 埠，按「開始傳送」。顯示「收到 ACK」後可查看手機量測的 RTT p50／p95。畫面也列出已送、已回覆、傳送前覆蓋或捨棄的舊影格、逾時與封包大小；若辨識回呼的時間戳重複或倒退，會捨棄該影格，避免較舊結果覆寫新姿勢。離開 App 前景會停止傳送。

只傳 33 個 normalized／world landmarks 和計時資料，不傳相機影像。Android INTERNET 與 ACCESS_NETWORK_STATE 為一般權限；此專案 target SDK 36。接收端命令、協定與量測限制見 windows/README.md。

## 10 分鐘結果記錄

新版 App 會每約 1 秒在 Logcat 的 `PoseLandmarkerEngine` 輸出 `POSE_RATE`：記錄這段時間的 MediaPipe 結果回呼數、其中偵測到人體的次數及 CPU／GPU 模式。這是手機上的**辨識結果回呼頻率**，不是相機原始 FPS 或 Windows 收包頻率；兩者差距可能來自丟棄或網路。計時從第一個回呼開始，沒有回呼的間隔會在下一個結果到達時計入；程式退出或停止後未再收到回呼的尾段不會自動計入。

本次新增紀錄的 APK 已通過建置與 lint，但尚未安裝或在實機驗證。回到電腦後連接已授權 USB 偵錯的手機，可用 Android Studio 執行 App，或在專案根目錄執行：

~~~powershell
$adb = 'C:\Users\user\AppData\Local\Android\Sdk\platform-tools\adb.exe'
& $adb devices -l
& $adb install -r .\android\app\build\outputs\apk\debug\app-debug.apk
~~~

在另一個 PowerShell 視窗開始擷取目前之後的手機日誌，接著進行一次不中斷的實機測試：

~~~powershell
cd E:\10_DevCode\VRchat-track\windows
New-Item -ItemType Directory -Force .\captures | Out-Null
$adb = 'C:\Users\user\AppData\Local\Android\Sdk\platform-tools\adb.exe'
& $adb logcat -T 1 -v time -s PoseLandmarkerEngine:I LanPoseSender:I '*:S' | Tee-Object -FilePath .\captures\phone-run.log
~~~

測試結束後以 Ctrl+C 停止擷取，再執行 `python -B summarize_phone_log.py .\captures\phone-run.log`。輸出依 delegate 區分，將各視窗的回呼次數除以總視窗時間，並列出每段低於 15 FPS 的次數；空白、App 中止或重啟的時間不會憑空補進去，因此仍需確認是否連續運行。最新 UDP 狀態的 RTT p50／p95 僅涵蓋最近最多 512 筆，不能當成 10 分鐘的完整分位數。App 若降回 CPU，須分別記錄，不應合併聲稱 GPU 全程正常。

可在測試前後各執行一次 `& $adb shell dumpsys battery`，保留 `temperature` 原始值並註明裝置及單位；這是電池資訊，不等同 CPU／GPU 溫度，也不能單獨證明降頻。日誌包含診斷統計及可能的私人 IP，但不包含影像或 landmark 座標；`windows/captures` 已由 Git 忽略。

## Android Emulator 驗證

已使用 Pixel 6 / API 35 Google Play x86_64 AVD 驗證以下流程：

1. debug APK 可安裝與啟動。
2. Android 35 顯示 CAMERA 的執行階段權限提示。
3. 選擇「While using the app」後，CAMERA 權限為 granted。
4. App 重新取得前景，前鏡頭的 CameraX client 成功連線。

此 AVD 的預設設定沒有前鏡頭。若要重跑前鏡頭驗證，從 PowerShell 執行：

~~~powershell
& 'C:/Users/user/AppData/Local/Android/Sdk/emulator/emulator.exe' -avd 'VRChatTrack_API35' -camera-front emulated -camera-back emulated
~~~

Emulator 只驗證 App 的型別、啟動、權限與 CameraX 流程；它不能取代實體手機的相機品質、效能與 MediaPipe 測試。

## 重跑獨立 Kotlin 檢查

這兩個小型檢查不依賴 Android 或 JUnit，可在已建置的 `android` 目錄執行；編譯器路徑依本機 Android Studio 安裝位置調整：

~~~powershell
$env:JAVA_HOME = 'E:\AndroidStudio\jbr'
$kotlinc = 'E:\AndroidStudio\plugins\Kotlin\kotlinc\bin\kotlinc.bat'
$src = 'app\src\main\java\com\vrchattrack\singlephone'
& $kotlinc "$src\PoseRateMeter.kt" tests\PoseRateMeterCheck.kt -include-runtime -d app\build\pose-rate-check.jar
& "$env:JAVA_HOME\bin\java.exe" -jar app\build\pose-rate-check.jar
& $kotlinc "$src\FrameAdmission.kt" tests\FrameAdmissionCheck.kt -include-runtime -d app\build\frame-admission-check.jar
& "$env:JAVA_HOME\bin\java.exe" -jar app\build\frame-admission-check.jar
~~~

## 還未加入

- Android 端正式校正、角度轉換與濾波；目前由 Windows 實驗性處理
- 手機經 Windows receiver 驅動 VRChat Avatar 的完整流程與長時間驗證

這些項目會依 PROJECT_PLAN.md 的第 2 至第 5 階段依序加入。

