# 同一影格影像／landmarks 對照工具

目前狀態：App 0.2.0 與 Windows 檢視工具已完成自動檢查；**Samsung 真手機 PNG 擷取、ZIP 匯出與 Windows 匯入已確認**。22 組新影像完整拍到右腳箱面動作；[離線影像調查](IMAGE_PAIR_REVIEW_2026-11-06.md) 仍重現高度低估。GPU delegate、保存負載與背景停止仍待實測。這是高度低估的診斷工具，不會將手機資料接到 VRChat tracker。

## 手機端：預設關閉、明確啟用

1. 先更新至 App **0.2.0（versionCode 2）**。需要使用者安裝或實測前，先播放語音通知，預留就位時間。
2. 在可捲動的底部面板按「開始影像對照（120 秒）」才開始保存。每 3 秒最多一張，最長 120 秒／40 張；也可按「停止影像對照」。
3. 停止、App 失去前景、重新啟動姿勢管線或切換辨識模式會停止取樣；重開 App 不會自動恢復。尚未發布的舊工作會捨棄並清理，停止返回後不會再發布舊批次。
4. 停止後按「匯出最近一次影像對照 ZIP」，由系統檔案選單選擇目的地，例如手機的「下載」。把 ZIP 複製到電腦的 `windows/captures`。純本機擷取不需啟動 Wi-Fi 傳送。

手機保存的是 MediaPipe 結果回呼所附的輸入影像，已套用 CameraX 旋轉／前鏡頭鏡像，**沒有底部 UI、沒有預覽裁切**。回呼中先複製影像，再交給背景工作保存；最多只有一張自有影像在處理。沒有選中的回呼不會複製或保存影像。[MediaPipe 結果回呼介面](https://developers.google.com/edge/api/mediapipe/java/com/google/mediapipe/tasks/vision/poselandmarker/PoseLandmarker)。

資料保存於 App 私有 `noBackupFilesDir/diagnostic-pairs`，不加入相簿、不自動上傳，也不參與 Android Auto Backup。匯出目的地由使用者選擇；匯出後的 ZIP 是另一份檔案。[Android 備份範圍](https://developer.android.com/identity/data/autobackup)、[系統檔案匯出](https://developer.android.com/training/data-storage/shared/documents-files#create-file)。

每張圖為無損 PNG；單張編碼上限 8 MiB、輸入尺寸上限 4,194,304 像素、單批儲存上限 64 MiB。達到限制或寫入失敗時會停止該輪對照並顯示狀態。PNG 與 JSON 先寫入暫存子目錄，確認該批次仍有效後才一次發布；已完成的配對不會覆寫。

## Windows：離線檢視

在 `windows` 執行，將 ZIP 名稱改成實際匯出的檔名：

~~~powershell
python -B inspect_pose_pairs.py captures/pose-image-pairs.zip --output captures/right-step-images.html --swap-left-right
~~~

本次前鏡頭已明確確認左右角色對調，因此範例帶 `--swap-left-right`；不同設備／鏡頭應重新確認。這個選項只改檢視頁的角色名稱，不修改原始影像或座標。工具依原始 PNG 寬高直接疊點，不再次鏡像或旋轉。檢視頁可切換影格、開關疊點及顯示索引；左右角色表同時列出 2D、3D 與信心值。沒有偵測到人時保留空點陣列，不補入上一幀。

匯入時驗證 PNG SHA-256、尺寸／PNG chunk CRC、擷取批次、唯一 frameId、`resultTimestampMs`、來源時間戳、方向、模型資訊及點數。未通過就不產生檢視頁。輸出 HTML 必須是新檔名，既有檔案不覆寫；HTML 內含照片與座標，請留在被 Git 忽略的 `captures` 目錄。

檢視頁自帶圖片與資料，不載入外部腳本／圖片，也不建立 OSC 或其他網路連線。快速切換時會拒絕較舊的非同步圖片回呼，避免舊照片與新座標混用。

## 可選：連結同一輪 tracker 紀錄

若要把照片、來源點與 tracker 高度分解一起看，量測時另行啟動**不送 OSC**的 `tracker_preview.py --record ...`，並在手機同時明確啟用 Wi-Fi 傳送與影像對照。手機影像仍只存本機，UDP 只送姿勢與時間資訊；Windows 回覆 ACK。

~~~powershell
python -B inspect_pose_pairs.py captures/pose-image-pairs.zip --recording captures/right-step.jsonl --output captures/right-step-linked.html --swap-left-right
~~~

工具以同一手機的 `captureMonotonicNs`／`analysisStartMonotonicNs` 精確連結，再核對 2D／3D 陣列與可用的影格／尺寸／方向／模型資訊。不是用兩台設備時鐘相減或猜動作時間。來源不一致、重複識別或整份檔案完全沒有同影格配對時會失敗；只有部分照片在 receiver 工作時段內時，其他照片明確顯示未連結。

App 的本機配對與 UDP 共用 `PoseFrameJson`，維持協定 version 1，新增 `resultTimestampMs`、影像尺寸、旋轉／鏡像與模型名稱；原本座標四位小數及既有欄位語意保持一致。只開本機影像對照時，不會自動啟動 LAN 傳送。

## 已完成與待驗證

- **已完成：** APK 建置／lint、獨立 Kotlin 取樣與儲存檢查、Kotlin 合成 PNG ZIP → Windows 讀取／HTML 產生、最新 Windows 76 項測試（含後續離線模型比較；本機 Node 可用時另驗證檢視頁座標與非同步切換邏輯）；Samsung App 0.2.0 手動擷取／ZIP 匯出／Windows 匯入已有真人影像證據。純本機影像流程不需要 Wi-Fi 或 ACK。
- **待驗證：** GPU delegate、保存負載、按鈕停止競態／背景停止與真人點位精度。實際封包沒有 delegate 欄位，不能僅憑模型預設推定 GPU 通過；合成 JVM PNG 與 Node 的 DOM／Canvas 模型不能替代上述實機驗收。每 3 秒的照片也不能驗證即時失追策略。
- **仍未通過：** 手機動作公尺高度；本工具不改校正／地面／倍率，也不代表 FBT、HMD 對齊、遠端同步或 Unity smoke test 通過。

同一 PNG 可另交由 [離線模型比較工具](OFFLINE_MODEL_COMPARISON_2026-11-06.md) 做桌面 CPU IMAGE 研究。新推論與手機原始結果分開；不得將其回填成原手機紀錄，亦不代表手機更新後已通過。
