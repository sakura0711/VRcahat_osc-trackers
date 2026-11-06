# 固定影像離線模型比對：右腳高度低估

**下一步先保留 App 0.2.0 與手機 OSC 關閉。Full 是值得後續驗證的候選，尚不能因這輪桌面結果就更新 App 或宣稱高度問題已修復。** 本輪只使用已保存 PNG，沒有新拍攝、手機操作或真人動作。

## 已證實：同圖更換模型會明顯改變結果

輸入沿用 [上一輪影像調查](IMAGE_PAIR_REVIEW_2026-11-06.md) 的同一 ZIP，SHA-256 `da27054e6dab99f031cb5cc4f897bde61a180f8f599d1cf6f4978c0795645d2c`。22 張 PNG 原始像素／尺寸保留，不再鏡像、旋轉或外部縮放；RGB 轉換前確認全部為 RGB 或 alpha 全不透明。三個模型各推論 22 張，皆有 20 張通過幾何檢查；同樣的 16 張保持姿勢照片全有效，沒有以不同有效樣本挑選結果。

桌面使用既有 **MediaPipe Python 0.10.21／CPU XNNPACK／獨立 IMAGE**。手機原始資料來自 **Android tasks-vision 1.0.0／LIVE_STREAM**，delegate 未記錄；兩者不是完全相同的執行路徑。官方提供 [Lite／Full／Heavy 模型與輸出定義](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker)，[IMAGE 模式範例](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker?tab=Python) 說明單張推論方式。Full／Heavy 從官方連結下載後固定 SHA-256，沒有上傳照片；Lite 直接使用專案既有 Android asset。

校正照片第 3–7 張、箱面第 10–15 張、放回第 17–21 張；髖高 0.90 m、mirror=true、swap=true、forward=-1、yaw=0。沿用前一報告的取樣幾何設定：只在離線分析容許 5000 ms 間隔，正式 250 ms 失追設定未變。每個數字是各階段逐幀結果的中位數差，並非外部量得的踝點位移。

| 資料來源 | 各自校正：對前／後基準上升 | 共用手機原始校正：對前／後基準上升 |
| --- | ---: | ---: |
| 手機已保存的 Lite 結果 | 5.05／5.13 cm | 5.05／5.13 cm |
| 桌面 Lite IMAGE | 6.01／6.58 cm | 5.80／6.35 cm |
| 桌面 Full IMAGE | **16.24／16.29 cm** | **14.28／14.25 cm** |
| 桌面 Heavy IMAGE | 7.11／6.72 cm | 2.55／2.02 cm |

Full 自己校正與手機原始校正的尺度分別為 1.04689／1.04925，相近。**共用同一組上軸、尺度、鏡像／角色設定、地面算法與照片後，Full 仍比原始資料高約 9.2 cm**，所以不能把差異全歸因於校正尺度、不同輪姿勢或更換鏡頭。這證明來源估計有重要影響；沒有排除透視造成的共同困難，也不代表 Full 已達 20 cm。

桌面 Lite 的獨立單張也重現偏低，不必依賴 Wi-Fi 或手機連續串流才會出現這類低估。但不能由此精確拆分 Android／桌面版本、delegate、追蹤 ROI 或時間平滑各占多少。

## 2D／3D 交叉替換：高度差異來自來源 world 幾何

另做兩項純離線試算，均固定手機原始校正；選定照片的信心檢查全通過：

| 2D 來源 | 3D 來源 | 右踝上升（對前／後基準） |
| --- | --- | ---: |
| Full | 手機原始 | **5.05／5.13 cm** |
| 手機原始 | Full | **14.28／14.25 cm** |

現有 `tracker_pose.py` 以 normalized 點作信心門檻，位置由 world 點計算；normalized x／y 不直接決定 tracker 公尺高度。因此換 2D 座標而保留原始 3D 不會修好本輪高度，3D 替換才重現 Full 的數值變化。這只是算法路徑的因果隔離：模型的 2D 定位與 3D 推論仍可能相互關聯，不能說 2D 誤差對模型完全無影響。

代表照片第 11 張，右踝點 27 的影像 y 為手機 **483.58 px**、Lite **480.84 px**、Full **477.44 px**、Heavy **476.63 px**；Full 與 Heavy 的點都比原始點靠上，兩者 3D 高度結果卻差很多。可見單看點貼在腳上，不足以證明公尺坐標正確。人工未建立精確的踝骨標記真值，不把這些座標差當作像素誤差分數。

## 腿長與地面的進一步分解

Full 的來源右大腿段長仍縮短 **10.97%**，比原始手機的 9.21% 更大；Heavy 只縮短 **6.41%**，高度卻更低。這表示「腿段縮短」是異常線索，不能單獨當作主因或選模型的標準，也不能只固定骨長就當作修復。

固定手機校正時，原始右踝相對髖高度的模型 Y 投影中位數由約 -74.77 cm 變 -66.59 cm；模型 Z 投影同時由 -4.04 cm 變 -5.99 cm，削去部分升高。Full 的 Y 項由約 -76.93 cm 變 -61.85 cm，Z 項只由 -4.03 cm 變 -4.67 cm。各分量獨立取中位數，不能視為精確相加的等式；數據見 [分析摘要](evidence/2026-11-06-offline-model-comparison.json)。這是模型估計的深度／軸向，不能當成實測手機俯仰或腳部深度。

地面也會隨來源模型改變：手機原始與桌面 Lite 在選定階段均以左腳尖作最低點；Full／Heavy 的站姿常以右腳尖作最低點，抬腳後又改變。固定手機校正的 Heavy 在箱面六張中甚至有兩張仍以模型右腳尖作最低點，儘管使用者確認真人右腳在箱上。

僅利用「本輪左腳一直留地」的已確認條件，試算始終由左腳 heel／toe 最低點定地面：原始資料仍為 5.05／5.13 cm；Full 各自校正為 17.36／17.14 cm，Heavy 為 10.96／9.95 cm。這是依已知動作的反事實分解，**沒有加入正式程式、沒有接觸地面偵測器，也不能推廣到任意動作**。它支持未來須一起驗證來源腳部幾何與接觸／地面策略；不是選定支撐腳就能解決原始低估。

## 可重現的離線工具與檢查

新增 `offline_pose_compare.py`。它只接受本機模型，不自動下載、不開 receiver，也沒有 OSC 選項。CLI 以 audit hook 阻止 Python socket 建立／連線／sendto／名稱解析；MediaPipe 延後匯入，既有標準庫套件無須新增依賴。新推論檔案與手機原始資料分開，保留原圖影格 ID／雜湊對照，去除手機舊 session／傳輸時間／處理時間，不能拿去當原始手機同幀紀錄接回 JSONL。

在 `windows` 執行；模型已另存本機忽略目錄，輸出須使用不存在的新目錄：

~~~powershell
python -B offline_pose_compare.py captures/right-box-images-20261106/source.zip --model lite=../android/app/src/main/assets/pose_landmarker_lite.task --model full=captures/pose-model-ab-20261106/models/pose_landmarker_full.task --model heavy=captures/pose-model-ab-20261106/models/pose_landmarker_heavy.task --before 3-7 --raised 10-15 --after 17-21 --hip-height 0.90 --mirrored-input yes --swap-left-right --forward-sign -1 --yaw 0 --output captures/pose-model-ab-20261106/new-run
~~~

- 正式輸出 `captures/pose-model-ab-20261106/run-02` 與初次研究輸出數值完全一致；新格式未沿用手機處理／傳輸欄位。
- Full 將 22 張順序反轉再做 IMAGE 推論，對回相同原圖後所有座標／信心的最大差為 **0**。這只驗證本輪獨立單張重現性，不能取代 LIVE_STREAM 重播。
- 全部新模型輸出捨入為手機同樣四位小數後，固定校正的高度增量最大變化約 **0.0102 cm（0.102 mm）**，遠小於模型間差異。
- Windows `python -B -m unittest discover -v` 最終 **76 項通過**；新增 7 項覆蓋已知 20 cm 合成資料、鏡像／角色設定、不改原資料、固定／獨立尺度、缺值／失敗、分段／輸出拒絕、推論身份隔離與 socket 保護。既有網路測試只使用本機隔離動態埠，不向 VRChat 9000 發送手機資料。本次普通權限完整通過，未變更防火牆，不能據此宣稱舊的間歇埠問題已修復。

模型與工具 SHA-256、階段數據、交叉替換、地面分解及驗證記錄均在 [衍生 evidence](evidence/2026-11-06-offline-model-comparison.json)。新推論點、模型檔、原始 PNG 和圖表只留本機 `captures`，不加入 Git。圖表：`captures/pose-model-ab-20261106/run-01/height-model-comparison.png` 與 `same-frame-model-feet.png`。

## 待驗證

Full 是本批影像較好的候選，還沒有 Android 相同版本／delegate／LIVE_STREAM 的對照、連續動作自然度、完整像素真值或公尺校正驗收。單一人的單一 20 cm 姿勢也不能代表其它角度、遮擋或動作。

相機內參、實測俯仰與逐幀腳部深度仍缺少，透視不能排除。桌面舊版 runner 有 NORM_RECT／feedback 警告，未建立它與低估的關聯，不能把警告直接當根因。手機 ACK、HMD 對齊、FBT、遠端同步和 Unity smoke 都不在本輪驗收範圍。

下一個安全工作是先設計能區分模型／模式差異的固定影像回放對照，再決定是否需要手機端改動；不要直接換模型或用 20 cm／5.1 cm 倍率補償。若後續確需更新 App 或使用者配合，必須先語音通知。目前無須重拍。
