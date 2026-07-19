# 🚀 McLeod Research Engine v1.0 - QUICK REFERENCE GUIDE

> Canonical quick reference. Historical research summaries are archived under `archive/2026-07-18_cleanup/docs_research/`.

## **Command Reference**

### **1. Run Research Engine Only**
```bash
cd "/Users/mason/Library/CloudStorage/Dropbox/McLeod Capital/McLeod Alpha"
./venv/bin/python3 engine/research_engine.py
```
**Output:** `data/mcleod_research_latest.json` + `data/mcleod_research_latest.csv`  
**Runtime:** ~1.5 seconds

### **2. Run Portfolio Engine (with Research Integration)**
```bash
cd "/Users/mason/Library/CloudStorage/Dropbox/McLeod Capital/McLeod Alpha"
./venv/bin/python3 engine/portfolio_engine.py
```
**Output:** Rankings CSV, EIPV CSV, Target Weights CSV  
**Runtime:** ~1.0 seconds  
**Note:** Reads `data/mcleod_research_latest.json` if available

### **3. Generate Morning Report**
```bash
cd "/Users/mason/Library/CloudStorage/Dropbox/McLeod Capital/McLeod Alpha"
./venv/bin/python3 reports/morning_cio_report.py
```
**Output:** `reports/morning_cio_report_latest.md`  
**Runtime:** ~0.5 seconds

### **4. Run Complete Workflow (Recommended)**
```bash
cd "/Users/mason/Library/CloudStorage/Dropbox/McLeod Capital/McLeod Alpha"
./venv/bin/python3 run_portfolio_engine_full.py
```
**Output:** All files (sync + research + rankings + report)  
**Runtime:** ~3.0 seconds

### **5. Sync Schwab Positions First (Optional)**
```bash
cd "/Users/mason/Library/CloudStorage/Dropbox/McLeod Capital/McLeod Alpha"
./venv/bin/python3 portfolio_sync.py
```
**Output:** `data/schwab_portfolio_latest.json`, `data/schwab_positions_latest.csv`  
**Runtime:** ~1 second

---

## **Data Files**

### **Input Files** (must exist)
- `data/schwab_portfolio_latest.json` - Portfolio from Schwab API
- `data/schwab_positions_latest.csv` - Positions list
- `config/mcleod_core_metrics.json` - Metrics definitions

### **Output Files** (auto-generated)

**Research Outputs:**
- `data/mcleod_research_latest.json` - Full research with metadata (74 KB)
- `data/mcleod_research_latest.csv` - Flattened research data (20 KB)

**Portfolio Rankings:**
- `data/mcleod_core_rankings_latest.csv` - Core rankings (currently empty - holdings blocked)
- `data/eipv_rankings_latest.csv` - EIPV allocation recommendations
- `data/target_weights_latest.csv` - Target rebalancing weights

**Reports:**
- `reports/morning_cio_report_latest.md` - Daily morning report

---

## **Current Data State**

### **Quick Status Check**
```bash
# Check latest research timestamp
head -5 data/mcleod_research_latest.json | grep timestamp

# Check holdings count
tail -1 data/mcleod_research_latest.csv | wc -c

# Check data quality score
grep data_quality_score data/mcleod_research_latest.csv | head -2
```

### **Portfolio Snapshot**
```
Total Value:        $175,987.11
Equity Value:       $103,430.20 (58.8%)
Positions:          20 equities + 2 options
Health Score:       100.0/100
Margin Efficiency:  43.3%
```

### **Research Status**
```
Holdings Researched:     20
Metrics Populated:       4/26 (15.4%) 
  - thesis_health ✅
  - liquidity_score ✅
  - margin_requirement ✅
  - data_quality_score ✅

NEEDS_RESEARCH:          22/26 (84.6%)
  - All fundamental metrics (14)
  - All frameworks (4)
  - All IBD fields (3)
  - McLeod Composite (1)

Rankings Status:
  Available:        0/20 (0%)
  Blocked:          20/20 (100%)
  Block Reason:     11.5% quality < 60% required
```

---

## **How to Populate Research**

### **Quick Start (5 Holdings, One Metric Each)**
```python
# Edit data/mcleod_research_latest.json
# For each of top 5 holdings (MU, MELI, AMZN, NBIS, CRWD):
# 1. Change "business_quality" from "NEEDS_RESEARCH" to 0-100 score
# 2. Set "business_quality_source" to "manual_research"
# 3. Set "business_quality_confidence" to 50-100
# 4. Re-run portfolio_engine.py to see impact

# If 1 metric per holding: 5/26 = 19.2% (still blocked)
# Need 15+ metrics per holding to reach 60% threshold
```

### **Via JSON Edit**
```json
{
  "symbol": "MU",
  "business_quality": 72,
  "business_quality_source": "manual_research",
  "business_quality_confidence": 85,
  // ... update other metrics
}
```

### **Via CSV Upload (Future)**
Once fundamentals researched, can bulk-update CSV and reimport:
```bash
# 1. Edit data/mcleod_research_latest.csv with research data
# 2. Convert CSV back to JSON (via research_engine or manual script)
# 3. Re-run portfolio_engine.py
```

---

## **Expected Output Samples**

### **Research Summary (from engine output)**
```
🔬 Researching 20 holdings...
  ✓ 5/20 holdings researched
  ✓ 10/20 holdings researched
  ✓ 15/20 holdings researched
  ✓ 20/20 holdings researched

📊 RESEARCH ENGINE SUMMARY
📈 HOLDINGS RESEARCHED
  Total: 20
  Equities: 20

📋 METRICS POPULATED
  Total Metric Slots: 520
  Populated: 80 (15.4%)
  NEEDS_RESEARCH: 440

🚫 HOLDINGS BLOCKED FROM RANKING
  Count: 20/20
  Reason: Data quality 11.5% < 60% required
```

### **Portfolio Engine Output (with Research)**
```
✓ Loaded portfolio: 22 positions (20 equities, 2 options)
✓ Loaded research data: 20 holdings with research metrics

📈 Running McLeod Core Rankings analysis...
  🚫 20 holdings blocked from ranking:
    RKLB - Insufficient data quality (11.5% < 60%)
    ARTV - Insufficient data quality (11.5% < 60%)
    ... (all 20 holdings blocked)

💰 Running EIPV analysis (best $1,000 allocation)...
  ✓ Top destination for next $1,000:
    AGX (EIPV: 1.87, new weight: 6.30%)
```

### **Morning Report Section (Research Gaps)**
```
## 📋 Data Quality & Research Gaps

⚠️ **The following fields require manual research:**
- Business Quality scores
- Expected Alpha estimates
- Valuation metrics
- 2-year CAGR projections
- ... (22 total NEEDS_RESEARCH fields)

**Current Status:** 4/26 metrics populated (15.4%)
**Required for Ranking:** 15+/26 metrics (60%+)
**Gap:** 11+ metrics per holding
```

---

## **Troubleshooting**

### **"No rankings to save" - Empty rankings CSV**
✅ **Expected behavior** - Holdings blocked due to insufficient research data
- Check: `data/mcleod_research_latest.json` exists?
- Check: Data quality < 60%?
- Check: Holdings listed as blocked in engine output?

### **"Research data not found" - Warning message**
✅ **Expected on first run** - Run `research_engine.py` first
```bash
./venv/bin/python3 engine/research_engine.py  # First
./venv/bin/python3 engine/portfolio_engine.py # Then
```

### **EIPV rankings empty**
❌ **Problem** - Check portfolio_sync.py ran successfully
```bash
./venv/bin/python3 portfolio_sync.py
./venv/bin/python3 engine/portfolio_engine.py
```

### **"20 holdings blocked" message**
✅ **Expected** - This is working as designed
- Need to populate research metrics to unblock
- 60% data quality threshold prevents low-confidence rankings

---

## **Key Thresholds & Constants**

```python
# Data quality threshold for ranking
MIN_DATA_QUALITY_FOR_RANKING = 60%  # Holdings < 60% quality blocked

# SPCX protection
EXCLUDE_FROM_REPLACEMENT = {"SPCX"}  # Strategic holding, never recommended for replacement

# Concentration alerts
CONCENTRATION_WARNING_THRESHOLD = 10.0%  # Alert at 10% weight
MAX_POSITION_SIZE = 15.0%                 # Target max 15% weight

# Research status markers
RESEARCH_NEEDED = "NEEDS_RESEARCH"        # All missing research data marked this way

# Current data state
METRICS_DEFINED = 26                      # Total metrics in system
METRICS_POPULATED = 4                     # Current per holding: thesis_health, liquidity, margin, quality
METRICS_RESEARCH_NEEDED = 22              # Fundamentals + frameworks + IBD
```

---

## **Maintenance Schedule**

### **Daily Operations**
```bash
# Morning (before market open)
./venv/bin/python3 run_portfolio_engine_full.py

# Output available for morning report at 9:30 AM ET
# Check: reports/morning_cio_report_latest.md
```

### **Weekly**
```bash
# Check data quality status
grep data_quality_score data/mcleod_research_latest.csv

# If >= 60%, holdings will unblock automatically
```

### **As Needed (Research Population)**
```bash
# Edit research data
vi data/mcleod_research_latest.json

# Re-run portfolio engine
./venv/bin/python3 engine/portfolio_engine.py

# Check updated rankings
head -5 data/mcleod_core_rankings_latest.csv
```

---

## **Performance Expectations**

| Operation | Time | Status |
|-----------|------|--------|
| Research Engine | 1.5 sec | Fast |
| Portfolio Engine | 1.0 sec | Fast |
| Morning Report | 0.5 sec | Fast |
| Full Workflow | 3.0 sec | Fast |
| Schwab Sync | 1.0 sec | Moderate |

**Total Daily Overhead:** ~3 seconds (negligible)

---

## **File Locations**

```
/Users/mason/Library/CloudStorage/Dropbox/McLeod Capital/McLeod Alpha/

├── engine/
│   ├── research_engine.py              ← Research orchestration
│   ├── portfolio_engine.py             ← Portfolio analysis (updated)
│   └── __init__.py
│
├── config/
│   └── mcleod_core_metrics.json        ← 26 metrics definitions
│
├── data/
│   ├── schwab_portfolio_latest.json    ← From Schwab API
│   ├── schwab_positions_latest.csv     ← From Schwab API
│   ├── mcleod_research_latest.json     ← Research output
│   ├── mcleod_research_latest.csv      ← Research output (CSV)
│   ├── mcleod_core_rankings_latest.csv ← Rankings (blocked)
│   ├── eipv_rankings_latest.csv        ← EIPV (operational)
│   └── target_weights_latest.csv       ← Targets (operational)
│
├── reports/
│   ├── morning_cio_report.py           ← Report generator
│   └── morning_cio_report_latest.md    ← Daily report output
│
├── portfolio_sync.py                   ← Schwab sync
├── run_portfolio_engine_full.py        ← Full workflow orchestrator
│
├── RESEARCH_ENGINE_SUMMARY.md          ← Detailed documentation
├── RESEARCH_ENGINE_FINAL_STATUS.md     ← Status report
└── RESEARCH_ENGINE_QUICKREF.md         ← This file

Python Environment:
  venv/bin/python3 (Python 3.11.15)
  
External APIs:
  Schwab: token.json (auth)
  Account: 33310903 (MARGIN)
```

---

## **Support & Questions**

**System Operational?** ✅ Yes  
**All Tests Passing?** ✅ Yes  
**Ready for Production?** ✅ Yes  
**Ready for Research Population?** ✅ Yes  

**Next: Populate Fundamental Research Metrics**
- Target: 15+ metrics per holding
- Result: Unlock all 20 holdings for core rankings
- Timeline: Flexible (populate as research completed)

---

**Last Updated:** 2026-07-14 15:25 UTC  
**Status:** OPERATIONAL  
**Version:** 1.0.0
