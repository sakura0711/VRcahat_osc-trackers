# 文件架構與規範

本專案文件依「類別」分層。新增或修改文件前先讀本頁。

## 資料夾職責

| 位置 | 放什麼 | 不放什麼 |
| --- | --- | --- |
| `README.md`（根） | 目標一句話 + 導覽連結 | 狀態細節、實驗數據 |
| `docs/STATUS.md` | **唯一**「目前狀態 / 已證實 vs 待驗證」 | — |
| `docs/PLAN.md` | 主線、邊界、OSC 契約、程式模組、Phase 定義 | 實驗數據、逐輪結果 |
| `docs/logs/` | 有日期的調查與測試紀錄 | 操作步驟、計畫 |
| `docs/logs/evidence/` | 衍生數據 JSON | — |
| `reference/` | 穩定參考（`anyadance-controls.md`、`steamvr-202.md`） | 會過期的狀態 |
| `windows/`、`android/` | 各平台操作指南（怎麼跑） | 狀態、實驗結論 |

## 規範

1. **一檔一類別**：計畫 / 狀態 / 操作 / 紀錄 / 參考 不混寫在同一個檔。
2. **狀態只有一份**：只寫在 `docs/STATUS.md`；其他檔要提狀態就用一行連結指過去，不複製。
3. **新實驗或排查** → 在 `docs/logs/` 新增 `YYYY-MM-DD-主題.md`，不要塞進 `PLAN.md` 或操作指南。
4. **操作指南**（`windows/`、`android/`）只寫執行步驟與參數，結果連到 `docs/logs/`。
5. **用語分清**「已證實」與「待驗證」；不得把 UDP 送出、loopback ACK 當成 VRChat 已接收或遠端同步。
6. **搬檔保留歷史**：先 `git mv`（純移動單獨一個 commit），再於下一個 commit 改內容與連結。
7. 內部連結用相對路徑；搬檔後用 `grep -rn "](.*\.md" --include=*.md` 檢查沒有斷連。
