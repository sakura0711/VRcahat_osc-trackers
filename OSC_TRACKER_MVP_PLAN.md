# VRChat 原生 OSC Tracker MVP：參考與實作計畫

**狀態：規劃草案（2026-11-04，Asia/Taipei）**  
**本文件目的：** 將產品主線從「特定 Avatar 的 Animator 參數控制」調整為「由手機影像驅動 VRChat 原生 Tracker／全身 IK」，並保留現有參數模式作為可回退的自製 Avatar 進階功能。

## 1. 產品目標與重要前提

### 目標

玩家以一支 Android 手機拍攝全身動作；VRChat 使用原生 Tracking / IK 套用到目前穿著的正常 Avatar。另一位玩家在私人房間中應可看到 Avatar 的髖、雙腿、軀幹與手臂呈現明顯的全身姿勢，而非只見 Desktop 模式的人棍。

此路線不應要求購買 Avatar 的 Unity 原始檔，也不應要求為每個 Avatar 建立 Animator、Expression Parameters 或動畫曲線。

### 重要前提：Desktop 相容性尚未驗證

VRChat 官方與其社群 Tracker 範例將 OSC Tracker 校正描述為在 **VR 模式**進行；相關 Avatar 文件也將 Desktop 的頭／左右手，與 FBT 的頭／左右手／髖／雙腳區分。因此，不能把「沒有 HMD 的 VRChat Desktop」可直接使用原生 FBT 視為既成事實。

**本計畫的第 0 階段必須先驗證這件事。** 在未通過前，不停用現有的 Avatar Parameters 路線，也不宣稱 OSC Tracker 能解決純 Desktop 人棍問題。

## 2. 兩條輸出模式

```text
Android 手機相機
  → MediaPipe Pose Landmarker（33 landmarks）
  → 私人 Wi-Fi UDP JSON（不傳影像）
  → Windows receiver：驗證、統計、校正、濾波
  ├─ parameters 模式：六個 Avatar Parameters → Avatar Animator
  └─ trackers 模式：VRChat OSC Tracker transforms → 原生 IK
```

### `trackers`：新主線

- 送出每個追蹤點的世界座標（公尺）與 Euler 旋轉（度）。
- 由 VRChat 的原生 IK 求解 Avatar 骨架；不需修改 Avatar。
- 理想用途：能進入支援 FBT 的 VR 模式、又想穿著商店購買 Avatar 的玩家。
- 第一版以少量可信點優先：髖＋左右腳；品質足夠才依序加入胸、肘與膝。

### `parameters`：保留的次要模式

- 現有六個 `Puppet/*` Float parameters 驅動自訂 Animator。
- 適合擁有 Unity 原始檔的自製 Avatar，或需要刻意放大／風格化動作時。
- 可在 Desktop 進行既有的本機 Robot 測試；但不能自動套用至購買 Avatar。

## 3. OSC Tracker 協定契約

| 本專案暫定 ID／端點 | 人體對應 | MVP 優先順序 |
| --- | --- | --- |
| `1` | Hip | 必要 |
| `2` | Chest | 第二階段 |
| `3` / `4` | Left / Right Foot | 必要 |
| `5` / `6` | Left / Right Knee | 最後加入 |
| `7` / `8` | Left / Right Elbow | 第二階段 |
| `head`（特殊名稱，不是 ID 9） | 座標系與 yaw 對齊參考 | 建議 |

上表的 ID 對應是本專案的暫定慣例；官方文件列出 ID 1–8 及支援的人體部位，但未指定兩者的固定映射。實際配對須透過 VRChat 校正驗證。

每個一般 tracker 的端點為：

```text
/tracking/trackers/{1..8}/position  (float x, y, z；公尺)
/tracking/trackers/{1..8}/rotation  (float x, y, z；Euler 度，Z-X-Y 順序)
/tracking/trackers/head/position
/tracking/trackers/head/rotation
```

VRChat 文件指出：資料有誤差時，少送幾個 tracker 往往會得到較好的 IK 結果。座標系為 Unity 的左手系、+Y 向上；使用者真實身高與 VRChat 身高必須一致，否則腳部高度會錯位。

## 4. 現有成果如何沿用

| 現有模組 | Tracker 計畫中的角色 | 處理方式 |
| --- | --- | --- |
| Android CameraX + MediaPipe | 取得 33 個 landmarks | 保留 |
| Android LAN sender | 送出 landmark 封包 | 保留 |
| UDP schema、ACL、ACK、統計 | 安全與可靠性基礎 | 保留 |
| Windows receiver | 取得資料、記錄品質、選擇 output | 擴充 |
| `pose_control.py` | 六關節角度求解 | 保留為 `parameters` mode |
| Unity Robot / Animator | 本機回歸與特殊姿勢參考 | 不再是主線驗收 |
| OSC encoder | 已有 float OSC 基礎 | 擴充為 Vector3 / Tracker endpoints |

## 5. 執行階段與驗收

### Phase 0 — 可行性閘門：VRChat 模式（0.5–1 天）

**目的：** 先證實使用者實際的 VRChat 執行模式是否接受、校正並網路同步 OSC Tracker FBT。

1. 以獨立、可重複的 tracker probe 送出固定髖＋雙腳的標準 OSC 封包。
2. 分別在可用的 VR 執行模式與目前 Desktop 模式測試；記錄是否出現 tracker、能否執行 FBT calibration、Avatar 是否真的由 IK 帶動。
3. 在私人房間由第二位玩家觀察結果。

**通過標準：** 未修改的 Humanoid Avatar 可由固定測試 tracker 驅動，且遠端觀察者看得到髖／腿姿勢。

**決策：**

- 若 VR 模式通過：以 `trackers` 作為正式 MVP 主線。
- 若純 Desktop 不通過且使用者沒有可用 VR runtime：不得承諾「購買 Avatar 的全身 IK」；保留 `parameters` 為 Desktop fallback，另開立「官方支援的 VR runtime／虛擬追蹤來源」研究項目。

2026-11-04 實測已確認 Desktop 的 OSC Debug 收到探針封包，但 Avatar 未動且未完成 FBT 校正。無實體頭顯的 [虛擬 SteamVR Phase 0 計畫](VIRTUAL_HMD_PHASE0_PLAN.md) 是後續獨立驗證路線；虛擬驅動的 FBT 成功不能自動算作 OSC Tracker 路線通過。

### Phase 1 — Tracker 輸出基礎（0.5–1 天）

1. 建立 `TrackerOutput` 與 OSC Vector3 encoder，固定使用 VRChat 定義的 tracker slot。
2. 新增 `--output parameters|trackers` 命令列選項；預設仍為安全、不送 OSC 的模式。
3. 為 OSC 位址、型別、slot mapping、停止送出與超時行為加入單元測試及 loopback 測試。
4. 保持現有 parameters 測試全數通過。

**通過標準：** tracker OSC 封包可被獨立解析、探針能重現 Phase 0 結果。

### Phase 2 — 單手機姿勢到 tracker transforms（1–2 天）

1. 將 MediaPipe world landmarks 轉成以髖為根的公尺制骨架。
2. 實作站姿／T-pose 校正：身高、地面 Y、相機面向、左右鏡像、初始 yaw。
3. 優先求解 Hip、Left Foot、Right Foot 之位置與旋轉。
4. 針對低可信度、腳被遮擋、暫時失追採取 hold-last-valid、超時停送或退回安全姿勢；不得將雜訊當成可信 tracker。
5. 在 UI／終端機顯示每個 tracker 的信心、是否正在輸出、校正狀態與輸入 FPS。

**通過標準：** 使用者站立、轉身、蹲下、抬腳時，Avatar 下半身動作可辨識且腳不持續瞬移。

### Phase 3 — 自然度與可操作性（1–2 天）

1. 新增 Chest、Left Elbow、Right Elbow，僅在對應 landmark 品質達標時輸出。
2. 比較 EMA / One Euro filter、dead zone 與適度 prediction；分別量測抖動與操作延遲。
3. 建立 3、5、8 tracker profile，讓使用者在「穩定」與「表現完整」間選擇。
4. 加入簡潔校正流程：相機擺放提示、全身入鏡檢查、身高設定、T-pose countdown、重新校正按鈕。

**通過標準：** 頭、手、髖與腳在畫面內時，Avatar 全身姿勢不再呈現典型 Desktop 人棍；短暫遮擋不造成明顯爆轉或左右互換。

### Phase 4 — 遠端與穩定性驗收（1–2 天）

1. 私人房間、另一位玩家觀看未修改的購買 Avatar。
2. 逐項測試站立、雙手抬高、轉身、蹲下、左右抬腳、短暫遮擋與重新校正。
3. 完成 10 分鐘實機測試，記錄手機 FPS / inference、封包遺失與 jitter、receiver 處理時間、tracker 有效率與使用者主觀延遲。
4. 明確區分「本機鏡子看起來有動」與「遠端玩家確實看到同步動作」。

**通過標準：** 遠端玩家能辨識連續的全身姿勢改變；沒有無法恢復的漂移、長時間卡住或高頻腳部瞬移。

## 6. MVP 不包含

- 不承諾無頭顯 Desktop 可啟用原生 FBT；先以 Phase 0 證實。
- 不模擬、注入或修改 VRChat 客戶端；僅使用官方 OSC Tracker 介面。
- 不宣稱單鏡頭可提供精準的房間世界深度、快速前後移動或完美足部旋轉。
- 不做手指、手部位置、臉部追蹤、完整頭顯追蹤或精確舞蹈 mocap。
- 不將第二支手機列為第一版前提；僅在單鏡頭深度失敗時升級。
- 不為商店購買 Avatar 修改 Unity 專案。

## 7. 主要風險與緩解方式

| 風險 | 影響 | 緩解／決策 |
| --- | --- | --- |
| Desktop mode 不接受 FBT calibration | 無法達成購買 Avatar 全身 IK 目標 | Phase 0 先驗證；不通過即停止 tracker MVP 擴張 |
| 單鏡頭 Z 深度歧義 | 前後移動、轉側身、腳部位置不穩 | 先少量 tracker；固定相機與身高；必要時第二鏡頭 |
| Avatar 比例／Humanoid mapping 特殊 | IK 姿勢不自然 | 用多種公開／購買 Avatar 實測；不修改模型作為解法 |
| 人體被家具或手臂遮擋 | tracker 跳動或左右交換 | 信心閾值、hold-last-valid、超時停送、recalibrate |
| 平滑過強 | 動作延遲高 | 以延遲與 jitter 同時量測，提供 profile |
| 遠端同步不如本機鏡子 | 最終體驗差 | Phase 4 由第二位玩家驗收，不以本機結果代替 |

## 8. 參考專案與採用原則

| 專案 | 可借鏡內容 | 授權／成熟度 | 採用原則 |
| --- | --- | --- | --- |
| [VRChat OSC Trackers](https://docs.vrchat.com/docs/osc-trackers) | 官方端點、座標、校正與 tracker 數量 | 官方規格 | 唯一協定依據 |
| [vrchat-community/vrc-oscquery-lib](https://github.com/vrchat-community/vrc-oscquery-lib) | Tracker sender／receiver、校正測試流程 | VRChat 社群範例 | 可作協定測試參考 |
| [4firas/Fever](https://github.com/4firas/Fever) | metric hip-rooted skeleton、One Euro、upsampling、head anchor、測試拆分 | MIT；macOS / Swift | 參考演算法與模組邊界，不移植平台 UI |
| [ju1ce/Mediapipe-VR-Fullbody-Tracking](https://github.com/ju1ce/Mediapipe-VR-Fullbody-Tracking) | 單鏡頭 MediaPipe、校正與 VRChat OSC backend 的實務限制 | MIT；社群使用較多，但程式較舊 | 參考失敗情境與設定，不直接取代現有 Android App |
| [francesco-gallo/vr-body-tracker](https://github.com/francesco-gallo/vr-body-tracker) | Android、MediaPipe、height / offsets / overlay / OSC Tracker mapping | 未見標準 OSS 授權；作者標示多數由 AI 產生 | 僅參考產品與測試設計，禁止直接複製 |
| [LAGkitty/VRBody](https://github.com/LAGkitty/VRBody-Phone-Full-Body-Tracker-for-VRChat) | Phone → PC → OSC 的使用流程 | 未見清楚 OSS 授權 | 僅比較流程與 UI |
| [VerTicAl-HorIzoNs/PoseMesh](https://github.com/VerTicAl-HorIzoNs/PoseMesh) | 正面＋側面相機融合深度 | 小型實驗專案 | 作為第二手機／雙鏡頭升級參考 |

## 9. Git 與交付策略

基線與分支已建立；本次工作在 `feat/osc-trackers`，`master` 保留既有六參數 MVP：

```text
master（現有六參數 MVP 基線）
└─ feat/osc-trackers（新 Tracker 輸出與驗證）
```

每個 Phase 完成後都要保留可測試成果；Tracker branch 未通過 Phase 0 前，不修改或刪除現有 Animator 資產。最終產品應保留 `parameters` 與 `trackers` 兩個 output profile，而不是以其中一方覆寫另一方。

## 10. 下一步

1. 決定使用者是否具備可進入 VR 模式的環境（PCVR 或 Quest 等），並執行 Phase 0。
2. 在 `feat/osc-trackers` 完成探針與實機紀錄；Phase 0 通過後才繼續 tracker 輸出。
3. 以 [Phase 0 實測步驟](windows/TRACKER_PHASE0.md) 檢查無影像依賴的 tracker probe 與遠端可見性，再接上手機 landmark。
4. 以 3-tracker（Hip + Feet）達成遠端可見的基本全身姿勢後，才擴充至 5 或 8 tracker。
