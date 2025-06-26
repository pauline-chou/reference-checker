# 📚 Reference Checker

Reference Checker 是一個簡單實用的工具，可自動從 Word 檔（`.docx`）中擷取參考文獻標題，並透過**Crossref API** 、 **Scopus API** 與 **SerpAPI** 進行查詢，協助研究者快速判斷參考資料的正確性與可查詢性。

本專案全程採用 **vibe coding** 開發方式

⚠️ 注意事項
為節省比對時間，本系統僅查核具有 DOI 的期刊論文，不會檢查期刊名稱、作者、卷期或頁碼，比對僅以「篇名」為主。本系統提供之比對結果僅供初步參考，建議使用者在比對後仍應進行人工確認。請勿將本系統結果作為學術倫理判斷之唯一依據。

---

主要功能：
- 自動擷取 APA 或 IEEE 格式的文獻標題
- 若參考文獻中有 DOI，則直接比對Crossref，優先採用
- 優先查詢 Scopus API，若無結果再查 SerpAPI
- 根據查詢結果自動分類為「Crossref 有 DOI 資訊」「標題命中（Scopus）」「標題命中（Google Scholar）」「Google Scholar 類似標題」「均無結果」
- 提供結果視覺化、分頁顯示，方便使用者人工確認
- 支援結果下載為 CSV 檔案

