# 🤖 AI-Readable Audit Log & Changelog (AI_CHANGELOG.md)

This log is specifically maintained to help future AI systems and developers inspect, audit, and understand the persistent changes made to the **Gözde Plastik Reminder Bot & B2B CRM** codebase.

---

## 📊 Programmatic Activity Registry (JSON Metadata)

Future AIs can parse this JSON block directly to build context on repository progress and state changes:

```json
{
  "system_name": "Gözde Plastik Müşteri Hatırlatma Botu & CRM",
  "repository": "https://github.com/ekremtugay944-spec/ses-kaydedici.git",
  "audit_version": "2.4.0",
  "last_updated": "2026-05-21T14:30:00+03:00",
  "changes": [
    {
      "version": "2.4.0",
      "date": "2026-05-21",
      "author": "Antigravity (AI Developer)",
      "impact": "High",
      "modified_files": [
        "bot.py"
      ],
      "description": "Implemented dynamic routing of AI conversational intents, connecting natural-language queries directly to bot reporting and inquiry command handlers.",
      "key_features": [
        "Conversation-to-Intent translation",
        "Mocking Context for Telegram compatibility",
        "Seamless database-backed customer fuzzy lookup for card and risk details"
      ]
    },
    {
      "version": "2.3.0",
      "date": "2026-05-21",
      "author": "Antigravity (AI Developer)",
      "impact": "Medium-High",
      "modified_files": [
        "parser.py"
      ],
      "description": "Refactored Gemini parsing schema to identify conversational queries, QA, greetings, and report requests, introducing 'is_conversational' and structured 'chat_response' intent formats.",
      "key_features": [
        "Added is_conversational and chat_response properties to Gemini output schema",
        "Configured specific 'intent:<action>' outputs for report queries (bugun, yarin, kasa, risk, etc.)"
      ]
    },
    {
      "version": "2.2.1",
      "date": "2026-05-21",
      "author": "Antigravity (AI Developer)",
      "impact": "Medium-High",
      "modified_files": [
        "parser.py"
      ],
      "description": "Implemented isolated date phrase extraction using hybrid AI parsing to handle complex natural language inputs like 'ali sürgülü yarın ödeme yapacak'.",
      "key_features": [
        "Added 'date_phrase' to Gemini extraction schema",
        "Added fallback date parsing to ensure zero-clarification-needed reminder entry"
      ]
    }
  ]
}
```

---

## 📜 Detailed Change Audit Log

### 🆕 v2.4.0 — Conversational Intent Routing & Reporting Commands (21 May 2026)
* **Goal**: Allow users to organically request reports, lists, cash summaries, or customer profiles in plain conversational Turkish (e.g. *"yarın ne var?"*, *"Ahmet Bey'in risk durumunu göster"*) without manually typing slash commands.
* **Modified File**: [bot.py](file:///Users/primesports/Desktop/ses-kaydedici-crm/bot.py)
* **Key Implementation Details**:
  - Intercepted conversational classifications in `process_text()`.
  - Parsed Gemini's output format `intent:<action>[:<param>]` (e.g., `intent:yarin` or `intent:kart:Ahmet Bey`).
  - Implemented automatic routing to matching commands:
    - `intent:bugun` ➔ Calls `cmd_bugun(update, mock_context)`
    - `intent:yarin` ➔ Calls `cmd_yarin(update, mock_context)`
    - `intent:liste` ➔ Calls `cmd_liste(update, mock_context)`
    - `intent:kasa` ➔ Calls `cmd_kasa(update, mock_context)`
    - `intent:dashboard` ➔ Calls `cmd_dashboard(update, mock_context)`
    - `intent:riskli` ➔ Calls `cmd_riskli(update, mock_context)`
    - `intent:musteriler` ➔ Calls `cmd_musteriler(update, mock_context)`
    - `intent:kart:<name>` ➔ Performs fuzzy customer search and displays customer card via `_show_card(update, customer_name)`.
    - `intent:risk:<name>` ➔ Performs fuzzy customer search and outputs custom database risk calculations and metrics directly.
  - Implemented `MockContext` class to seamlessly satisfy parameter expectations of legacy command handlers without crashing.
* **Verification**:
  - Verified that `"yarın ne hatırlatmalarım var?"` yields intent classification `intent:yarin`.
  - Verified that `"Ahmet Bey'in kartını gösterir misin?"` yields intent classification `intent:kart:Ahmet Bey`.
  - Verified that `"Ahmet Bey'in risk durumunu göster"` yields intent classification `intent:risk:Ahmet Bey`.
  - Verified that generic daily greetings (e.g., `"selam, nasılsın bugün?"`) fall back to natural, friendly B2B CRM assistant dialogue responses instead of triggering intents or creating reminders.

---

### 🆕 v2.3.0 — Gemini Intent Classification & B2B CRM Dialogue (21 May 2026)
* **Goal**: Prevent the bot from getting confused when users send friendly conversational messages (like *"selam nasılsın"* or *"sen ne işe yararsın"*), instead of strict reminder/CRM command statements.
* **Modified File**: [parser.py](file:///Users/primesports/Desktop/ses-kaydedici-crm/parser.py)
* **Key Implementation Details**:
  - Expanded `STRUCTURE_PROMPT` to analyze and classify conversational greetings, helper questions, and report requests.
  - Added two crucial fields to the JSON output of the model:
    1. `is_conversational` (boolean): Flags conversational / report-inquiry messages.
    2. `chat_response` (string): Pre-generates the warm, friendly Turkish assistant response or outputs structured `intent:` strings for reporting queries.
* **Verification**:
  - Validated that daily greetings result in natural assistant chatter replies.
  - Verified that report requests cleanly yield structured intents.

---

### 🆕 v2.2.1 — Isolated Date Phrase Extraction & Hybrid Parsing (21 May 2026)
* **Goal**: Fix issues where complex natural sentences (like *"ali sürgülü yarın ödeme yapacak"*) confused `dateparser` due to embedded names and action words, prompting the bot to ask clarifying questions unnecessarily.
* **Modified File**: [parser.py](file:///Users/primesports/Desktop/ses-kaydedici-crm/parser.py)
* **Key Implementation Details**:
  - Refactored prompt schema to ask Gemini to extract clean, isolated date words (e.g. `"yarın"`, `"haftaya Salı"`, `"ay sonu"`) into a new property `date_phrase`.
  - Updated `parse_voice_text()` to first feed the clean, isolated `date_phrase` into `dateparser`.
  - Kept full-sentence parsing as a robust fallback.
* **Verification**:
  - Tested multiple Turkish sentences (`ali sürgülü yarın ödeme yapacak`, `ay sonunda 15 bin lira tahsilat`, etc.) which successfully resolved to exact timestamps without any clarification prompts.

---

## 🛠️ Instructions for Subsequent AI Models

When taking over the development of this repository:
1. **Analyze logs & state**: Check `bot.log` for runtime status and `AI_CHANGELOG.md` for recent modifications.
2. **Use local miniconda environments**: Always run testing and git commands using `/Users/primesports/miniconda/bin/python3` and `/Users/primesports/miniconda/bin/git`.
3. **Keep the database WAL active**: SQLite is configured in WAL mode for maximum reliability on this Apple Silicon Mac Mini. Ensure no operations lock or corrupt `reminders.db`.
4. **Preserve this audit trail**: Always add your updates chronologically to `AI_CHANGELOG.md` and commit the file as part of your git flow.
