# Android 固定影像離線回放

**目前先保留手機相機 App 0.2.0。** 已備妥獨立診斷 App **Pose Offline Replay 0.1.0**，套件名稱 `com.vrchattrack.replay`，不覆蓋 `com.vrchattrack.singlephone`。本次只安裝到唯讀模擬器，未更新手機；若之後需使用者安裝或配合，必須先語音通知。

## 已證實

1. APK 建置／lint 通過（0 errors、14 warnings）；原相機 App 的相容建置／lint 亦通過（0 errors、28 warnings），未修改其程式與版本。
2. 最終 APK 的 `aapt dump permissions` **無任何 uses-permission**；v2 簽章與兩份內建模型 SHA-256 均核對成功。沒有網路或相機權限，沒有 OSC、LAN sender 或自動下載功能。
3. Kotlin 主機檢查能解析這批真實 ZIP 的 22 張圖片，涵蓋 PNG CRC／雜湊、身份／尺寸／點陣列、錯誤資料拒絕、停止／過期工作、模型與 delegate 隔離。主機假推論一律標為 synthetic，不能當 Android 實測。
4. 既有 API 35 x86_64 AVD 的唯讀、無視窗實例，真正執行 Android MediaPipe **1.0.0 CPU** 的 Lite／Full × IMAGE／VIDEO，共 **88 次推論**；輸入私有副本與兩份輸出皆逐段核對 SHA-256。模擬器已關閉。
5. Windows 全套最終 **84 項通過**，含新增 8 項回放格式／身份／時間／缺值檢查；早先曾有 10／14 項既有 UDP 測試遇到 WinError 10013，最終提高權限通過，沒有改防火牆或系統埠，不能宣稱環境問題已修復。

## 同一批影像的 Android 結果

原始 ZIP：`../windows/captures/right-box-images-20261106/source.zip`，SHA-256 `da27054e6dab99f031cb5cc4f897bde61a180f8f599d1cf6f4978c0795645d2c`。照片已旋轉／鏡像；解碼時不縮放、不再次套用旋轉或鏡像。第 3–7 張校正、10–15 張右腳在 20 cm 箱面、17–21 張回地面，沿用髖高 0.90 m、mirror=true、swap=true、forward=-1、yaw=0。

| CPU IMAGE | 各自校正：右踝對前／後基準上升 | 共用手機原始校正 |
| --- | ---: | ---: |
| Lite | 6.00／6.58 cm | 5.80／6.35 cm |
| Full | 16.24／16.29 cm | 14.28／14.25 cm |

兩模型選定的 16 張全部有效，與先前桌面 CPU 單張結果接近。**Full 仍未達 20 cm，不能當作手機高度驗收成功。** 這是模擬器 CPU 的原生推論，沒有證實三星手機 arm64／GPU、即時相機或連續動作的結果。

VIDEO 完成 API 呼叫，但兩模型的前站姿均為 **0／5 有效，獨立校正失敗**。共用手機校正時，箱面只有 Lite 1／6、Full 3／6 有效；不能把少量剩餘樣本的中位數拿來與 IMAGE 比高度。Windows 對此輸出 `geometry_comparison_complete=false`，保留缺值／失敗，不補零、不沿用舊姿勢。本批約每 3 秒一張，缺少原始連續影格與追蹤歷史；VIDEO 不等於 LIVE_STREAM 重播。預設先使用 **CPU／IMAGE**。

完整階段數據、APK／原始報告雜湊及限制見 [驗證 evidence](../windows/evidence/2026-11-06-android-replay-preparation.json)。原始照片、模型、新推論點、APK 與模擬器原始報告留在忽略目錄。

## 之後才需要的手機操作

以下流程尚未在實體手機驗證，現在不用操作；開始前先語音通知。

1. 另裝 `replay/build/outputs/apk/debug/replay-debug.apk`，或在 Android Studio 選 **replay** 模組；相機 App 0.2.0 保持原狀。
2. 開啟 Pose Offline Replay，手動匯入已保存的 `pose-image-pairs (1).zip`。不需要重新拍攝、Wi-Fi、ACK 或相機權限。
3. 保持預設 CPU／IMAGE，按「比較 Lite／Full」。完成後再選 GPU／IMAGE 作另一輪；GPU 失敗會記錄 error，不自動回到 CPU。
4. 匯出完成的 JSON。檔案選取器只在明確匯入／匯出時開啟；不會自動開始推論或傳送。離開前景會要求停止，工作資源關閉前不能重開，停止後的舊工作不能發布報告。
5. 將 JSON 放進 Windows 的 `captures`，用下列命令核對與分析。原 ZIP 不改名覆寫，新結果不回填成原手機封包。

在 `windows` 執行（檔名改成這輪匯出的新檔）：

~~~powershell
python -B android_replay.py captures/right-box-images-20261106/source.zip captures/android-pose-replay.json --before 3-7 --raised 10-15 --after 17-21 --hip-height 0.90 --mirrored-input yes --swap-left-right --forward-sign -1 --yaw 0 --output captures/android-replay-summary.json
~~~

工具核對 ZIP／擷取批次、每張原圖 ID／SHA-256／尺寸／方向、兩模型固定雜湊、模式／delegate 一致、完整結果數與點陣列。IMAGE 的框架時間沒有輸入時間語義：原生實測為 `-1`，只保留在 `frameworkTimestampMs` 作診斷，`taskResultTimestampMs=null`；身份由原圖 ID／雜湊決定。VIDEO 的輸入與結果時間則必須完全等於來源影格時間。兩者都不與電腦或當前手機時鐘相減。

缺少人體保留空點，模型錯誤不產生可用資料；輸出不可覆寫，預設拒絕 synthetic 測試報告。`--allow-synthetic` 僅供交換格式檢查，摘要仍保留 `synthetic=true`。GPU 的 configuredDelegate 代表 API 配置與沒有 App 層 CPU fallback，不保證每個 kernel 都在 GPU 執行。

## 建置與主機檢查

使用既有 JDK 17、Gradle／SDK 快取；不安裝或啟動手機：

~~~powershell
$env:JAVA_HOME = 'C:\Program Files\Microsoft\jdk-17.0.15.6-hotspot'
.\gradlew.bat --offline --no-daemon :replay:assembleDebug :replay:lintDebug :app:assembleDebug :app:lintDebug
~~~

回放 APK 只打包兩個公開模型，**不包含本批照片**。Lite 使用現有相機 App 的 asset；Full 使用 `../windows/captures/pose-model-ab-20261106/models/pose_landmarker_full.task`，也可用 `-PposeFullModel=PATH` 指定本機檔案。建置任務先核對固定雜湊，不自動下載：

- Lite：`59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a`。
- Full：`4eaa5eb7a98365221087693fcc286334cf0858e2eb6e15b506aa4a7ecdcec4ad`；來源為 [Google 官方模型清單](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker) 的 Full bundle。若新版下載雜湊不同，須明確建立新實驗，不能略過驗證。

主機 Kotlin 檢查使用 `org.json:json:20250107` 測試 JAR（APK 不打包此 JAR，Android 使用框架 JSON）。本機位置 `replay/build/check-tools/json-20250107.jar`，SHA-256 `85d4c1ab192d3117fd02c7fff1ec0fe63ade45cf56def7fe950ef060cf06e99f`。可由 [Google Maven Central HTTPS 鏡像](https://maven-central.storage-download.googleapis.com/maven2/org/json/json/20250107/json-20250107.jar) 取得並核對此 SHA-256；本次未關閉 TLS 驗證。它只供測試，存於忽略的 build 目錄。

~~~powershell
$env:JAVA_HOME = 'C:\Program Files\Microsoft\jdk-17.0.15.6-hotspot'
$replayCompiler = 'E:\AndroidStudio\plugins\Kotlin\kotlinc\bin\kotlinc.bat'
$replayJson = 'replay\build\check-tools\json-20250107.jar'
$replayCore = 'replay\src\main\java\com\vrchattrack\replay'
& $replayCompiler "$replayCore\ReplayArchive.kt" "$replayCore\ReplayRunner.kt" tests\ReplayCheck.kt -cp $replayJson -include-runtime -d replay\build\replay-check.jar
& "$env:JAVA_HOME\bin\java.exe" '-Djava.awt.headless=true' -cp "replay\build\replay-check.jar;$replayJson" com.vrchattrack.replay.ReplayCheckKt
~~~

檢查器可另帶原 ZIP 與一個不存在的 JSON 路徑，產生 synthetic 交換格式；它不呼叫 MediaPipe，不能當成原生推論。本次另有真正模擬器報告，兩者分開。

## 開發者的模擬器入口

debug APK 有 `ReplaySmokeInstrumentation`，僅由明確的 `adb am instrument` 啟動，使用 App 私有 `cache/smoke-source.zip`，不開 Activity／相機。正式 Activity 不根據 Intent 自動匯入或開始。IMAGE／VIDEO 報告各用固定檔名且不覆寫，重跑需使用新的唯讀測試實例，或明確保留先前測試報告後再測。

88 次原生回放完成後，另補上 ZIP 目錄項目必須為空的拒絕檢查；最終 APK 已重新建置／lint，JVM 拒絕案例通過。此修正不改模型、推論 adapter 或本批沒有目錄項目的有效 ZIP 路徑，未再重跑 88 次。原生測試 APK 與最終 APK 的雜湊分別保留於 evidence。

本次只使用 `emulator-5580`，先以 `adb push` 複製到測試暫存區，再 `run-as com.vrchattrack.replay cp` 到私有快取，**兩處 SHA-256 都核對原檔**，之後移除本次暫存副本。不要透過 Windows 標準輸入／文字管線複製 ZIP；本次曾發生截斷，已被 ZIP 檢查拒絕，未產生可用推論。

~~~powershell
adb -s emulator-5580 shell am instrument -w -e mode IMAGE com.vrchattrack.replay/.ReplaySmokeInstrumentation
adb -s emulator-5580 shell am instrument -w -e mode VIDEO com.vrchattrack.replay/.ReplaySmokeInstrumentation
~~~

取得報告時用程式的二進位 `adb exec-out run-as ... cat no_backup/smoke-image.json`，並與模擬器私有檔的 SHA-256 比對；不要經 PowerShell 文字重導向。兩份報告原始路徑為 `../windows/captures/android-replay-20261106/emulator-image.json`／`emulator-video.json`。這輪已完成，不必例行重跑。

## 待驗證

實體手機的檔案選取、前景／背景停止、GPU 初始化／結果、資源負載與長時間使用仍待驗證。沒有重建原始 LIVE_STREAM，也沒有對 HMD、VRChat FBT／IK、遠端同步或 Unity smoke 作新驗收。Full 的公尺幅度仍不足，透視／2D／3D 真值仍未完全分離；禁止將此回放結果直接送進 VRChat。
