# AnyaDance 操作參考（v0.0.6）

本專案在 [Phase 0 虛擬 HMD 驗證](VIRTUAL_HMD_PHASE0_PLAN.md) 使用 AnyaDance 提供虛擬 SteamVR 裝置。本文件整理 AnyaDance v0.0.6 `AnyaDance.exe` 的**所有操作**，資料來源為官方 `README.zh-CN.md` 與 v0.0.6 原始碼（`src/ui/input.cpp`）。

> AnyaDance 是外部工具，位於 `E:\10_DevTool\AnyaDance-v0.0.6\anyadance`。其自帶的三個 SteamVR tracker 不等於本專案 OSC Tracker 成功；兩者須分開驗證。

---

## 0. 最重要的一條規則

**鍵盤與滑鼠操作只有在 AnyaDance 視窗是「焦點視窗」時才生效。**

- 原始碼 `input.cpp` 以 `GetForegroundWindow() == AnyaDance視窗` 判斷；一旦失焦，會呼叫 `HandleFocusLost()`，**放開所有按住的按鍵與扳機**。
- 60 Hz 的姿勢 UDP 串流**不受影響**：視窗最小化或失焦時仍持續推送六個裝置的姿勢。只有「按鍵輸入邊緣」需要焦點。
- **後果**：做 VRChat FBT 校正時，若你去點 VRChat 的 Headset Window，AnyaDance 一失焦就把扳機放掉，校正不會觸發。全程讓 AnyaDance 保持焦點，眼睛看 Headset Window。

---

## 1. 六個虛擬裝置

驅動透過 `127.0.0.1:39570` 的 UDP JSON 接收姿勢，向 VRChat 提供六個裝置：

| 裝置 | 說明 |
|---|---|
| HMD（頭顯） | 唯一有 `0 m` 地面下限的裝置 |
| 左控制器 | |
| 右控制器 | |
| 髖部 tracker | |
| 左腳 tracker | |
| 右腳 tracker | |

- `AnyaDance.exe` 一打開就以 **60 Hz** 推送六裝置 T 姿勢；目前 Phase 0 OSC 隔離測試已把 SteamVR 的 `driver_anyadance.enable_trackers` 設為 `false`，因此驅動只註冊 HMD 與左右控制器。原設定已備份，詳見 [虛擬 HMD Phase 0 計畫](VIRTUAL_HMD_PHASE0_PLAN.md)。
- 封包停止後，SteamVR 仍看到各裝置停在最後姿勢，保持連線、有效、`TrackingResult_Running_OK`。
- 正常退出時送出一幀中性輸入。

---

## 2. 鍵盤操作（控制器按鍵）

| 鍵 | 對應 | 典型 VRChat 用途 |
|---|---|---|
| `W` `A` `S` `D` | 左搖桿移動 | 角色前後左右走 |
| `Q` / `E` | 右搖桿轉向 | 左轉 / 右轉 |
| `Space` | 按住＝右 A | 跳躍 |
| `M` | 按住＝右 B | 開右手快速選單 |
| `V` | 按住＝左 A | 語音（push-to-talk） |
| `Z` | 按住＝**左扳機** | 選取 / 校正確認 |
| `X` | 按住＝**右扳機** | 選取 / 校正確認 |
| `R`（獨立實驗版） | 右搖桿按下 | 2026-11-05 遊戲內測試沒有反應；不可當作可用操作 |

**FBT 校正「同時扣兩扳機」＝同時按住 `Z` + `X`。**（AnyaDance 必須在焦點）

### VRChat 選單（重要限制）

| 選單 | 怎麼開 |
|---|---|
| 快速選單（Quick Menu） | `M`（右 B）。**Calibrate FBT 在這裡。** |
| 動作選單（Action Menu） | VRChat 預設綁「按壓搖桿」。AnyaDance v0.0.6 原版打不開；獨立 `R` 實驗版也未在 VRChat 打開 |

- AnyaDance v0.0.6 原版驅動（`virtual_device.cpp:940-961`）只建立搖桿 `x`/`y` 軸，**沒有 `thumbstick/click`、`trackpad/click` 元件**，送不出搖桿按壓。
- `application_menu/click` 元件存在，但 AnyaDance 沒有鍵對應它（`input.cpp` 綁定表只有 WASD/QE/Space/M/V/Z/X）。
- 2026-11-05 獨立測試版加入 `R → right.system_click → /input/thumbstick/click`。AnyaDance 自帶測試 1/1 通過；使用者截圖顯示多次 `R down/up` 皆為 `Sent`，SteamVR 讀取了 `joystick::click` 綁定，但 VRChat 圓形選單**沒有反應**。因此只證明 UI 送出及綁定存在，不能判定 VRChat 收到或按鍵可用。測試後已還原原版 exe、DLL、控制器 profile，三個檔案皆經雜湊核對；備份位於 `E:\10_DevTool\AnyaDance-before-thumbstick-20261105`。可重建的差異見 [補丁](patches/anyadance-v0.0.6-r-action-menu.patch)；此補丁未完成遊戲內驗收。

---

## 3. 滑鼠操作（六個裝置方框）

身體面板上有六個裝置方框，拖拽即可擺姿勢。方框隨 UI 視窗縮放。

### HMD 方框
| 操作 | 效果 |
|---|---|
| 左鍵拖拽 | 旋轉頭顯 |
| 右鍵拖拽 | 垂直（Y）移動 |
| 左鍵＋右鍵 | 同樣的垂直移動手勢 |

### 其他五個裝置（控制器 / 髖 / 雙腳）
| 操作 | 效果 |
|---|---|
| 左鍵拖拽 | 本地 X/Y 平移 |
| 中鍵拖拽 | 旋轉 |
| **左鍵＋右鍵一起拖拽** | 深度（Z）移動 |
| 中鍵＋右鍵一起拖拽 | 橫滾（roll） |

> **注意：這五個裝置「單獨右鍵拖拽」不會有反應。** 原始碼 `panel_body.cpp:58-61`：純右鍵只對 HMD 方框生效；對其他裝置右鍵僅作為組合鍵修飾。深度移動必須左鍵＋右鍵一起按住拖拽。

### 位置限制
- 所有裝置 Y 上限 `25 m`。
- 只有 HMD 有 `0 m` 下限（低於地面會讓視角進地下）。
- 其餘五個裝置可低於地面到 `-30 m`（腳穿過地板、髖做地板動作）。

### 座標系切換
- **HMD / Global 單選鈕**：決定操控用「頭顯偏航基準」還是「固定世界軸」。
- **手部對稱 / 腳部對稱 核取方塊**：成對鏡像。HMD 模式對頭顯偏航的 YZ 平面對稱；Global 模式以頭顯位置為中心、按世界軸對稱。

---

## 4. 手指與抓取

| 操作 | 效果 |
|---|---|
| 滾輪 | 同時開合雙手所有手指 |
| 按住數字鍵＋滾輪 | 單獨彎曲一根手指 |
| 握成完整拳頭 | 觸發該手 grip（抓取）；鬆開任一指即釋放 |

數字鍵對應（每指鉗制在 `[0,1]`）：

- `1`–`5`：左手，小指 → 拇指
- `6`–`0`：右手，拇指 → 小指
- 即 `5`/`6` 為拇指，`1`/`0` 為小指。
- 往同方向滾到底可把所有手指重置為全張或全握。

---

## 5. 身體面板空白處（全身操控 + 右搖桿）

在身體面板「空白處」（非裝置方框）拖拽：

| 操作 | 效果 |
|---|---|
| 左鍵拖拽 | 等同右搖桿：按下點為中心，各軸偏移 ±1，放開回中位（配合 `M` 操作右手快速選單） |
| 中鍵拖拽 | 以頭顯位置為軸心旋轉全部六裝置（偏航 / 俯仰） |
| 中鍵＋右鍵拖拽 | 繞同一軸心橫滾（roll） |
| 右鍵拖拽 | 保持身體形狀整體垂直移動，向下在頭顯觸及 `0 m` 處停止 |

全身旋轉與單裝置手勢共用同一個 HMD / Global 座標系設定。

---

## 6. UI 按鈕與面板

| 按鈕 / 控制項 | 功能 |
|---|---|
| **註冊驅動** | 把所在資料夾註冊為 SteamVR 驅動，啟用全虛擬裝置組；寫入前先備份 `steamvr.vrsettings` 到 `%LOCALAPPDATA%\AnyaDance\steamvr.vrsettings.backup` |
| **取消註冊驅動** | 還原 SteamVR 設定備份、恢復真實裝置追蹤 |
| **重啟 SteamVR** | 以全虛擬模式重啟 SteamVR |
| **舞蹈 (MMD)** | 選 `.vmd` 動作 + `.pmx`/`.pmd` 模型，經 Blender + MMD Tools 解算後以 60 Hz 推送到六裝置 |
| **高級** | 指定 Blender / MMD Tools 自訂安裝路徑（會記住） |
| **保存姿勢 / 加載姿勢** | 擷取 / 恢復目前姿勢為 `.nya` 片段 |
| **保存 .nya / 加載 .nya**（舞蹈對話框） | 存已解算舞蹈 / 直接重播（跳過 Blender 解算，瞬間播放） |
| **視窗置頂** | 固定視窗在最上層（會記住） |
| **監視驅動命令** | 開關驅動命令多播日誌（預設關，會記住） |
| 語言 | 英文 / 簡體中文 / 日文 |

UDP 日誌（永遠英文）每行可：**複製**（原始請求體）、**複製重發命令**（可直接執行的 PowerShell UDP 單行）、**重新發送**。

---

## 7. 驅動註冊與解析度設定

### 註冊 / 取消註冊腳本（`scripts\`）
```powershell
.\scripts\register_driver.ps1      # 註冊 + 套用全虛擬設定 + 備份
.\scripts\restart_steamvr.ps1      # 重啟 SteamVR
.\scripts\uninstall.ps1            # 取消註冊 + 還原備份 + 重啟
.\scripts\listen_driver_log.ps1    # 參考用驅動命令監聽器
```
更改註冊或重建 DLL 後**必須重啟 SteamVR**。

### HMD 渲染解析度
虛擬頭顯預設每眼 `1920x1080`。在 `<Steam>\config\steamvr.vrsettings` 的 `driver_anyadance` 小節覆寫：
```json
"driver_anyadance": {
    "headset_render_width": 3840,
    "headset_render_height": 2160
}
```
GPU 渲染時間約按縮放倍數平方成長（4K ≈ 1080p 的四倍）。同一小節另有桌面鏡像視窗設定：`headset_window_width`、`headset_window_height`、`headset_window_eye_mode`、`headset_window_preserve_aspect`。

> 本專案目前把 `headset_window_width/height` 設為 **2560×1440**（使用者要求保留），與 `-202` 是否解除無關。詳見 [VIRTUAL_HMD_PHASE0_PLAN.md](VIRTUAL_HMD_PHASE0_PLAN.md)。

---

## 8. 本專案 FBT 校正會用到的操作（實務對照）

1. 讓 AnyaDance 保持焦點視窗（見 §0）。
2. 用 `M`（右 B）開 VRChat 快速選單，找到 Calibrate FBT。
3. 觸發校正後，Avatar 凍結成 T 字並出現校正球。
4. **同時按住 `Z` + `X`**（左右扳機）鎖定校正。
5. 需要時用滑鼠在裝置方框調整髖 / 雙腳位置，讓校正球貼合 Avatar 身體比例。

> 已證實：2026-11-05 使用者完成 AnyaDance tracker 的 FBT 校正，拖動髖／腳方框後，本機 Avatar 下半身跟著動。目前已暫停註冊這三個 SteamVR tracker，以便隔離驗證 OSC；OSC 驅動本機動作與遠端同步仍待驗證。Phase 0 通過標準見 [VIRTUAL_HMD_PHASE0_PLAN.md](VIRTUAL_HMD_PHASE0_PLAN.md)。

---

## 9. 安全與存活行為

- 六裝置以中性姿勢開始，保持連線且有效。
- UI 序列化前鉗制位置，驅動收到封包後再次鉗制（`±30 m`、HMD `0 m` 下限、手指 `[0,1]`）。
- 封包停止後裝置停在最後姿勢，仍回報 `TrackingResult_Running_OK`。

---

## 10. 參考

- 官方 README：`E:\10_DevTool\AnyaDance-v0.0.6\anyadance\README.zh-CN.md`
- 原始碼鍵位邏輯：`E:\10_DevTool\AnyaDance-source-v0.0.6\src\ui\input.cpp`
- 專案 Phase 0 計畫：[VIRTUAL_HMD_PHASE0_PLAN.md](VIRTUAL_HMD_PHASE0_PLAN.md)
- 免責：虛擬裝置輸入連線遊戲有帳號風險（AnyaDance DISCLAIMER）；本文件僅整理操作，不改變該風險。
