# Windows 接收端

使用 Python 3.12 的標準函式庫，沒有額外套件。預設只監聽 127.0.0.1；手機實測須綁定電腦的私人 IPv4，並可限制手機來源：

~~~powershell
python -B pose_receiver.py --bind 192.168.137.1 --port 8765 --allow-sender 192.168.137.189
~~~

位址請依目前電腦與手機實際網路修改。按 Ctrl+C 結束。若要自動結束，可加 --duration 60。接收端不接受 0.0.0.0 或公開 IP；不要將埠轉發至網際網路。

在手機 App 輸入電腦 IP 與相同 UDP 埠，按「開始傳送」。僅顯示已送封包時，不代表對方已收到；手機顯示「收到 ACK」才表示收到 Windows 回覆。App 離開前景會停止傳送。若收不到 ACK，檢查 Wi-Fi、接收端位址、埠號及 Windows 防火牆。

## 姿勢參數與 VRChat OSC（測試中）

接收端可選擇把姿勢轉成六個 Float 參數，並透過 OSC 發到同一台電腦的 `127.0.0.1:9000`。預設不會送出 OSC；使用時請先開啟 VRChat 的 OSC，並加上 `--osc`：

~~~powershell
python -B pose_receiver.py --bind 192.168.137.1 --port 8765 --allow-sender 192.168.137.189 --osc
~~~

上面的 IP 僅供範例，請改成目前設備的 IP。手機開始傳送後，全身入鏡並保持 T 字站姿，直到終端機顯示校正完成；預設在六個關節都取得近期有效資料後至少持續 3 秒，且每個關節在最近 3 秒內各有 5 筆有效樣本。任一關節超過 1 秒沒有有效資料，或封包中斷超過 1 秒，會重新計時，避免使用長時間遮擋前的舊樣本。這些條件檢查的是可見度與幾何資料，仍須由人保持 T 字姿勢；若持續無法完成，請查看顯示的各關節有效樣本數、調整入鏡範圍和光線。調短校正時間時，樣本視窗最少保留 1 秒。

輸出名稱為 `Puppet/LeftArmRaise`、`Puppet/RightArmRaise`、`Puppet/LeftElbowFlex`、`Puppet/RightElbowFlex`、`Puppet/LeftKneeFlex` 和 `Puppet/RightKneeFlex`。校正姿勢為 0；相對角度變化 90 度對應 1，值限制在 -1 到 1。每個關節只採用 visibility／presence 可用且不低於 0.5 的點，預設 35 ms 平滑；關節遺失 250 ms 後回到待機值：雙臂為 -1（放下），肘與膝為 0。新手機工作階段開始校正及正常結束接收端時也會送出待機值；T 字校正完成仍送出全 0。這些時間不是端到端延遲；`--smoothing-ms`、`--hold-ms` 與 `--calibration-seconds` 可調整。

VRChat Desktop 已回傳六個 OSC 測試參數；使用者確認手臂、彎膝與 WASD 共存正常，先前彎膝走路滑行的問題已修正並在遊戲內重測。這些是以診斷工具直接送 OSC 測得，尚未驗證手機經 receiver 到 VRChat 的完整流程。這是六個單軸角度的最小測試，並非完整的 3D 全身追蹤。

### 單參數遊戲內診斷

套用本機測試 Avatar 並開啟 VRChat OSC 後，先停止 receiver，避免兩個程式同時改寫參數；例如在 `windows` 目錄執行：

~~~powershell
python -B osc_probe.py LeftArmRaise --value 1 --hold 5
~~~

腳本會先送待機值（雙臂 -1、其餘 0），再將所選參數維持 5 秒，最後送回待機值。依次將名稱換成 `RightArmRaise`、`LeftElbowFlex`、`RightElbowFlex`、`LeftKneeFlex`、`RightKneeFlex`，在 VRChat 畫面觀察各動作。也可同時指定多個參數，例如 `python -B osc_probe.py LeftArmRaise LeftElbowFlex --hold 10`，檢查同一隻手抬起並彎肘。上臂可另以 `--value 0` 測試 T 字平舉；本測試 Avatar 的肘與膝負值限制在伸直。腳本只會送往本機 `127.0.0.1:9000`；送出成功不代表遊戲已收到。

## 協定與量測

每個 UDP 封包是一份 UTF-8 JSON（version 1），含 session、遞增 seq、相機原始時間戳、手機分析開始／送出單調時間、處理時間及姿勢資料。偵測到人體時，normalized 與 world landmarks 均為 33 個；沒有人體時兩個陣列為空。每個點包含 x、y、z 和可用的 visibility／presence；數值以四位小數傳輸。不傳送相機影像。

Windows 驗證格式與數量、忽略舊序號，並以 session、seq 與手機送出時間回覆 ACK。手機以同一個 elapsedRealtimeNanos 時鐘測量發送到收到 ACK 的 application RTT，顯示最近最多 512 筆的 p50／p95。這包含最後 JSON 編碼、網路、Windows 接收／驗證／回覆及手機排程，**不是單程延遲**。Windows 自己的接收處理時間使用高精度 perf_counter_ns，不與手機時鐘相減。

相機原始時間戳的時間基準取決於裝置；除非確認相機的 timestamp source，不能直接與手機 elapsedRealtime 或 Windows 時鐘相減。所有數字也不包含 VRChat、相機曝光或螢幕顯示。

Windows 定期輸出收到／有效／無人體數、schema 錯誤、序號缺口、亂序、到達間隔、相鄰間隔抖動、接收處理時間及封包大小，也包含：

- `arrival_fps` 是有效封包的平均到達率；`pose_arrival_fps` 是依有效封包中人體比例估算的人體封包到達率。兩者都不是手機相機或辨識回呼 FPS。
- `pose_frame_pct` 是有效封包中帶人體結果的比例。`joint_confident_pct` 的分母是帶人體的有效封包，計算各關節的三個點信心是否達 0.5；它不驗證骨骼幾何或動作正確性。
- `phone_processing_p50_ms`／`phone_processing_p95_ms` 來自所接收人體封包的 `inferenceMs`。App 正常提供分析開始到結果擷取完成的合計；分段計時不可用時使用 App 的備援估計。它不是純模型推論時間或人體到 Avatar 的延遲。百分位最多使用最近 10,000 筆樣本。
- `udp_resets` 計數 Windows 回報先前 ACK 的 UDP 連接重設；`oversized` 計數過大的資料報。接收端遇到這兩種狀況後繼續監聽。

序號缺口是估計值：第一個收到封包之前及最後一個之後的損失無法得知；手機在傳送前覆蓋過期影格則另列，不算網路丟包。接收端不寫入照片或姿勢資料。

啟用 OSC 時，`pose_to_osc_p50_ms`／`pose_to_osc_p95_ms` 記錄 Windows 收到人體封包後到本機 OSC 傳送呼叫結束的時間，只計校正已完成且有 OSC 送出的封包；其中仍可能包含低信心後回到待機值的更新。這包含驗證、ACK 與姿勢轉換，但不包含 Wi-Fi 單程、VRChat 收取或渲染；校正與終端機輸出可能影響少數樣本。`osc_updates` 是本機傳送呼叫數，並非 VRChat 確認收到的數量。

協定沒有加密或驗證，只適合可信任的私人 LAN；--allow-sender 僅限制來源 IP，不是身分驗證。

## 測試

~~~powershell
python -B -m unittest discover -v
python -B soak_loopback.py --duration 600 --fps 15
~~~

`soak_loopback.py` 只使用 `127.0.0.1`、隨機本機 UDP 埠及合成姿勢，檢查 receiver、ACK、校正和 OSC 編碼；不會傳送到 VRChat。其結果不能代表實際手機、Wi-Fi 或遊戲的穩定性。

## 實機 10 分鐘測試準備

1. 使用新建置的 Android debug APK 更新手機；詳見 `android/README.md`。固定手機、確定全身入鏡，手機與電腦連同一個可信任的私人 LAN，VRChat Desktop 套用本機 Robot 並開啟 OSC。
2. 在電腦執行 `ipconfig`，以目前連線介面的私人 IPv4 取代下面範例。若要保留紀錄，在 `windows` 目錄執行：

   ~~~powershell
   New-Item -ItemType Directory -Force .\captures | Out-Null
   $receiverIp = '192.168.137.1'
   python -B -u pose_receiver.py --bind $receiverIp --port 8765 --osc --duration 660 --report-interval 30 | Tee-Object -FilePath .\captures\receiver-run.log
   ~~~

3. 開啟接收端後盡快在手機填入相同 IP／埠並開始傳送；確認 ACK，保持 T 字姿勢至校正完成，再觀察六個動作與 WASD。660 秒包含啟動與校正時間，不自動保證有滿 10 分鐘的有效姿勢；需確認實際連續時間。
4. 手機 FPS、ACK RTT、遺失與溫度紀錄方式見 `android/README.md`。彙整 Windows 的 `FINAL`，並記下是否一直前景運行、方向是否正確及是否發熱／降頻。以額外錄影裝置逐格量測前，不報告人體到螢幕的端到端延遲。

`captures` 已由 Git 忽略，日誌不含相機影像或 landmark 座標，但可能包含私人網路位址；請自行保留於可信任的電腦。

## Phase 0：原生 OSC Tracker 探針

**VR 模式 Phase 0 已通過**：AnyaDance 自帶 SteamVR trackers 停用後，`tracker_probe.py` 送出的合成髖與雙腳完成校正、本機動作與私人房間遠端盲測。這不等於手機姿勢已接入。結果見 [OSC Tracker MVP 計畫](../OSC_TRACKER_MVP_PLAN.md)，必要時重做的指令見 [探針操作](TRACKER_PHASE0.md)。

## Phase 1：TrackerOutput 元件

`tracker_output.py` 提供 OSC Vector3 編碼與只送到本機的 `TrackerOutput`。呼叫端必須提供已校正的公尺位置、Euler 旋轉，以及 `hip`、`left_foot`、`right_foot` 對應的相異 tracker ID（1–8）；當次 VRChat 校正可能把 3／4 對調。元件只送出有提供的角色，傳入無效資料時整批不送。`tracker_probe.py` 已共用此編碼器；loopback 測試覆蓋對調映射及資料格式。

目前 `pose_receiver.py` **未使用** `TrackerOutput`，仍只在 `--osc` 下輸出六個 Avatar 參數；請勿把這個元件當作手機 FBT 完成。

## 手機 tracker 座標校正基礎（離線）

`tracker_pose.py` 接受已驗證格式的 MediaPipe 封包，但只回傳三個 `TrackerTransform`，**不送 OSC**。建立 `TrackerCalibrationConfig` 時，必須提供實測站姿髖高（地面至左右髖中點，公尺）、初始 yaw、是否鏡像，以及前向符號。Android 目前把前鏡頭影格鏡像後送進 MediaPipe，因此 `mirrored_input=True` 是程式路徑的設定；仍須以真實影格確認左右與前後方向。前向符號若與站姿腳尖方向不符，校正會失敗。

站姿需雙腳著地並保持方向約 3 秒。校正以 MediaPipe hip-centred world landmarks 建立右、上、前軸，按實測髖高定尺度；腳底由 heel／foot index 估計。每幀以較低的腳底點估計地面；腳 tracker 放在 ankle，旋轉只估 yaw，pitch／roll 固定為零。單手機 world landmarks 沒有房間平移，所以髖的水平位置固定為原點；雙腳同時離地無法與蹲下可靠區分。這些限制與地面估計都待真實手機資料驗證。

任一必要點低於信心門檻或無姿勢時，該幀不產生任何 tracker transform；超過 250 ms 沒有完整有效影格，校正作廢。停止產生資料不保證 VRChat 立刻清除最後一幀；接入 receiver 前須另外驗證遊戲的失追行為。測試：在 `windows` 執行 `python -B -m unittest discover -v`。

### 真手機離線預覽

`tracker_preview.py` 會沿用 receiver 的封包驗證、來源限制及 ACK，只在終端機顯示校正進度與三個 tracker 的推算公尺位置／yaw，**不建立 OSC 輸出**。它不記錄原始 landmark 或影像。`--hip-height` 是實測站姿髖高，不是總身高；`--forward-sign` 須以實際腳尖方向選擇。先用 `--yaw 0` 檢查相對方向，絕對 HMD 對齊仍待驗證。

在 `windows` 目錄執行，將範例 PC／手機 IP 與髖高換成當前實際值，並讓兩者位於可互通的私人網路：

~~~powershell
python -B tracker_preview.py --bind 192.168.137.1 --allow-sender 192.168.137.189 --port 8765 --hip-height 0.90 --mirror yes --forward-sign 1 --duration 60
~~~

啟動後才在手機 App 輸入相同的 PC IP 與 UDP 埠、按「開始傳送」，確認 ACK；站立約 3 秒後依序抬左腳、放下、抬右腳、放下、蹲下、轉身。`PREVIEW_TRACKERS` 應顯示對應腳高度上升、蹲下時髖降低、轉身時 yaw 改變。`PREVIEW_WAIT` 表示校正或追蹤暫停；`PREVIEW_LOST` 表示須重新站姿校正。若始終無法校正，可再以另一個 `--forward-sign` 做獨立的離線診斷，並記下哪個方向符合真人動作。此預覽不能證明 VRChat IK、FBT 或遠端同步。
