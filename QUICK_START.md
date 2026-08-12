# Quick Start - DataMind AI Intelligent Agent

## Your Application is Running! 🚀

**Server URL:** http://localhost:8000

## Two Modes Available

### 1. Original Mode (Backward Compatible)
**Endpoint:** `http://localhost:8000/api/query/stream`
- Uses classic AgentController
- All existing functionality preserved
- Suitable for simple queries

### 2. Intelligent Mode (New! ✨)
**Endpoint:** `http://localhost:8000/api/query/intelligent/stream`
- Uses new IntelligentAgent
- Deep question analysis
- Multi-step reasoning
- Result validation
- **Recommended for complex queries**

## Test the Intelligent Agent

### Option 1: Via Browser
1. Open http://localhost:8000
2. The UI uses the original endpoint by default
3. To test intelligent mode, you'll need to modify `public/app.js` to use the new endpoint

### Option 2: Via Test Script (Recommended)
```bash
python test_intelligent_agent.py
```

This will test three critical scenarios:
1. Multi-step category→product drill-down
2. Top 5 products by revenue
3. Monthly revenue trend

### Option 3: Via cURL
```bash
# Test intelligent endpoint
curl "http://localhost:8000/api/query/intelligent/stream?question=Which+product+category+generates+the+highest+revenue%2C+and+what+are+the+top+3+products+in+that+category%3F"
```

## Critical Test Cases

### 🎯 Multi-Step Question (Tests New Intelligence)
```
Question: "Which product category generates the highest revenue, 
          and what are the top 3 products in that category?"

Expected Behavior:
✅ Analyzes question as multi-step
✅ Step 1: Calculate revenue by ALL categories
✅ Step 2: Extract highest revenue category
✅ Step 3: Query products in THAT category (using actual result)
✅ Step 4: Validate exactly 3 products returned
✅ Generates TWO visualizations
✅ Explanation uses actual values from validated results
```

### 📊 Simple Ranking
```
Question: "What are the top 5 best-selling products by revenue?"

Expected Behavior:
✅ Single-step query plan
✅ Returns exactly 5 products
✅ Sorted by revenue descending
✅ Bar chart visualization
✅ Statistical explanation
```

### 📈 Trend Analysis
```
Question: "Show monthly revenue trend for 2025"

Expected Behavior:
✅ Time-series analysis
✅ Date filtering for 2025
✅ Line chart visualization
✅ Monthly breakdown
```

## Event Types to Watch For

When testing the intelligent endpoint, you'll see these SSE events:

| Event | Meaning |
|-------|---------|
| `analysis` | Question has been analyzed (entities, metrics, etc.) |
| `plan` | Execution plan created with step descriptions |
| `step_start` | Starting an analytical step |
| `sql` | SQL query executed with results |
| `extraction` | Identifier extracted from previous result |
| `chart` | Visualization generated |
| `insights` | Statistical explanation created |
| `answer_chunk` | Streaming final answer text |
| `complete` | All steps finished successfully |
| `validation_failed` | Validation error (will attempt correction) |

## Configuration

### Current Settings (from `.env`)
```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-proj-...
OPENAI_MODEL=gpt-4o
```

### Switch Providers
Update `.env` to use different LLM:
```env
# Use Google Gemini
LLM_PROVIDER=gemini
GEMINI_API_KEY=your-key

# Use Groq (Llama 3.1)
LLM_PROVIDER=groq
GROQ_API_KEY=your-key

# Use Mock (offline testing)
LLM_PROVIDER=mock
```

Restart server after changes:
```bash
# Stop current server (Ctrl+C)
# Then start again:
uvicorn src.main:app --reload --port 8000
```

## Comparing Original vs Intelligent

### Test Both Modes
```bash
# Original mode
curl "http://localhost:8000/api/query/stream?question=YOUR_QUESTION"

# Intelligent mode
curl "http://localhost:8000/api/query/intelligent/stream?question=YOUR_QUESTION"
```

### Key Differences

**Original Mode:**
- Simpler, faster for basic queries
- Single attempt at SQL generation
- Less validation
- May produce incorrect results for complex multi-step questions

**Intelligent Mode:**
- Deep question understanding
- Multi-step planning with dependencies
- Result validation at each step
- Automatic error correction
- Better for complex analytical questions
- More reliable and accurate

## Frontend Integration

### Update UI to Use Intelligent Mode

Edit `public/app.js`, find the query endpoint and change:

**From:**
```javascript
const endpoint = `/api/query/stream?question=${encodeURIComponent(question)}`;
```

**To:**
```javascript
const endpoint = `/api/query/intelligent/stream?question=${encodeURIComponent(question)}`;
```

Or create a toggle:
```javascript
const mode = document.getElementById('intelligentMode').checked;
const endpoint = mode 
  ? `/api/query/intelligent/stream?question=${encodeURIComponent(question)}`
  : `/api/query/stream?question=${encodeURIComponent(question)}`;
```

## Troubleshooting

### Server Not Starting
```bash
# Check if port is in use
netstat -ano | findstr :8000

# Install dependencies
pip install -r requirements.txt

# Check database exists
ls data/ecommerce.db
```

### Intelligent Agent Errors
Check server logs for:
```
[Validation] - Shows validation issues
[Correction] - Shows retry attempts  
[LLM Error] - Shows LLM provider issues
```

### LLM Quota Exceeded
Server automatically falls back to MockProvider:
```
[Fallback] LLM provider error: quota exceeded. Falling back to offline mock mode...
```

## Next Steps

1. ✅ **Test the intelligent endpoint** with critical multi-step questions
2. ✅ **Compare results** between original and intelligent modes
3. ✅ **Monitor validation success rates** in server logs
4. ✅ **Update frontend** to use intelligent mode when ready
5. ✅ **Gather user feedback** on answer quality
6. ✅ **Gradually migrate** queries to intelligent mode

## Support Files

- `INTELLIGENT_AGENT_UPGRADE.md` - Full technical documentation
- `IMPLEMENTATION_SUMMARY.md` - Implementation details
- `test_intelligent_agent.py` - Automated testing
- `README.md` - Updated project README

## Success Metrics

Monitor these to validate the upgrade:
- ✅ Multi-step questions answered correctly
- ✅ No hardcoded values in dependent queries
- ✅ Validation success rate > 90%
- ✅ Explanations match actual query results
- ✅ Appropriate visualizations selected
- ✅ Error correction successful rate
- ✅ User satisfaction with answer quality

## Questions?

Check the documentation:
- **Technical details**: `INTELLIGENT_AGENT_UPGRADE.md`
- **Implementation**: `IMPLEMENTATION_SUMMARY.md`
- **Original docs**: `README.md`

The intelligent agent makes your DataMind AI application production-ready with reliable, validated, data-grounded analytics! 🎉
